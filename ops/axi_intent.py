"""
axi_intent.py
─────────────
Intent classifier для Axi: один быстрый вызов локального Ollama определяет действие пользователя
и возвращает структурированный JSON вместо цепочки regex-проверок.

Использование:
    from axi_intent import classify_intent

    result = await classify_intent(
        text="удали inspection_report из omi",
        context={
            "has_pending_task": True,
            "last_task_num": 7,
            "bot_mentioned": True,
            "chat_type": "group",
        },
    )
    # {"action": "delete_omi", "params": {"query": "inspection_report"}}
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict

import httpx

logger = logging.getLogger("axi_intent")

# ── In-process LRU: повторные одинаковые запросы intent → без повторного Ollama/Gemini ──
_intent_cache_lock = threading.Lock()
_intent_cache: OrderedDict[str, tuple[dict, float | None]] = OrderedDict()


def _intent_cache_enabled() -> bool:
    return os.environ.get("AXI_INTENT_RESPONSE_CACHE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _intent_cache_max_entries() -> int:
    try:
        return max(16, min(int(os.environ.get("AXI_INTENT_CACHE_MAX", "512") or "512"), 50_000))
    except ValueError:
        return 512


def _intent_cache_ttl_sec() -> float:
    raw = os.environ.get("AXI_INTENT_CACHE_TTL_SEC", "0").strip()
    if not raw:
        return 0.0
    try:
        v = float(raw)
        return v if v > 0 else 0.0
    except ValueError:
        return 0.0


def _intent_cache_fingerprint(
    text: str,
    context: dict | None,
    chat_history: list[tuple[str, str]] | None,
    intent_extra: str | None,
    *,
    backend_pref: str,
    ollama_model: str,
    quality_backend: str,
) -> str:
    """SHA-256 от входов; история и контекст обязаны входить, иначе ложные попадания."""
    h = hashlib.sha256()
    h.update((text or "").strip().encode("utf-8"))
    h.update(b"\0")
    h.update(json.dumps(context or {}, sort_keys=True, ensure_ascii=True).encode("utf-8"))
    h.update(b"\0")
    h.update(json.dumps(list(chat_history or []), ensure_ascii=True).encode("utf-8"))
    h.update(b"\0")
    h.update((intent_extra or "").encode("utf-8"))
    h.update(b"\0")
    h.update(backend_pref.encode("ascii"))
    h.update(b"\0")
    h.update(ollama_model.encode("utf-8"))
    h.update(b"\0")
    h.update(quality_backend.encode("utf-8"))
    return h.hexdigest()


def _intent_cache_get(fp: str) -> dict | None:
    ttl = _intent_cache_ttl_sec()
    now = time.monotonic()
    with _intent_cache_lock:
        if fp not in _intent_cache:
            return None
        payload, exp = _intent_cache[fp]
        if exp is not None and now > exp:
            del _intent_cache[fp]
            return None
        _intent_cache.move_to_end(fp)
        return copy.deepcopy(payload)


def _intent_cache_put(fp: str, result: dict) -> None:
    ttl = _intent_cache_ttl_sec()
    exp: float | None = None
    if ttl > 0:
        exp = time.monotonic() + ttl
    max_n = _intent_cache_max_entries()
    with _intent_cache_lock:
        _intent_cache[fp] = (copy.deepcopy(result), exp)
        _intent_cache.move_to_end(fp)
        while len(_intent_cache) > max_n:
            _intent_cache.popitem(last=False)

# NIM fallback: используется если Ollama недоступна
_INTENT_NIM_URL = os.environ.get("NVIDIA_NIM_URL", "http://127.0.0.1:8082").rstrip("/")
_INTENT_NIM_KEY = os.environ.get("NVIDIA_NIM_API_KEY", "")

_SYSTEM_PROMPT = """\
You are Axi — an intelligent AI assistant embedded in a Telegram chat. Your job is to understand \
what the user wants based on their CURRENT message AND the CONVERSATION HISTORY provided below.

**CRITICAL: You are a context-aware AI, not a keyword matcher.** \
Read the conversation history carefully. The user's message may be a follow-up, a reference to \
something discussed earlier, or an implicit continuation. Resolve pronouns ("it", "this", "that file", \
"его", "этот", "тот файл"), ellipsis, and contextual references using the conversation history.

**Language policy (RU/EN):** infer intent semantically in any language, but keep user-facing meaning in the user's language. \
For Russian input, route with Russian semantics; for English input, route with English semantics. \
Do not switch language unless the user asks for translation.

Examples of contextual reasoning:
- User sent a file 2 messages ago, now says "обработай" → process_task (the file they just sent)
- User asked about task #5 earlier, now says "а результат?" → task_status for #5
- User says "Я прислал файл" after sending a document → they're confirming upload, not requesting a new one → save_to_inbox or task_status depending on whether it was already registered
- User says "удали" without specifying what → look at conversation: what were they just discussing?
- User says "пришли" → in Russian this means "send TO ME" (user receives), never upload

Return ONE JSON object. No markdown, no explanation — ONLY the JSON.

## Available actions and their params:

- **delete_file** — delete a file from local storage. params: {query}
- **delete_omi** — delete a record from Omi registry/database. params: {query}
- **delete_from_queue** — delete file(s) from OCR inbox queue, or remove duplicates. params: {query, mode: "file"|"duplicates"}
- **stop_task** — cancel/stop an Axi pipeline task #N. params: {task_num: int}
- **search_history** — search previous chat messages. params: {query}
- **anonymize** — anonymize/redact the current document (last task). params: {}
- **send_anonymized** — send the anonymized version of a file. params: {}
- **use_template** — generate a document using a template. params: {template_keyword, task_num (optional int)}
- **send_master_doc** — receive a master document stored in Omi. params: {query}
- **send_file** — receive a specific file or previously generated report. params: {filename (if exact name known), keywords (list)}
- **save_to_inbox** — upload/save a document for OCR/registration. params: {}
- **list_tasks** — see Axi upload tasks (#1, #2…). params: {}
- **list_omi_docs** — see documents registered in Omi/AIMS database. params: {}
- **handoff_omi** — the user needs **Omi** (live AIMS registry on the server: move between P01–P10, archive by year, `/docgen` from registry, OCR queue on the Omi side, backups, skills — operations on paths/storage that only the Omi bot performs). You have **search/list** against the synced registry snapshot, not arbitrary server filesystem control like Omi. params: {reason (optional string), suggested_text (full user request repeated — same language; runtime queues it to Omi; Omi replies in chat)}
- **task_status** — status of a specific task. params: {task_num: int}
- **process_task** — run OCR or analysis on a task. params: {task_num: int or null}
- **generate_docx** — create/write a new Word document. params: {}
- **check_standards** — run a compliance/standards review on an uploaded document or described scope. Use when user says "проверь на стандарты", "check against standards", "compliance check", "аудит стандартов", "verify against ISO/API/ASME". params: {query (optional description of what to check)}
- **rename_file** — rename ONE specific file based on its content. params: {filename}
- **batch_rename** — rename ALL files with coded/meaningless names. params: {}
- **ocr_queue** — see the OCR processing queue. params: {}
- **omi_status** — check Omi archive bot health/state. params: {}
- **job_filter_help** — factual explanation of vacancy/email monitoring (Job Filter bot, IMAP env). Use when user asks how email/job search by mail works. params: {}
- **clear_axi_tasks** — remove finished Axi task rows from DB for this chat (not OCR inbox files). params: {task_num (optional int), wipe_all (optional bool)}
- **task_intake_dialog** — start semantic intake in live chat before execution (confirm target result, ask sources, then ask for file-upload markers start/end, then plan approval). params: {result_goal (optional), sources (optional)}
- **file_watch_mode** — switch to strict file-by-file verification mode: wait for uploads one-by-one, check if each file is already processed/registered, reject duplicate execution, do not auto-start OCR/compliance pipelines. params: {}
- **chat** — general conversation, questions, answers — no tool needed. params: {}
- **clarify** — request is ambiguous, ask ONE short question (same language as user). params: {question: string}

## Disambiguation guidelines:

Think about WHAT the user is referring to, not just the keywords they used:
- "delete" → WHERE? Omi/database → delete_omi. Queue/inbox → delete_from_queue. Local file → delete_file. Infer from context if not stated.
- "clear task list" / "очисти очередь задач" / "задача уже зарегистрирована, убери из списка" → **clear_axi_tasks** (Axi DB tasks #N), NOT delete_from_queue unless they mean files in inbox/income.
- Questions about **Job Filter / email vacancies / IMAP / parsing job emails** → **job_filter_help**. Do NOT invent script names (e.g. `email_parser_job_alerts.py`, `ocr-watcher`, "Skill 24") — those are not authoritative; the real service is `job_filter_bot` + env vars.
- **Registry vs Omi bot**: "show/list/search documents in the registry" → **list_omi_docs** or **send_master_doc** as context implies. "Move this file to P04", "archive 2021 in P03", "run registry docgen bundle", "fix OCR skipped in Omi inbox" → **handoff_omi** (you cannot execute those; registry stays fresh after Omi syncs, but execution is Omi’s job). Do not dead-end with **chat** when the user clearly needs Omi.
- "send/find/show a report" → send_file (existing). "make/create/write a report" → generate_docx (new).
- "проверь на стандарты" / "check compliance" / "аудит стандартов" / "verify against ISO/API" → **check_standards** (not generate_docx, not chat). The user wants a compliance gap analysis, not a document to be written.
- Three main pipelines: **save_to_inbox** (загрузи в базу / load to DB), **check_standards** (проверь на стандарты / compliance), **generate_docx** (подготовь документ / prepare doc). Route each correctly.
- For multi-file tasks (e.g. merge CV/resume from many files), prefer **task_intake_dialog** before execution: confirm desired output, ask source mix, request upload start marker and upload-complete marker.
- **Artifact delivery vs chat:** if the user says the bot **did not send a file**, **where is the file**, or **status of task #N** after promised output — use **task_status** (and then **send_file** / **process_task** if the pipeline did not run or the file was not attached). Do **not** route those to **chat** so the runtime can ground the reply in tasks/storage instead of free-form "100% done" narration.
- If user explicitly says to wait for files one-by-one and only verify processing/registration status, use **file_watch_mode** and avoid standards/style guided flows.
- "stop task #N" / "отмени задачу #N" → stop_task (not delete_from_queue).
- "Omi status" / "что делает Omi" → omi_status (Omi service, not Axi task).
- A filename in the message does NOT mean process_task unless user explicitly asks to process/OCR it.
- When task_num is needed but not stated: if context shows has_pending_task, use last_task_num.
- Use **clarify** only when the ambiguity would lead to a wrong tool — prefer intelligent inference from context over asking.

## Context (provided by system):

You will receive these fields (any may be absent):
- has_pending_task, last_task_num — active task info
- bot_mentioned — whether user said "@Axi" or "Axi"
- chat_type — "private", "group", or "supergroup"
- pipeline_running, pipeline_task_label — whether a background OCR/analysis is running
- recent_files — files recently sent in this chat

When pipeline_running is true: if the message is about the running task, route normally. \
If it's clearly a NEW task, route to the correct action. If ambiguous, use clarify.

## Response format:
{"action": "<action>", "params": {<params or empty>}}
"""


def _intent_system_with_extra(extra: str | None) -> str:
    """Базовый промпт intent + опциональные пользовательские примеры (few-shot из БД)."""
    e = (extra or "").strip()
    if not e:
        return _SYSTEM_PROMPT
    return (
        _SYSTEM_PROMPT
        + "\n\n## User-trained routing (real requests — prefer when wording is similar)\n"
        + e
    )


def _parse_json_from_response(text: str) -> dict | None:
    """Извлекает JSON из ответа LLM без regex."""
    payloads: list[str] = []
    raw = (text or "").strip()
    if not raw:
        return None

    payloads.append(raw)
    if "```" in raw:
        parts = raw.split("```")
        for i in range(1, len(parts), 2):
            block = parts[i].strip()
            if block.lower().startswith("json"):
                block = block[4:].strip()
            if block:
                payloads.append(block)

    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        payloads.append(raw[first:last + 1])

    seen: set[str] = set()
    for candidate in payloads:
        c = candidate.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            data = json.loads(c)
            if isinstance(data, dict) and "action" in data:
                return data
        except json.JSONDecodeError:
            continue
    return None


def _build_message_text(
    text: str,
    context: dict | None,
    chat_history: list[tuple[str, str]] | None = None,
) -> str:
    """Build a single prompt from chat history + current message for Ollama/NIM."""
    parts = []

    if chat_history:
        for role, msg in chat_history:
            parts.append(f"{role.upper()}: {msg}")

    if context:
        ctx_parts = []
        for k, v in context.items():
            if k == "recent_chat_block":
                continue
            if v is not None:
                ctx_parts.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        if ctx_parts:
            parts.append("[System context]\n" + "\n".join(ctx_parts))

    parts.append(f"USER: {text}")
    return "\n\n".join(parts)


def _intent_llm_backend() -> str:
    return "ollama"


async def _classify_intent_ollama(
    text: str,
    context: dict | None,
    chat_history: list[tuple[str, str]] | None,
    *,
    intent_extra: str | None = None,
) -> dict | None:
    """Intent через Ollama/DGX (/api/chat). Требует ops/ollama_resolve + DGX_* в контейнере."""
    try:
        from ollama_resolve import effective_intent_ollama_base_url, ollama_apply_keep_alive
    except ImportError:
        return None

    model = (
        os.environ.get("AXI_INTENT_OLLAMA_MODEL", os.environ.get("AXI_OLLAMA_MODEL", "axi_omi_sphere")).strip()
        or "axi_omi_sphere"
    )
    base = effective_intent_ollama_base_url().rstrip("/")
    _sys = _intent_system_with_extra(intent_extra)
    messages: list[dict] = [{"role": "system", "content": _sys}]
    if chat_history:
        for role, msg in chat_history:
            orole = "user" if role == "user" else "assistant"
            messages.append({"role": orole, "content": (msg or "")[:8000]})
    ctx_block = ""
    if context:
        ctx_parts = []
        for k, v in context.items():
            if k == "recent_chat_block":
                continue
            if v is not None:
                ctx_parts.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        if ctx_parts:
            ctx_block = "\n\n[System context]\n" + "\n".join(ctx_parts)
    messages.append({"role": "user", "content": ((text or "") + ctx_block)[:14000]})

    # 70B на DGX при холодном старте / длинном промпте часто >120s — иначе ReadTimeout и лишний fallback.
    _intent_read = float(os.environ.get("AXI_INTENT_OLLAMA_TIMEOUT_SEC", "300"))
    _intent_read = max(60.0, min(_intent_read, 900.0))
    # httpx: либо общий default, либо явно connect/read/write/pool — иначе ValueError.
    timeout = httpx.Timeout(connect=30.0, read=_intent_read, write=120.0, pool=30.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            _chat_body: dict = {"model": model, "messages": messages, "stream": False}
            ollama_apply_keep_alive(_chat_body)
            r = await client.post(f"{base}/api/chat", json=_chat_body)
            if r.status_code != 200:
                logger.warning("intent_ollama_http status=%s body=%s", r.status_code, r.text[:200])
                return None
            data = r.json()
            msg = data.get("message") or {}
            raw = msg.get("content") if isinstance(msg.get("content"), str) else ""
            result = _parse_json_from_response(raw or "")
            if result:
                logger.debug("intent_ollama: %s → %s", text[:60], result.get("action"))
            return result
    except Exception as e:
        logger.warning("intent_ollama_error: %r", e)
        return None


async def classify_intent(
    text: str,
    context: dict | None = None,
    *,
    chat_history: list[tuple[str, str]] | None = None,
    intent_extra: str | None = None,
) -> dict:
    """
    Классифицирует намерение: по умолчанию Ollama/DGX локально, с NIM fallback если Ollama недоступна.

    chat_history: list of (role, content) tuples from DB — chronological order,
    role is "user" or "model".

    Возвращает dict вида:
        {"action": "delete_file", "params": {"query": "report.pdf"}}

    intent_extra: дополнительный текст к system prompt (few-shot из БД Axi — axi_learned_intent).

    Кэш ответа (AXI_INTENT_RESPONSE_CACHE=1): LRU в процессе, ключ = SHA-256 текста + контекст + история + intent_extra.

    При ошибке или неопределённости возвращает:
        {"action": "chat", "params": {}}
    """
    intent_ollama_model = (
        os.environ.get(
            "AXI_INTENT_OLLAMA_MODEL",
            os.environ.get("AXI_OLLAMA_MODEL", "axi_omi_sphere"),
        ).strip()
        or "axi_omi_sphere"
    )
    try:
        from ollama_resolve import ollama_schedule_telegram_stack_warm, pc_assist_stack_enabled

        if pc_assist_stack_enabled():
            await asyncio.to_thread(ollama_schedule_telegram_stack_warm)
    except Exception:
        logger.debug("axi_intent: ollama_schedule_telegram_stack_warm failed", exc_info=True)

    fp = _intent_cache_fingerprint(
        text,
        context,
        chat_history,
        intent_extra,
        backend_pref="ollama",
        ollama_model=intent_ollama_model,
        quality_backend="",
    )
    if _intent_cache_enabled():
        hit = _intent_cache_get(fp)
        if hit is not None:
            logger.debug("intent_cache_hit action=%s", hit.get("action"))
            return hit

    res = None
    skip_ollama = False
    if os.environ.get("AXI_CHAT_OLLAMA_READY_CHECK", "0").strip() == "1":
        try:
            from ollama_resolve import (
                effective_intent_ollama_base_url,
                ollama_model_is_loaded,
                ollama_schedule_background_warm,
            )

            intent_model = intent_ollama_model
            base_chk = await asyncio.to_thread(effective_intent_ollama_base_url)
            loaded = await asyncio.to_thread(ollama_model_is_loaded, intent_model, base_chk)
            if not loaded:
                skip_ollama = True
                logger.info("intent_skip_ollama_until_loaded model=%s", intent_model)
                await asyncio.to_thread(ollama_schedule_background_warm, intent_model, base_chk)
        except Exception as e:
            logger.warning("intent_ollama_ps_check_failed: %s", e)
    if not skip_ollama:
        res = await _classify_intent_ollama(
            text, context, chat_history, intent_extra=intent_extra
        )
    if res:
        if _intent_cache_enabled():
            _intent_cache_put(fp, res)
        return res

    logger.warning("intent_ollama_unavailable_trying_nim_fallback")
    _sys_full = _intent_system_with_extra(intent_extra)
    msg_text = _build_message_text(text, context, chat_history)

    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        payload = {
            "model": "meta/llama-3.1-405b-instruct",
            "messages": [
                {"role": "system", "content": _sys_full},
                {"role": "user", "content": msg_text},
            ],
            "temperature": 0.0,
            "max_tokens": 320,
        }
        headers = {}
        if _INTENT_NIM_KEY:
            headers["Authorization"] = f"Bearer {_INTENT_NIM_KEY}"

        try:
            resp = await client.post(
                f"{_INTENT_NIM_URL}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 200:
                body = resp.json()
                raw = body.get("choices", [{}])[0].get("message", {}).get("content", "")
                result = _parse_json_from_response(raw)
                if result:
                    logger.debug("intent_nim: %s → %s", text[:60], result.get("action"))
                    if _intent_cache_enabled():
                        _intent_cache_put(fp, result)
                    return result
        except (httpx.TimeoutException, httpx.NetworkError):
            pass
        except Exception as e:
            logger.warning("intent_nim_error: %s", e)

    logger.warning("intent_classify_fallback: chat (no valid response for %r)", text[:60])
    return {"action": "chat", "params": {}}
