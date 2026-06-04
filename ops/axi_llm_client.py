"""
axi_llm_client.py
─────────────────
Unified LLM call wrapper for Axi bot.
Extracted from axi_bot.py (Phase C Task 2 refactor).

Provides:
  _gemini_reply, _anthropic_reply, _anthropic_classify_intent
  _axi_llm_local_first_enabled, _get_llm_semaphore
  _animate_progress, _ft_log_example
  _local_ollama_reply_sync, _cloud_llm_reply
  _llm_reply, _llm_reply_inner
  _should_web_search
  _axi_system_prompt, _load_axi_skill_context

Config is read from os.environ at call time — no circular imports.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx as _httpx

log = logging.getLogger("axi")

# ── Config (read from env at import time, matching axi_bot.py) ─────────────────

AXI_NAME = os.environ.get("AXI_NAME", "Axi").strip()
AXI_LLM_LOCAL_FIRST = os.environ.get("AXI_LLM_LOCAL_FIRST", "1").strip().lower() in ("1", "true", "yes", "on")
AXI_LLM_MAX_CONCURRENT = max(1, int(os.environ.get("AXI_LLM_MAX_CONCURRENT", "1")))
AXI_FT_LOG_ENABLED = os.environ.get("AXI_FT_LOG_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
AXI_FT_LOG_DIR = Path(os.environ.get("AXI_FT_LOG_DIR", "/data/axi_ft_log"))
AXI_WEB_SEARCH_ENABLED = False  # Disabled: NVIDIA NIM does not support Google Search grounding
ANTHROPIC_MODEL = os.environ.get("AXI_ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()

AXI_SYSTEM_PROMPT = os.environ.get(
    "AXI_SYSTEM_PROMPT",
    "You are Axi, a practical AI assistant embedded in a Telegram chat. "
    "Your primary job: answer questions, analyse documents, draft text, and generate files — directly, without ceremony.\n\n"
    "BEHAVIOUR RULES (follow strictly):\n"
    "1. Be concise. Do NOT open with a self-introduction, capability statement, or summary of what you 'see in the system' "
    "unless the user asked for it. Jump straight to the answer or the action.\n"
    "2. Do NOT volunteer ISO 55001 / AIMS / P-code / E-code mappings unless the user explicitly asks for them. "
    "If the user asks a general question (safety, engineering, drafting, web search, coding, etc.) — "
    "answer it as a general assistant.\n"
    "3. You CAN generate Word (.docx) files yourself. When a user asks for a report, updated document, or analysis "
    "in Word format: generate the content, save it as .docx using python-docx, and send it back in the same chat. "
    "Do NOT tell the user to ask Omi for docx generation — you handle it directly.\n"
    "4. Omi is a separate bot that manages the AIMS database and filesystem (move files, backup DB). "
    "Only redirect to Omi for: file moves/archives, DB backups, /docgen of multi-document bundles. "
    "For registry queries (what documents are registered, search by keyword/type/date, show full registry) — "
    "query aims_registry.db directly and return the result to the user. Do NOT tell the user to ask Omi.\n"
    "5. When a task file is in context (OCR text available): use it for the answer, but do NOT repeat the task metadata "
    "('Task #N, inbox file, ISO mapping…') every time. Mention it only if directly relevant.\n"
    "6. Web search: not available in local-only mode.\n"
    "7. Language: reply in English by default. Switch to the user's language only if they explicitly write in another language.\n"
    "8. For document review/improvement tasks: do the work (read OCR text, apply requested standards/rules, produce "
    "the updated content or file). Do not describe your plan at length — just do it and send the result.\n\n"
    "TERMINOLOGY (do not confuse):\n"
    "- **register a file / register file** = verb phrase: the *action* of adding a file into the AIMS registry database "
    "(ingest, OCR pipeline, row in aims_registry).\n"
    "- **the register / registry** = noun: the *document registry* as a system (the database of records), not a single file.\n"
    "- In user messages, «register file» usually means *perform registration*, not «the register object».\n\n"
    "ARTIFACT INTEGRITY (critical):\n"
    "- Do not claim a pipeline task is complete or that a file was delivered to the chat unless the runtime actually "
    "wrote the artifact and sent it via Telegram in the same handler turn.\n"
    "- Do not invent progress percentages unless they come from task DB state.\n"
    "- Do not promise that the file will be attached in the next message; either attach now or say generation failed.\n"
    "- If the user says they did not receive a file: acknowledge, check task/tools status — do not fabricate errors.",
).strip()


def _load_axi_skill_context() -> str:
    """Load Axi runtime skill pack for internal prompt injection."""
    try:
        from agents.agent_skill_loader import load_agent_skill_text

        text = load_agent_skill_text("axi")
        if text:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            log.info("Axi skill pack loaded: agent=axi chars=%d sha256=%s", len(text), digest)
        else:
            log.warning("Axi skill pack empty: agent=axi")
        return text or ""
    except Exception as exc:
        log.warning("Axi skill pack load failed: %s", exc)
        return ""


AXI_SKILL_CONTEXT = _load_axi_skill_context()


def _axi_system_prompt(base_prompt: str | None = None) -> str:
    """Build Axi system prompt with optional runtime skill context."""
    base = base_prompt if base_prompt is not None else AXI_SYSTEM_PROMPT
    if AXI_SKILL_CONTEXT:
        return base + "\n\n# Axi runtime skill pack\n" + AXI_SKILL_CONTEXT
    return base


# ── Semaphore ──────────────────────────────────────────────────────────────────

_llm_semaphore: asyncio.Semaphore | None = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(AXI_LLM_MAX_CONCURRENT)
    return _llm_semaphore


def _axi_llm_local_first_enabled() -> bool:
    return AXI_LLM_LOCAL_FIRST


# ── Progress animation ─────────────────────────────────────────────────────────

_PULSE_FRAMES = ("🧠", "💭", "⚙️", "🔄")


async def _animate_progress(
    msg,
    base_text: str,
    stop_event: asyncio.Event,
    *,
    interval: float = 12.0,
) -> None:
    """Edit progress_msg every interval seconds with elapsed time + rotating emoji."""
    t0 = time.perf_counter()
    idx = 0
    while not stop_event.is_set():
        await asyncio.sleep(interval)
        if stop_event.is_set():
            break
        elapsed = int(time.perf_counter() - t0)
        emoji = _PULSE_FRAMES[idx % len(_PULSE_FRAMES)]
        try:
            await msg.edit_text(f"⏱ {base_text} {elapsed}с {emoji}")
        except Exception:
            pass
        idx += 1


# ── Fine-tuning log ────────────────────────────────────────────────────────────

def _ft_log_example(
    messages: list[dict],
    response: str,
    source: str,
) -> None:
    """Append a chat example to daily JSONL for future fine-tuning. Silent on errors."""
    if not AXI_FT_LOG_ENABLED:
        return
    try:
        import json as _json
        AXI_FT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        record = _json.dumps(
            {
                "messages": messages + [{"role": "assistant", "content": response}],
                "source": source,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        with (AXI_FT_LOG_DIR / f"axi_ft_{date_str}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(record + "\n")
    except Exception as e:
        log.debug("_ft_log_example write failed: %s", e)


# ── NVIDIA NIM API helper ──────────────────────────────────────────────────────

async def _gemini_reply(
    text: str,
    *,
    extra_context: str = "",
    use_search: bool = False,
    system_override: str | None = None,
) -> str:
    """Call NVIDIA NIM API (llama-3.1-405b-instruct). Returns the text response or an error string."""
    nim_url = os.environ.get("NVIDIA_NIM_URL", "http://127.0.0.1:8082").rstrip("/")
    nim_key = os.environ.get("NVIDIA_NIM_API_KEY", "")

    sys_prompt = _axi_system_prompt(system_override)
    user_text = f"{extra_context}\n\n{text}".strip() if extra_context else text

    timeout = _httpx.Timeout(60.0, connect=10.0)
    model = "meta/llama-3.1-405b-instruct"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    headers = {"Content-Type": "application/json"}
    if nim_key:
        headers["Authorization"] = f"Bearer {nim_key}"

    try:
        async with _httpx.AsyncClient(timeout=timeout) as client:
            url = f"{nim_url}/v1/chat/completions"
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                body = resp.json()
                answer = (
                    body.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                ).strip()
                if answer:
                    return answer
            else:
                log.warning("NIM %s status=%s", model, resp.status_code)
    except (_httpx.TimeoutException, _httpx.NetworkError):
        pass
    except Exception as e:
        log.warning("NIM error: %s", e)

    return f"{AXI_NAME}: не удалось получить ответ от NIM."


# ── Anthropic / OmniRouter fallback ───────────────────────────────────────────

async def _anthropic_reply(
    text: str,
    *,
    extra_context: str = "",
    system_override: str | None = None,
    _notify_owners_fn=None,
) -> str:
    """Call Claude via OmniRouter. Used as fallback when NIM is unavailable.

    _notify_owners_fn: optional async callable(text) for owner notifications.
    """
    omnirouter_url = os.environ.get("AIMS_OMNIROUTER_URL", "http://127.0.0.1:8082").rstrip("/")
    auth_token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")
    model = os.environ.get("AIMS_ANTHROPIC_MODEL", ANTHROPIC_MODEL)

    sys_prompt = _axi_system_prompt(system_override)
    user_text = f"{extra_context}\n\n{text}".strip() if extra_context else text
    _CLOUD_MAX_CHARS = 40_000
    if len(user_text) > _CLOUD_MAX_CHARS:
        log.info("omnirouter: truncating payload %d→%d chars", len(user_text), _CLOUD_MAX_CHARS)
        user_text = user_text[:_CLOUD_MAX_CHARS] + "\n\n[...truncated for cloud processing...]"

    payload = {
        "model": model,
        "max_tokens": 8096,
        "system": sys_prompt,
        "messages": [{"role": "user", "content": user_text}],
    }
    _OMNIROUTER_HDRS = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }
    for _attempt in range(2):
        timeout = _httpx.Timeout(90.0 if _attempt == 0 else 60.0, connect=10.0)
        try:
            async with _httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{omnirouter_url}/v1/messages", json=payload, headers=_OMNIROUTER_HDRS)
            if resp.status_code == 200:
                body = resp.json()
                text_out = (body.get("content") or [{}])[0].get("text", "").strip()
                if text_out:
                    _ft_log_example(
                        [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_text}],
                        text_out,
                        source=f"omnirouter:{model}",
                    )
                    return text_out
            else:
                log.warning("omnirouter status=%s body=%s", resp.status_code, resp.text[:200])
                if resp.status_code in (402, 529) and _notify_owners_fn is not None:
                    asyncio.ensure_future(_notify_owners_fn(
                        f"🚨 Axi: OmniRouter ошибка {resp.status_code} — "
                        f"{'средства на счёте закончились' if resp.status_code == 402 else 'сервис перегружен (529)'}."
                    ))
                break
        except Exception as e:
            log.warning("omnirouter error [attempt %d]: %s: %s", _attempt + 1, type(e).__name__, e)
            if _attempt < 1:
                await asyncio.sleep(3)
    return f"{AXI_NAME}: не удалось получить ответ от OmniRouter."


async def _anthropic_classify_intent(prompt: str, file_names: str) -> str:
    """Classify routing intent via Omnirouter (NVIDIA NIM) tool_use — returns guaranteed enum value."""
    omnirouter_url = os.environ.get("AIMS_OMNIROUTER_URL", "http://127.0.0.1:8082").rstrip("/")
    auth_token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")
    model = os.environ.get("AIMS_INTENT_MODEL", "llama405b")

    clf_tools = [{
        "name": "set_intent",
        "description": "Set the classified routing intent for this file-processing request",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["docx", "edit", "chat", "ask", "training_pair"],
                    "description": (
                        "docx=generate analysis/report as Word document; "
                        "edit=modify/update data inside the spreadsheet; "
                        "chat=text answer only, no file output; "
                        "ask=ambiguous, need clarification from user; "
                        "training_pair=prepare doctuning training pair from uploaded documents"
                    ),
                }
            },
            "required": ["intent"],
        },
    }]
    payload = {
        "model": model,
        "max_tokens": 64,
        "tools": clf_tools,
        "tool_choice": {"type": "tool", "name": "set_intent"},
        "messages": [{
            "role": "user",
            "content": (
                f"Attached files: {file_names}\n"
                f"User request: {prompt}\n\n"
                "Classify the routing intent."
            ),
        }],
    }
    _OMNIROUTER_HDRS = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }
    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(20.0, connect=10.0)) as client:
            resp = await client.post(f"{omnirouter_url}/v1/messages", json=payload, headers=_OMNIROUTER_HDRS)
        if resp.status_code == 200:
            for block in resp.json().get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "set_intent":
                    label = block.get("input", {}).get("intent", "ask")
                    return label if label in ("docx", "edit", "chat", "ask", "training_pair") else "ask"
        else:
            log.warning("omnirouter classify status=%s", resp.status_code)
    except Exception as e:
        log.warning("omnirouter classify error: %s", e)
    return "ask"


# ── Local Ollama ───────────────────────────────────────────────────────────────

def _local_ollama_reply_sync(
    text: str,
    *,
    extra_context: str = "",
    system_override: str | None = None,
) -> str:
    """Primary local registry-resolved path for Axi responses."""
    import sys as _sys
    from pathlib import Path as _Path

    _ops = str(_Path(__file__).resolve().parent)
    if _ops not in _sys.path:
        _sys.path.insert(0, _ops)

    from ollama_resolve import effective_ollama_base_url, heavy_ollama_model_name
    from omi_ollama import ollama_chat
    from core.metrics import record_llm_call

    sys_prompt = _axi_system_prompt(system_override)
    user_text = f"{extra_context}\n\n{text}".strip() if extra_context else text
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_text},
    ]
    base = effective_ollama_base_url().rstrip("/")
    if not base:
        raise RuntimeError("Ollama base URL is empty (OLLAMA_BASE_URL / DGX_OLLAMA_URL / …)")
    model = heavy_ollama_model_name()
    with record_llm_call(provider="local", model=model):
        result = ollama_chat(messages, model=model, base_url=base, timeout=300.0)
    _ft_log_example(messages, result, source=f"local:{model}")
    return result


# ── Cloud LLM ─────────────────────────────────────────────────────────────────

async def _cloud_llm_reply(
    text: str,
    *,
    extra_context: str = "",
    use_search: bool = False,
    system_override: str | None = None,
    _notify_owners_fn=None,
) -> str:
    """Call NVIDIA NIM (llama-3.1-405b) or fallback to Anthropic."""
    import sys as _sys
    from pathlib import Path as _Path
    _ops = str(_Path(__file__).resolve().parent)
    if _ops not in _sys.path:
        _sys.path.insert(0, _ops)

    from core.metrics import record_llm_call

    with record_llm_call(provider="nim", model="meta/llama-3.1-405b-instruct"):
        result = await _gemini_reply(
            text,
            extra_context=extra_context,
            use_search=use_search,
            system_override=system_override,
        )
    if "не удалось получить ответ от NIM" in result:
        log.info("NIM unavailable — trying Anthropic fallback")
        with record_llm_call(provider="anthropic", model=ANTHROPIC_MODEL):
            result = await _anthropic_reply(
                text,
                extra_context=extra_context,
                system_override=system_override,
                _notify_owners_fn=_notify_owners_fn,
            )
    return result


async def _llm_reply(
    text: str,
    *,
    extra_context: str = "",
    use_search: bool = False,
    system_override: str | None = None,
    _notify_owners_fn=None,
) -> str:
    """Route to local Ollama or cloud, serialised by semaphore to prevent GPU saturation."""
    async with _get_llm_semaphore():
        return await _llm_reply_inner(
            text,
            extra_context=extra_context,
            use_search=use_search,
            system_override=system_override,
            _notify_owners_fn=_notify_owners_fn,
        )


async def _llm_reply_inner(
    text: str,
    *,
    extra_context: str = "",
    use_search: bool = False,
    system_override: str | None = None,
    _notify_owners_fn=None,
) -> str:
    """При AXI_LLM_LOCAL_FIRST=1: сначала Ollama, затем NIM. Fallback: Anthropic Claude."""
    if use_search or not _axi_llm_local_first_enabled():
        return await _cloud_llm_reply(
            text,
            extra_context=extra_context,
            use_search=use_search,
            system_override=system_override,
            _notify_owners_fn=_notify_owners_fn,
        )
    try:
        out = await asyncio.to_thread(
            _local_ollama_reply_sync,
            text,
            extra_context=extra_context,
            system_override=system_override,
        )
        if (out or "").strip():
            return out.strip()
    except Exception as e:
        log.warning("Axi: local Ollama failed, using NIM: %s", e)
        try:
            from failure_detector import get_detector
            get_detector().from_axi({"ok": False, "error": str(e), "source": "local_ollama"})
        except Exception:
            pass
    return await _cloud_llm_reply(
        text,
        extra_context=extra_context,
        use_search=False,
        system_override=system_override,
        _notify_owners_fn=_notify_owners_fn,
    )


# ── Web search helper ──────────────────────────────────────────────────────────

def _should_web_search(text: str) -> bool:
    if not AXI_WEB_SEARCH_ENABLED:
        return False
    low = text.lower()
    return any(kw in low for kw in (
        "search", "find", "look up", "google", "latest", "current", "today",
        "news", "price", "цена", "найди", "поищи", "поиск", "погода", "курс",
        "сейчас", "сегодня", "последн", "актуальн",
    ))
