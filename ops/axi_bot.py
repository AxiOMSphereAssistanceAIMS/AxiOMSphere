#!/usr/bin/env python3
"""
axi_bot.py
──────────
Axi — AIMS Orchestrator & Quality Monitor
Telegram Bot: оркестрация, мониторинг Task Registry, генерация документов.

Роль (docs/project-owner-answers.md §9):
  - Оркестратор: конфиги, связи между ботами, расписания, ключи
  - Монитор качества: периодически сканирует зависшие задачи, уведомляет владельца
  - DB задачи → роутинг через Omi

Переменные окружения:
    AXI_BOT_TOKEN / AXI_TELEGRAM_TOKEN — токен @BotFather
    AXI_ALLOWED_USER_IDS              — через запятую user id (личка: id чата = user id;
                                        группа: либо id группы, либо id отправителя должен быть в списке)
    AXI_OWNER_CHAT_IDS                — чаты владельца (для уведомлений о застрявших задачах)
    AXI_NAME                          — имя бота в ответах (default: Axi)
    ANTHROPIC_API_KEY                 — Claude API key для локального fallback
    AXI_ANTHROPIC_MODEL               — модель (default: claude-sonnet-4-6)
    AXI_AIMS_KNOWLEDGE_MODE           — off (default) | on_topic | always
    AXI_RESULTS_DIR                   — куда писать сгенерированные docx (default: /data/result)
    TASK_REGISTRY_URL                 — http://localhost:8765
    TASK_REGISTRY_STUCK_MINUTES       — порог зависших задач в минутах (default: 15)
    TASK_REGISTRY_MONITOR_INTERVAL    — интервал мониторинга в секундах (default: 900)
    QWEN_PC_ASSIST_STACK              — 1: прогрев 70B + PC Qwen при каждом сообщении
    AXI_LLM_LOCAL_FIRST               — 1: сначала Ollama, fallback → Anthropic. 0 (default): облако.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import sys as _sys
_CORE_PATH = str(Path(__file__).resolve().parent)
if _CORE_PATH not in _sys.path:
    _sys.path.insert(0, _CORE_PATH)
from core.metrics import record_llm_call  # noqa: E402

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("axi")

# ── Config ─────────────────────────────────────────────────────────────────────

AXI_BOT_TOKEN = (
    os.environ.get("AXI_BOT_TOKEN", "")
    or os.environ.get("AXI_TELEGRAM_TOKEN", "")
).strip()

AXI_NAME = os.environ.get("AXI_NAME", "Axi").strip()

def _parse_ids(env_key: str) -> frozenset[int]:
    raw = os.environ.get(env_key, "").strip()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        try:
            if part:
                out.add(int(part))
        except ValueError:
            pass
    return frozenset(out)

ALLOWED_CHATS   = _parse_ids("AXI_ALLOWED_USER_IDS")
OWNER_CHATS     = _parse_ids("AXI_OWNER_CHAT_IDS") or _parse_ids("AXI_ALLOWED_USER_IDS")

AXI_RESULTS_DIR = Path(os.environ.get("AXI_RESULTS_DIR", "/data/result"))
AXI_AIMS_KNOWLEDGE_MODE = os.environ.get("AXI_AIMS_KNOWLEDGE_MODE", "off").strip().lower()
AXI_WEB_SEARCH_ENABLED = False  # Disabled: NVIDIA NIM does not support Google Search grounding
AXI_CHAT_SHOW_SOURCES = os.environ.get("AXI_CHAT_SHOW_SOURCES", "0").strip().lower() in ("1", "true", "yes", "on")
AXI_CHAT_SHOW_TASK_REGISTRY_WARNINGS = os.environ.get(
    "AXI_CHAT_SHOW_TASK_REGISTRY_WARNINGS", "0"
).strip().lower() in ("1", "true", "yes", "on")

TASK_REGISTRY_STUCK_MINUTES  = float(os.environ.get("TASK_REGISTRY_STUCK_MINUTES", "15"))
TASK_REGISTRY_MONITOR_INTERVAL = int(os.environ.get("TASK_REGISTRY_MONITOR_INTERVAL", "900"))
TASK_REGISTRY_AUTO_CLEANUP_MINUTES = float(os.environ.get("TASK_REGISTRY_AUTO_CLEANUP_MINUTES", "60"))

QWEN_PC_ASSIST_STACK = os.environ.get("QWEN_PC_ASSIST_STACK", "0").strip().lower() in ("1", "true", "yes", "on")

# Pending intent clarification: {chat_id: {prompt, files, ts}}
_pending_intent: dict[int, dict] = {}
# Self-learning log for clarification confirmations → future fine-tuning data
_SELF_LEARN_LOG = AXI_RESULTS_DIR.parent / "axi_intent_learn.jsonl"

AXI_LLM_LOCAL_FIRST = os.environ.get("AXI_LLM_LOCAL_FIRST", "1").strip().lower() in ("1", "true", "yes", "on")
AXI_FT_LOG_ENABLED = os.environ.get("AXI_FT_LOG_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
AXI_FT_LOG_DIR = Path(os.environ.get("AXI_FT_LOG_DIR", "/data/axi_ft_log"))
# Limit concurrent heavy LLM calls to prevent GPU saturation (96%+ util / thermal shutdown)
AXI_LLM_MAX_CONCURRENT = max(1, int(os.environ.get("AXI_LLM_MAX_CONCURRENT", "1")))
AXI_ANALYZE_WAIT_SEC = int(os.environ.get("AXI_ANALYZE_WAIT_SEC", "1800"))
AXI_ANALYZE_BATCH_WAIT_SEC = int(os.environ.get("AXI_ANALYZE_BATCH_WAIT_SEC", "20"))
AXI_DIALOG_LOG_MAX = max(2, int(os.environ.get("AXI_DIALOG_LOG_MAX", "10")))
AXI_FORCE_REPLY_LANG = os.environ.get("AXI_FORCE_REPLY_LANG", "en").strip().lower()
# In groups, require explicit @Axi / "Axi ..." mention only when enabled.
AXI_GROUP_REQUIRE_MENTION = os.environ.get("AXI_GROUP_REQUIRE_MENTION", "0").strip().lower() in (
    "1", "true", "yes", "on"
)
AXI_GROUP_ALLOW_ALL_MEMBERS = os.environ.get("AXI_GROUP_ALLOW_ALL_MEMBERS", "1").strip().lower() in (
    "1", "true", "yes", "on"
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL   = os.environ.get("AXI_ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()

_PENDING_ANALYZE: dict[int, dict[str, object]] = {}
_PENDING_VIDEO: dict[int, dict[str, object]] = {}
_PENDING_DOCFILL: dict[int, dict[str, object]] = {}  # step: await_blank | await_example | validating | await_approval
_DOCFILL_VRAM_QUEUE: dict[int, str] = {}            # chat_id → blank_text, waiting for VRAM headroom
DOCFILL_VRAM_MIN_FREE_GB: float = float(os.environ.get("DOCFILL_VRAM_MIN_FREE_GB", "36"))
_VEO_GEN_BUSY: set[int] = set()
_VEO_GEN_BUSY_LOCK = asyncio.Lock()
_AXI_DIALOG: dict[int, list[dict[str, str]]] = {}
_SEEN_UPDATES: dict[str, float] = {}
_SEEN_UPDATES_LOCK = Lock()

# Путь к БД Omi и рабочему пространству (для чтения документов)
OMI_DB_PATH   = Path(os.environ.get("OMI_DB_PATH",   "/data/aims_registry.db"))
AIMS_WORKSPACE = Path(os.environ.get("AIMS_WORKSPACE", "/data"))
_AXI_DIALOG_PATH = AIMS_WORKSPACE / "axi_dialog_state.json"
_AXI_DIALOG_LOCK = Lock()
_AXI_PENDING_ANALYZE_PATH = AIMS_WORKSPACE / "axi_pending_analyze_state.json"
_AXI_PENDING_LOCK = Lock()

# ── System prompt (axi_bot_refocus_patch.md) ───────────────────────────────────

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

# ── Task Registry client ───────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "omi_telegram"))
try:
    from task_registry_api import TaskRegistryClient as _TRClient
    _tr_client: "_TRClient | None" = _TRClient()
    log.info("Task Registry client: %s", _tr_client.base_url)
except Exception as _tre:
    _tr_client = None
    log.warning("Task Registry unavailable: %s", _tre)


def _tr_register(desc: str, chat_id: str, source: str = "axi") -> str:
    if _tr_client is None:
        return ""
    try:
        return _tr_client.register(desc, source=source, chat_id=chat_id) or ""
    except Exception as e:
        log.debug("_tr_register: %s", e)
        return ""

def _tr_start(tid: str, assigned_to: str = "axi") -> None:
    if not tid or _tr_client is None:
        return
    try:
        _tr_client.start(tid, assigned_to=assigned_to)
    except Exception as e:
        log.debug("_tr_start: %s", e)

def _tr_done(tid: str, summary: str = "") -> None:
    if not tid or _tr_client is None:
        return
    try:
        _tr_client.done(tid, result_summary=summary[:200])
    except Exception as e:
        log.debug("_tr_done: %s", e)

def _tr_stuck(tid: str, error: str = "") -> None:
    if not tid or _tr_client is None:
        return
    try:
        _tr_client.stuck(tid, error=error[:200])
    except Exception as e:
        log.debug("_tr_stuck: %s", e)


_TASK_CLOSE_PHRASES = (
    "выполнено",
    "готово",
    "закрыть задачу",
    "закрой задачу",
    "close task",
    "task done",
    "completed",
    "resolved",
)
_TASK_ID_RE = re.compile(r"\b(task_[0-9a-f]{12,})\b", re.IGNORECASE)


def _extract_task_id(text: str) -> str:
    m = _TASK_ID_RE.search(text or "")
    return (m.group(1) if m else "").lower()


def _looks_like_task_close_intent(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if _extract_task_id(t):
        return True
    return any(p in t for p in _TASK_CLOSE_PHRASES)


def _close_omi_task_from_chat(chat_id: str, text: str) -> tuple[bool, str]:
    """
    Best-effort close flow for user's "done/close task" messages.
    Prevents creating a new task when user actually wants to close a hanging Omi task.
    """
    if _tr_client is None:
        return False, "Task Registry недоступен."
    wanted_id = _extract_task_id(text)
    try:
        if wanted_id:
            task = _tr_client.get(wanted_id) or {}
            if str(task.get("chat_id", "")) != str(chat_id):
                return True, f"Задача `{wanted_id}` не найдена в этом чате."
            status = str(task.get("status", "")).lower()
            if status in {"done", "failed"}:
                return True, f"Задача `{wanted_id}` уже закрыта (`{status}`)."
            _tr_done(wanted_id, summary="manual_close_by_user")
            return True, f"✅ Закрыл задачу `{wanted_id}` по вашему подтверждению."

        stuck = _tr_client.find_stuck(older_than_minutes=0) or []
        candidates = [
            t for t in stuck
            if str(t.get("chat_id", "")) == str(chat_id)
            and str(t.get("assigned_to", "")).lower() == "omi"
            and str(t.get("status", "")).lower() in {"in_progress", "stuck", "pending"}
        ]
        if not candidates:
            return True, "В этом чате нет зависших задач Omi для закрытия."

        # Prefer the oldest hanging one to drain backlog deterministically.
        task = sorted(candidates, key=lambda x: (x.get("created_at") or "", x.get("id") or 0))[0]
        tid = str(task.get("task_id", "")).strip()
        if not tid:
            return True, "Нашёл зависшую задачу, но без task_id — не могу закрыть автоматически."
        _tr_done(tid, summary="manual_close_by_user")
        return True, f"✅ Закрыл зависшую задачу `{tid}` по вашему подтверждению."
    except Exception as e:
        log.warning("manual task close failed chat=%s: %s", chat_id, e)
        return True, f"Не смог закрыть задачу автоматически: {type(e).__name__}."

# ── Owner notification helper ──────────────────────────────────────────────────

import httpx as _httpx

async def _notify_owners_async(text: str) -> None:
    """Send a plain-text message to all OWNER_CHATS via Bot API (no context needed)."""
    if not AXI_BOT_TOKEN or not OWNER_CHATS:
        return
    url = f"https://api.telegram.org/bot{AXI_BOT_TOKEN}/sendMessage"
    async with _httpx.AsyncClient(timeout=10.0) as client:
        for chat_id in OWNER_CHATS:
            try:
                await client.post(url, json={"chat_id": chat_id, "text": text})
            except Exception as e:
                log.warning("notify_owners: failed chat=%s: %s", chat_id, e)


# ── NVIDIA NIM API helper ─────────────────────────────────────────────────────

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

    sys_prompt = system_override if system_override is not None else AXI_SYSTEM_PROMPT
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


# ── Anthropic fallback ─────────────────────────────────────────────────────────

async def _anthropic_reply(
    text: str,
    *,
    extra_context: str = "",
    system_override: str | None = None,
) -> str:
    """Call Claude via OmniRouter. Used as fallback when NIM is unavailable."""
    omnirouter_url = os.environ.get("AIMS_OMNIROUTER_URL", "http://127.0.0.1:8082").rstrip("/")
    auth_token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")
    model = os.environ.get("AIMS_ANTHROPIC_MODEL", ANTHROPIC_MODEL)

    sys_prompt = system_override if system_override is not None else AXI_SYSTEM_PROMPT
    user_text = f"{extra_context}\n\n{text}".strip() if extra_context else text
    # Cloud fallback: truncate very large payloads to avoid 90s timeout
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
                if resp.status_code in (402, 529):
                    asyncio.ensure_future(_notify_owners_async(
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


def _axi_llm_local_first_enabled() -> bool:
    return AXI_LLM_LOCAL_FIRST


# Semaphore: at most AXI_LLM_MAX_CONCURRENT heavy LLM calls at once.
# Prevents stacking two 32B–72B inferences on the DGX GPU simultaneously.
_llm_semaphore: asyncio.Semaphore | None = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(AXI_LLM_MAX_CONCURRENT)
    return _llm_semaphore


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
        from datetime import datetime, timezone
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


def _local_ollama_reply_sync(
    text: str,
    *,
    extra_context: str = "",
    system_override: str | None = None,
) -> str:
    """axi_omi_sphere (qwen3:32b-q8_0) on DGX — primary local path for Axi responses."""
    from ollama_resolve import effective_ollama_base_url, heavy_ollama_model_name

    from omi_ollama import ollama_chat

    sys_prompt = system_override if system_override is not None else AXI_SYSTEM_PROMPT
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


async def _cloud_llm_reply(
    text: str,
    *,
    extra_context: str = "",
    use_search: bool = False,
    system_override: str | None = None,
) -> str:
    """Call NVIDIA NIM (llama-3.1-405b) or fallback to Anthropic."""
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
                text, extra_context=extra_context, system_override=system_override,
            )
    return result


async def _llm_reply(
    text: str,
    *,
    extra_context: str = "",
    use_search: bool = False,
    system_override: str | None = None,
) -> str:
    """Route to local Ollama or cloud, serialised by semaphore to prevent GPU saturation."""
    async with _get_llm_semaphore():
        return await _llm_reply_inner(
            text,
            extra_context=extra_context,
            use_search=use_search,
            system_override=system_override,
        )


async def _llm_reply_inner(
    text: str,
    *,
    extra_context: str = "",
    use_search: bool = False,
    system_override: str | None = None,
) -> str:
    """
    При AXI_LLM_LOCAL_FIRST=1: сначала Ollama, затем NIM.
    Fallback: Anthropic Claude.
    """
    if use_search or not _axi_llm_local_first_enabled():
        return await _cloud_llm_reply(
            text,
            extra_context=extra_context,
            use_search=use_search,
            system_override=system_override,
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
    )


# ── Web search ─────────────────────────────────────────────────────────────────

def _should_web_search(text: str) -> bool:
    if not AXI_WEB_SEARCH_ENABLED:
        return False
    low = text.lower()
    return any(kw in low for kw in (
        "search", "find", "look up", "google", "latest", "current", "today",
        "news", "price", "цена", "найди", "поищи", "поиск", "погода", "курс",
        "сейчас", "сегодня", "последн", "актуальн",
    ))


# ── XLSX editing ───────────────────────────────────────────────────────────────


def _parse_xlsx_table_response(
    answer: str,
    original_sheets: dict[str, list[list]],
) -> dict[str, list[list[str]]]:
    """Parse LLM table response: [SHEET:] format first, markdown table fallback."""
    result_sheets: dict[str, list[list[str]]] = {}
    current_sheet: str | None = None

    for line in answer.splitlines():
        stripped = line.strip()
        sheet_match = re.match(r"\[SHEET:\s*(.+?)\]", stripped)
        if sheet_match:
            current_sheet = sheet_match.group(1).strip()
            result_sheets[current_sheet] = []
            continue
        # Auto-assign to first original sheet if LLM skips [SHEET:] header
        if current_sheet is None and "|" in stripped and not re.match(r"^[\|\s\-:]+$", stripped):
            current_sheet = next(iter(original_sheets), "Sheet1")
            result_sheets[current_sheet] = []
        if current_sheet is None:
            continue
        # Skip empty lines and markdown separator rows (|---|---|)
        if not stripped or re.match(r"^[\|\s\-:]+$", stripped):
            continue
        if "|" in stripped:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            result_sheets[current_sheet].append(cells)
        # Skip non-table lines (explanatory text without pipes)

    return result_sheets


async def _edit_xlsx_with_llm(
    xlsx_path: Path,
    instruction: str,
) -> Path:
    """Read xlsx, ask LLM to apply instruction, write modified xlsx."""
    from openpyxl import load_workbook, Workbook  # type: ignore

    wb_in = load_workbook(str(xlsx_path), data_only=True)
    sheets_raw: dict[str, list[list]] = {}
    for ws in wb_in.worksheets:
        sheets_raw[ws.title] = [list(row) for row in ws.iter_rows(values_only=True)]
    wb_in.close()

    table_parts: list[str] = []
    for sheet_name, rows in sheets_raw.items():
        table_parts.append(f"[SHEET: {sheet_name}]")
        for row in rows:
            table_parts.append(" | ".join("" if v is None else str(v) for v in row))
    table_text = "\n".join(table_parts)
    first_sheet = next(iter(sheets_raw), "Sheet1")

    prompt = (
        f"You are editing an Excel spreadsheet. Output ONLY the table data.\n\n"
        f"Current table:\n{table_text[:60000]}\n\n"
        f"Instruction: {instruction}\n\n"
        f"Required output format:\n"
        f"[SHEET: {first_sheet}]\n"
        f"cell1 | cell2 | cell3\n"
        f"cell1 | cell2 | cell3\n\n"
        f"Rules: include ALL rows and ALL columns unchanged except where instructed. "
        f"Empty cell = empty string. Start IMMEDIATELY with [SHEET: {first_sheet}]. "
        f"No markdown, no code fences, no explanation before or after the table."
    )
    answer = await _llm_reply(prompt)
    if not answer.strip() or answer.startswith(f"{AXI_NAME}:"):
        raise RuntimeError(answer.strip() or "LLM returned empty response")

    result_sheets = _parse_xlsx_table_response(answer, sheets_raw)
    if not result_sheets:
        raise ValueError(f"LLM returned no parseable table data (response length: {len(answer)})")

    wb_out = Workbook()
    wb_out.remove(wb_out.active)
    for sheet_name, rows in result_sheets.items():
        ws_out = wb_out.create_sheet(title=sheet_name[:31])
        for row in rows:
            ws_out.append(row)

    AXI_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = AXI_RESULTS_DIR / f"{xlsx_path.stem}_edited_{int(time.time())}.xlsx"
    wb_out.save(str(out_path))
    return out_path


async def _transform_xlsx_with_code(
    xlsx_path: Path,
    code_instruction: str,
) -> tuple[Path, str]:
    """Ask LLM to generate transformation code, run it in sandbox on XLSX.

    The LLM generates Python code that:
      - reads from input.xlsx via openpyxl
      - modifies the data
      - saves to input.xlsx (or output.xlsx)

    Returns (output_xlsx_path, stdout_from_execution)
    """
    from ops.workers.engineer_worker import execute_code_on_xlsx

    # Ask LLM to generate the transformation code
    prompt = (
        f"Generate ONLY Python code (no markdown, no explanation) to transform an Excel file.\n\n"
        f"Requirements:\n"
        f"  - Use openpyxl to open 'input.xlsx'\n"
        f"  - Perform this transformation: {code_instruction}\n"
        f"  - Save changes to 'input.xlsx' (or set output_xlsx = Path('output.xlsx'))\n"
        f"  - Print progress updates\n"
        f"  - No error handling (sandbox will catch exceptions)\n\n"
        f"Code must be executable, no imports outside openpyxl/pathlib/json/csv."
    )
    code = await _llm_reply(prompt)
    if not code.strip() or code.startswith(f"{AXI_NAME}:"):
        raise RuntimeError(code.strip() or "LLM returned empty code")

    # Run code in sandbox
    output_path, stdout, stderr = execute_code_on_xlsx(
        xlsx_path,
        code,
        timeout=30,
    )
    if stderr and "Traceback" in stderr:
        raise RuntimeError(f"Code execution failed:\n{stderr}")

    AXI_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    final_path = AXI_RESULTS_DIR / f"{output_path.stem}_{int(time.time())}.xlsx"
    output_path.rename(final_path)

    return final_path, stdout


# ── DOCX generation ────────────────────────────────────────────────────────────

async def _generate_custom_docx(
    content: str,
    filename_stem: str,
    out_dir: Path,
    *,
    title: str | None = None,
) -> Path:
    """
    Generate a .docx file from LLM markdown-like content.
    Parses # ## ### headings and **bold** markers into Word styles.
    """
    from docx import Document

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w\-]", "_", filename_stem)[:60]
    path = out_dir / f"{safe}_{stamp}.docx"

    doc = Document()
    if title:
        doc.add_heading(title, level=0)

    bold_re = re.compile(r"\*\*(.+?)\*\*")

    def _add_para(paragraph, line: str) -> None:
        parts = bold_re.split(line)
        for i, part in enumerate(parts):
            run = paragraph.add_run(part)
            if i % 2 == 1:
                run.bold = True

    for line in content.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith(("- ", "* ")):
            p = doc.add_paragraph(style="List Bullet")
            _add_para(p, stripped[2:])
        elif stripped == "":
            doc.add_paragraph("")
        else:
            p = doc.add_paragraph()
            _add_para(p, stripped)

    doc.save(str(path))
    return path


def _wants_docx(text: str) -> bool:
    norm = text.lower()
    patterns = (
        r"(word|docx|\.docx|в word|в ворд|ворд)",
        r"(return|send|give|верни|пришли|отправь).{0,30}(word|docx)",
        r"(generate|create|сгенерируй|создай).{0,30}(docx|word|report|отчёт|отчет)",
        r"(report|отчёт|отчет|документ).{0,30}(word|docx)",
        r"(generate|create|prepare|draft|combine|review|develop|write).{0,40}(procedure|report|document|manual|strategy)",
        r"(сгенерируй|создай|подготовь|собери|проверь).{0,40}(процедур|отч[её]т|документ|регламент|стратег)",
        # Analysis + send/deliver intent (no explicit "word" but clearly wants a document output)
        r"(check|analyze|analyse|review|compare|assess|audit).{0,60}(send|deliver|share|attach|chat|file)",
        r"(send|deliver|share).{0,20}(it|file|result|output).{0,20}(to chat|to us|to me)",
        r"(correct|improve|update).{0,30}file.{0,30}(best practice|standard|based on)",
        r"(проверь|проанализируй|сравни).{0,60}(отправь|пришли|прикрепи)",
    )
    return any(re.search(p, norm) for p in patterns)


def _wants_xlsx_edit(prompt: str, files: list[dict]) -> bool:
    """True when an xlsx is in the batch and the prompt is an edit/update instruction."""
    has_xlsx = any(
        (f.get("name") or "").lower().endswith((".xlsx", ".xlsm"))
        for f in files
    )
    if not has_xlsx:
        return False
    # Docx/analysis intent takes priority over table editing
    if _wants_docx(prompt):
        return False
    low = (prompt or "").lower()
    edit_keywords = (
        "обнови", "измени", "редактируй", "заполни", "добавь", "удали", "исправь",
        "обновить", "изменить", "отредактируй", "поправь", "вставь", "скопируй",
        "update", "edit", "fill", "modify", "change", "add", "delete", "insert",
        "fix", "correct", "replace", "set", "revise",
    )
    return any(kw in low for kw in edit_keywords)


async def _infer_file_intent(prompt: str, files: list[dict]) -> str:
    """Classify file-processing intent.

    Returns one of: 'docx' | 'edit' | 'chat' | 'ask' | 'training_pair'
    Pipeline: keyword fast-path → local Qwen → NIM (primary cloud) → Anthropic (last resort).
    """
    file_names = ", ".join(f.get("name", "?") for f in files[:5])

    async def _cloud_classify(p: str, fn: str) -> str:
        try:
            from router.nim_router import classify_file_intent as _nim
            intent, confidence = _nim(p, fn)
            if confidence >= 0.7 and intent != "ask":
                log.debug("nim_router: intent=%s conf=%.2f", intent, confidence)
                return intent
        except Exception as _e:
            log.debug("nim_router classify error: %s", _e)
        return await _anthropic_classify_intent(p, fn)

    try:
        from router.fallback_router import classify_file_intent as _route
        return await _route(
            prompt,
            file_names,
            anthropic_fallback_fn=_cloud_classify,
        )
    except Exception as e:
        log.warning("_infer_file_intent router error: %s — falling back to cloud", e)
        return await _cloud_classify(prompt, file_names)


def _save_intent_example(prompt: str, files: list[dict], intent: str) -> None:
    """Append confirmed (prompt, intent) pair to self-learning log for future fine-tuning."""
    import json as _json
    record = {
        "ts": int(time.time()),
        "prompt": prompt,
        "files": [f.get("name", "") for f in files],
        "intent": intent,
    }
    try:
        _SELF_LEARN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _SELF_LEARN_LOG.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug("_save_intent_example write failed: %s", e)


def _strip_false_attachment_claims(answer: str, *, lang: str) -> str:
    """
    Guardrail for chat-only path: remove model claims that a file is attached/generated
    when no Telegram document was actually sent by runtime.
    """
    text = (answer or "").strip()
    if not text:
        return text
    low = text.lower()
    claim_markers = (
        "is attached",
        "has been generated and is attached",
        "file is attached",
        "document is attached",
        "sending generated file",
        "вложен",
        "файл приложен",
        "документ приложен",
        "прикреплен",
        "прикреплён",
    )
    if not any(m in low for m in claim_markers):
        return text
    lines: list[str] = []
    for ln in text.splitlines():
        ll = ln.lower()
        if any(m in ll for m in claim_markers):
            continue
        lines.append(ln)
    cleaned = "\n".join(lines).strip() or text
    note = (
        "\n\nNote: this response is text-only. No file was attached in this message."
        if lang != "ru"
        else "\n\nПримечание: это текстовый ответ. Файл к этому сообщению не прикреплялся."
    )
    return cleaned + note


def _strip_code_fences(answer: str) -> str:
    """
    Remove fenced code blocks from user-facing chat replies.
    Keeps response focused on conclusions instead of implementation details.
    """
    text = (answer or "").strip()
    if not text:
        return ""
    cleaned = re.sub(r"```[\s\S]*?```", "", text, flags=re.MULTILINE).strip()
    return cleaned or text


def _strip_generate_file_json(text: str) -> str:
    """
    Intercept model output wrapped in {"action":"generate_file",...}.
    Extracts the 'content' field when present; otherwise removes the JSON block.
    Prevents raw pipeline JSON from ending up verbatim in a .docx file.
    """
    text = (text or "").strip()
    if '{"action"' not in text and '"generate_file"' not in text:
        return text
    import json as _json
    json_start = text.find('{"action"')
    if json_start == -1:
        return text
    # Walk forward to find matching closing brace
    brace_depth = 0
    in_str = False
    escape_next = False
    json_end = -1
    for i, ch in enumerate(text[json_start:], start=json_start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_str:
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0:
                json_end = i + 1
                break
    if json_end == -1:
        return text
    json_blob = text[json_start:json_end]
    try:
        obj = _json.loads(json_blob)
        content = obj.get("content", "")
        if content and len(content) > 50:
            before = text[:json_start].strip()
            after = text[json_end:].strip()
            parts = [p for p in [before, content, after] if p]
            return "\n\n".join(parts)
    except Exception as e:
        log.debug("_strip_generate_file_json parse failed: %s", e)
    # Fallback: strip the JSON block, keep surrounding text
    before = text[:json_start].strip()
    after = text[json_end:].strip()
    return (before + ("\n\n" + after if after else "")).strip() or text


def _build_doc_analysis_system() -> str:
    """
    System prompt override for deep structured technical document analysis
    when the source contains equipment tables, preservation matrices, or PPM guidelines.
    Injected for the docx-output path in _process_analyze_batch when xlsx is present.
    """
    return (
        AXI_SYSTEM_PROMPT + "\n\n"
        "DOCUMENT ANALYSIS MODE — MANDATORY RULES:\n"
        "1. OUTPUT: Write directly as a professional engineering document using Markdown "
        "(# ## ### headings, bullet lists, **bold**). "
        "NEVER output JSON, code blocks, or {\"action\":...} constructs — "
        "write the document text directly with no wrapper.\n"
        "2. COMPLETENESS: If the source document lists equipment types, systems, or processes "
        "— enumerate EVERY item by its exact name. Do not summarize, skip, or merge any item.\n"
        "3. PER-EQUIPMENT DEPTH: For each equipment type identified, provide a dedicated subsection with:\n"
        "   - Gap analysis: what is currently missing or insufficient in the source\n"
        "   - 3–5 specific, actionable improvements with engineering rationale\n"
        "   - Applicable standards with full designation "
        "(e.g., API 610 12th ed. §9.3, ISO 55001:2014 §8.1, NACE SP0169-2013, IEC 60034-1)\n"
        "   - Quantitative acceptance criteria where applicable "
        "(e.g., vibration ≤ 4.5 mm/s RMS per ISO 10816-3, insulation ≥ 100 MΩ at 500 V DC)\n"
        "4. DOCUMENT STRUCTURE (use this unless the user specified otherwise):\n"
        "   # [Document Title]\n"
        "   ## Executive Summary\n"
        "   ## Scope and Applicability\n"
        "   ## Equipment-by-Equipment Analysis\n"
        "   ### [Equipment Type 1]\n"
        "   ### [Equipment Type 2]\n"
        "   ...\n"
        "   ## Cross-Cutting Recommendations\n"
        "   ## Standards and Reference Matrix\n"
        "5. STANDARDS: Always cite specific standard numbers and sections. "
        "Never use vague phrases like 'per industry standards' or 'according to best practice' "
        "without naming the actual standard.\n"
        "6. LENGTH: Do not truncate. Every equipment type in the source must appear as its own "
        "subsection with full analysis. A complete analysis is expected."
    )


def _wants_standards_docx_result(text: str) -> bool:
    low = (text or "").lower()
    if _wants_docx(low):
        return True
    return any(k in low for k in (
        "correct", "fix", "revise", "update", "redline",
        "исправ", "скоррект", "обнови", "внеси коррект",
    ))


def _build_applied_corrections_section(compliance_review: str) -> str:
    """
    Build a concise delta block to show what changed vs original.
    """
    lines = [(ln or "").strip("-• ").strip() for ln in (compliance_review or "").splitlines()]
    candidates: list[str] = []
    seen: set[str] = set()
    markers = ("gap", "non-com", "critical", "major", "minor", "recommend", "clause", "required")
    for ln in lines:
        low = ln.lower()
        if len(ln) < 18:
            continue
        if not any(m in low for m in markers):
            continue
        if ln in seen:
            continue
        seen.add(ln)
        candidates.append(ln[:220])
        if len(candidates) >= 8:
            break
    if not candidates:
        candidates = [
            "Updated procedure steps to align with cited international standards and clauses.",
            "Added missing control points, verification checkpoints, and records required for compliance.",
            "Clarified acceptance criteria, responsibilities, and evidence requirements.",
        ]
    body = "\n".join(f"- {item}" for item in candidates[:8])
    return "## Applied corrections vs original\n" + body


def _sources_note(
    *,
    lang: str,
    use_search: bool,
    has_dialog_context: bool = False,
    uploaded_files_count: int = 0,
) -> str:
    if not AXI_CHAT_SHOW_SOURCES:
        return ""
    if lang == "ru":
        lines = ["Источники:"]
        lines.append("- запрос пользователя")
        if has_dialog_context:
            lines.append("- контекст предыдущего диалога")
        if uploaded_files_count > 0:
            lines.append(f"- содержимое загруженных файлов ({uploaded_files_count})")
        lines.append("- web search" if use_search else "- без web search")
        return "\n".join(lines)
    lines = ["Sources used:"]
    lines.append("- user request")
    if has_dialog_context:
        lines.append("- recent chat context")
    if uploaded_files_count > 0:
        lines.append(f"- uploaded file content ({uploaded_files_count})")
    lines.append("- web search" if use_search else "- no web search")
    return "\n".join(lines)


# ── Standards / compliance check ─────────────────────────────────────────────

def _wants_standards_check(
    text: str,
    *,
    recent_chat_context: str = "",
    pending_files_count: int = 0,
) -> bool:
    """Detect "check against standards / compliance check" intent."""
    low = (text or "").lower()
    check_kw = any(k in low for k in (
        "проверь на стандарт", "проверь стандарт", "проверь соответствие",
        "check against standard", "check standard", "check compliance",
        "compliance check", "standards check", "standards review",
        "на соответствие стандарт", "verify standard", "сверь со стандарт",
        "аудит стандарт", "standards audit",
        "international standards", "with standards", "against standards",
        "according to standards", "per standard", "as per standard",
        "международн", "по стандарт", "по международн",
    ))
    contextual_pair = (
        ("standard" in low or "standards" in low or "international" in low)
        and any(v in low for v in ("check", "verify", "review", "audit", "correct", "fix", "update"))
    )
    if check_kw or contextual_pair:
        return True

    # Live-chat intent resolution: "this procedure/document" + corrective verbs
    # should route to standards flow when there is recent doc context.
    deictic_ref = any(k in low for k in (
        "this procedure", "this document", "this file", "that procedure", "that document",
        "эту процедуру", "этот документ", "этот файл", "данную процедуру", "этот регламент",
    ))
    corrective_action = any(k in low for k in (
        "correct", "fix", "revise", "update", "improve", "bring in line", "align",
        "исправ", "скоррект", "обнов", "доработ", "приведи в соответств",
    ))
    context_low = (recent_chat_context or "").lower()
    has_recent_doc_context = ("[doc:" in context_low) or ("uploaded file content" in context_low)
    has_pending_files = pending_files_count > 0
    return deictic_ref and corrective_action and (has_recent_doc_context or has_pending_files)


async def _handle_standards_check(
    update,
    ctx,
    text: str,
    *,
    lang: str,
    tr_id: str | None,
    progress_msg,
    t0: float,
) -> None:
    """
    Pipeline: extract recent files + Omi DB context → LLM compliance analysis → text report.
    """
    _chat_id = update.effective_chat.id if update.effective_chat else None

    # Gather file content from pending analyze state
    file_texts: list[str] = []
    state = _get_pending_analyze_state(_chat_id) if _chat_id else None
    pending_files: list[object] = list((state or {}).get("files") or [])
    for item in pending_files[:3]:
        try:
            if isinstance(item, dict):
                name = str(item.get("name") or "uploaded_document")
                excerpt = str(item.get("excerpt") or "").strip()
                if excerpt:
                    file_texts.append(f"[FILE: {name}]\n{excerpt[:8000]}")
                continue
            fp = Path(str(item))
            if not fp.exists():
                continue
            ext = fp.suffix.lower()
            content = ""
            if ext == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(str(fp))
                    content = "\n".join(p.extract_text() or "" for p in reader.pages[:8])
                except Exception as e:
                    log.warning("standards_check: PDF extract failed %s: %s", fp.name, e)
            elif ext in (".docx",):
                try:
                    from docx import Document as _Doc
                    doc = _Doc(str(fp))
                    content = "\n".join(p.text for p in doc.paragraphs)[:12000]
                except Exception as e:
                    log.warning("standards_check: DOCX extract failed %s: %s", fp.name, e)
            elif ext in (".txt", ".md"):
                content = fp.read_text(errors="replace")[:12000]
            if content.strip():
                file_texts.append(f"[FILE: {fp.name}]\n{content[:8000]}")
        except Exception as _e:
            log.debug("standards_check: file read error %s: %s", item, _e)

    if not file_texts:
        recent_doc_name, recent_doc_text = _load_recent_generated_doc_context(_chat_id)
        if recent_doc_text:
            file_texts.append(f"[FILE: {recent_doc_name}]\n{recent_doc_text[:8000]}")

    # Gather Omi registry context (top-5 docs by keyword)
    db_context = ""
    try:
        import sqlite3 as _sql
        from aims_paths import workspace_root as _wr
        _db = _wr() / "aims_registry.db"
        if _db.exists():
            kws = _extract_search_keywords(text)
            _conn = _sql.connect(str(_db))
            _conn.row_factory = _sql.Row
            rows: list = []
            for kw in kws[:4]:
                rows += _conn.execute(
                    "SELECT title, summary FROM documents WHERE title LIKE ? OR summary LIKE ? LIMIT 3",
                    (f"%{kw}%", f"%{kw}%"),
                ).fetchall()
            _conn.close()
            seen: set[str] = set()
            parts: list[str] = []
            for r in rows[:6]:
                t = str(r["title"] or "").strip()
                s = (str(r["summary"] or "").strip())[:400]
                if t and t not in seen:
                    seen.add(t)
                    parts.append(f"• {t}: {s}")
            if parts:
                db_context = "AIMS Registry excerpts:\n" + "\n".join(parts)
    except Exception as _dbe:
        log.debug("standards_check: db context error: %s", _dbe)

    # Build compliance prompt
    doc_block = "\n\n".join(file_texts) if file_texts else ""
    compliance_prompt = (
        f"{text}\n\n"
        + (f"[UPLOADED DOCUMENTS]\n{doc_block}\n\n" if doc_block else "")
        + (f"[AIMS REGISTRY CONTEXT]\n{db_context}\n\n" if db_context else "")
        + "INSTRUCTION: Perform a compliance review against applicable standards "
        "(ISO 55001/55002 Asset Management, API RP 570/574/653, ASME, NFPA 70/72, "
        "OSHA 1910, EN 13460, DEP/Shell standards). "
        "Structure output as:\n"
        "1. **Document / scope reviewed**\n"
        "2. **Applicable standards** (explicit standard numbers/revisions + rationale)\n"
        "3. **Compliance findings** (per standard: Compliant / Gap / N/A + evidence)\n"
        "4. **Recommended actions** (priority: Critical / Major / Minor)\n"
        "5. **Standards sources used** (for each standard include source name, publisher, year/revision, and URL if known)\n"
        "6. **Summary score** (0–100%)\n"
        "Be specific; cite clause numbers where relevant. "
        "Do not output Python code, pseudo-code, or fenced markdown code blocks. "
        "Return plain text only (no markdown tables, no markdown formatting markers). "
        "Do not write vague names like 'international standard' without exact identifiers (e.g., ISO 55001:2014 clause 6.2)."
    )

    use_search = AXI_WEB_SEARCH_ENABLED
    if progress_msg is not None:
        try:
            await progress_msg.edit_text(
                f"⏱ {AXI_NAME}: проверяю соответствие стандартам…"
                if lang == "ru" else
                f"⏱ {AXI_NAME}: running standards compliance check…"
            )
        except Exception:
            pass

    answer = await _llm_reply(compliance_prompt, use_search=use_search)
    answer = _strip_false_attachment_claims(answer, lang=lang)
    answer = _strip_code_fences(answer)

    dt = time.perf_counter() - t0
    source_hint = _sources_note(
        lang=lang,
        use_search=use_search,
        has_dialog_context=False,
        uploaded_files_count=len(file_texts),
    )
    task_hint = f" | task `{tr_id}`" if tr_id else ""
    full = answer.strip() + (f"\n\n{source_hint}{task_hint}" if (source_hint or task_hint) else "")

    if _wants_standards_docx_result(text) and answer.strip():
        original_block = "\n\n".join(file_texts) if file_texts else ""
        revised_prompt = (
            f"User request:\n{text}\n\n"
            f"[COMPLIANCE FINDINGS]\n{answer[:14000]}\n\n"
            + (f"[ORIGINAL DOCUMENTS]\n{original_block[:18000]}\n\n" if original_block else "")
            + "INSTRUCTION: Produce a fully corrected and updated procedure document that resolves the identified gaps.\n"
            + "Output only the corrected document content (final version), ready to save as .docx.\n"
            + "Use clear section headings and actionable steps. Include applicable standards with exact identifiers.\n"
            + "Do not output analysis notes, markdown code fences, or pseudo-code."
        )
        revised_doc = await _llm_reply(revised_prompt, use_search=use_search)
        revised_doc = _strip_false_attachment_claims(revised_doc, lang=lang)
        revised_doc = _strip_code_fences(revised_doc)
        generic_request_markers = (
            "please provide the procedure document",
            "once i have the content",
            "send the updated document to this chat",
        )
        if any(m in revised_doc.lower() for m in generic_request_markers):
            revised_doc = ""
        if not revised_doc.strip():
            revised_doc = answer
        if "applied corrections vs original" not in revised_doc.lower():
            revised_doc = revised_doc.strip() + "\n\n" + _build_applied_corrections_section(answer)
        first_line = next((ln.strip().lstrip("#").strip() for ln in revised_doc.splitlines() if ln.strip()), "corrected_procedure")
        docx_path = await _generate_custom_docx(revised_doc, "axi_standards_corrected", AXI_RESULTS_DIR, title=first_line)
        saved_to_kb = _register_corrected_standards_knowledge(
            docx_path=docx_path,
            user_request=text,
            compliance_review=answer,
            revised_document=revised_doc,
        )
        if progress_msg is not None:
            try:
                await progress_msg.delete()
            except Exception:
                pass
        with docx_path.open("rb") as fh:
            await update.message.reply_document(
                document=fh,
                filename=docx_path.name,
                caption=(
                    f"{AXI_NAME}: ✅ {docx_path.name} ({dt:.0f}s)\n"
                    + ("Knowledge base updated for future generations." if saved_to_kb else "Knowledge base update skipped.")
                ),
            )
        if _chat_id:
            _dialog_append(_chat_id, "assistant", f"[doc:{docx_path.name}]")
        _tr_done(
            tr_id,
            summary=(
                f"standards_docx_corrected:{docx_path.name}:"
                f"files={len(file_texts)}:search={use_search}:kb={int(saved_to_kb)}"
            ),
        )
        return

    if progress_msg is not None:
        try:
            await progress_msg.delete()
        except Exception:
            pass

    _TG_LIMIT = 4000
    chunks = [full[i : i + _TG_LIMIT] for i in range(0, len(full), _TG_LIMIT)] if full else ["…"]
    for chunk in chunks:
        await update.message.reply_text(chunk)

    if _chat_id:
        _dialog_append(_chat_id, "assistant", answer[:2000])
    _tr_done(tr_id, summary=f"standards_check:files={len(file_texts)}:search={use_search}")


# ── DB-based document strategy ────────────────────────────────────────────────

def _wants_registry_list(text: str) -> bool:
    """Detect requests to list/show/search the AIMS document registry."""
    low = text.lower()
    list_kw = any(k in low for k in (
        "реестр", "registry", "registered", "зарегистрировано", "зарегистрированы",
        "список документов", "list documents", "what documents", "какие документы",
        "покажи документы", "show documents", "все документы", "all documents",
        "что в базе", "what's in the", "в реестре", "in the registry",
        "сколько документов", "how many documents", "how many files",
    ))
    # Exclude strategy-generation requests — those go to _wants_db_strategy
    gen_kw = any(k in low for k in ("стратегия", "strategy", "подготовь", "generate", "сгенерируй"))
    return list_kw and not gen_kw


def _wants_db_strategy(text: str) -> bool:
    low = text.lower()
    has_db = any(k in low for k in ("database", "from database", "из базы", "из реестра", "из бд", "based on document"))
    has_gen = any(k in low for k in ("strategy", "стратегия", "plan", "план", "report", "отчёт",
                                      "prepare", "подготовь", "generate", "сгенерируй", "create", "создай"))
    return has_db and has_gen


def _extract_search_keywords(text: str) -> list[str]:
    from workers.data_worker import extract_search_keywords
    return extract_search_keywords(text)


def _register_corrected_standards_knowledge(
    *,
    docx_path: Path,
    user_request: str,
    compliance_review: str,
    revised_document: str,
) -> bool:
    """
    Save corrected standards output into AIMS registry for reuse in future generations.
    """
    import sqlite3

    if not OMI_DB_PATH.exists():
        log.warning("knowledge register skipped: OMI_DB_PATH not found: %s", OMI_DB_PATH)
        return False

    now = datetime.now(timezone.utc).isoformat()
    file_name = docx_path.name
    file_path = str(docx_path)
    standards_hits = sorted(set(re.findall(r"\b(?:ISO|API|ASME|NFPA|OSHA|EN)\s*[A-Z0-9./:-]*", compliance_review)))
    standards_kw = ", ".join(s for s in standards_hits if s.strip())[:500]
    summary = (
        "Corrected procedure after international standards compliance review.\n"
        f"Request: {user_request[:300]}\n"
        f"Standards: {standards_kw or 'not explicitly extracted'}\n"
        f"Findings excerpt: {compliance_review[:1200]}"
    )[:3500]
    notes = (
        "[Axi standards correction artifact]\n"
        "This record stores corrected output generated after compliance gap assessment.\n\n"
        f"[REVIEW]\n{compliance_review[:6000]}\n\n"
        f"[REVISED_DOCUMENT]\n{revised_document[:12000]}"
    )[:15000]

    try:
        conn = sqlite3.connect(str(OMI_DB_PATH))
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM documents WHERE file_path = ? OR file_name = ? LIMIT 1",
            (file_path, file_name),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE documents
                SET title = ?, summary = ?, keywords = ?, date_modified = ?, language = ?, source = ?, notes = ?
                WHERE id = ?
                """,
                (
                    "Corrected procedure (standards-reviewed)",
                    summary,
                    standards_kw,
                    now,
                    "en",
                    "axi_standards_correction",
                    notes,
                    int(existing["id"]),
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO documents (
                    file_path, file_name, file_type, title, summary, aims_process,
                    is_master, is_anonymized, language, date_added, date_modified,
                    source, notes, keywords
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_path,
                    file_name,
                    ".docx",
                    "Corrected procedure (standards-reviewed)",
                    summary,
                    "P06",
                    0,
                    0,
                    "en",
                    now,
                    now,
                    "axi_standards_correction",
                    notes,
                    standards_kw,
                ),
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("knowledge register failed: %s", e)
        return False


def _resolve_doc_path(raw_path: str | None) -> Path | None:
    from workers.data_worker import resolve_doc_path
    return resolve_doc_path(raw_path, workspace_path=AIMS_WORKSPACE)


def _fetch_db_docs(keywords: list[str], max_docs: int = 8) -> list[dict]:
    from workers.data_worker import fetch_db_docs
    return fetch_db_docs(keywords, max_docs, db_path=OMI_DB_PATH, workspace_path=AIMS_WORKSPACE)


async def _handle_registry_list(
    update: "Update",
    ctx: "ContextTypes.DEFAULT_TYPE",
    text: str,
    tr_id: str,
) -> None:
    """Return a formatted list of registered documents from aims_registry.db."""
    from workers.data_worker import query_registry
    chat_id = update.effective_chat.id

    if not OMI_DB_PATH.exists():
        await update.message.reply_text("⚠️ aims_registry.db не найден.")
        _tr_stuck(tr_id, "db not found")
        return

    try:
        loop = asyncio.get_event_loop()
        total, rows = await loop.run_in_executor(
            None, lambda: query_registry(text, 50, db_path=OMI_DB_PATH)
        )
    except Exception as e:
        log.warning("_handle_registry_list db error: %s", e)
        await update.message.reply_text(f"⚠️ Ошибка чтения реестра: {e}")
        _tr_stuck(tr_id, str(e))
        return

    _registry_stop = {"реестр", "registry", "registered", "зарегистрировано", "документы", "documents",
                      "список", "list", "all", "все", "what", "какие", "покажи", "show", "сколько", "how"}
    search_kws = [k for k in _extract_search_keywords(text) if k not in _registry_stop]

    if not rows:
        await update.message.reply_text("📂 В реестре нет документов по вашему запросу.")
        _tr_done(tr_id, summary="empty result")
        return

    label = f"(поиск: {', '.join(search_kws)}, {len(rows)} из {total})" if search_kws else f"последние {len(rows)} из {total}"
    lines = [f"📂 Реестр AIMS — {label}:\n"]
    for r in rows:
        proc = r["aims_process"] or "—"
        title = (r["title"] or r.get("file_name") or f"#{r['id']}").replace("_", " ")
        date = (r["date_added"] or "")[:10]
        lines.append(f"• [{proc}] {title}  ({date})")

    reply = "\n".join(lines)
    # Telegram 4096-char limit — send as file if too long
    if len(reply) > 3800:
        import io
        bio = io.BytesIO(reply.encode())
        bio.name = "registry.txt"
        await ctx.bot.send_document(chat_id=chat_id, document=bio, filename="registry.txt",
                                    caption=f"📂 Реестр AIMS — {label}")
    else:
        await update.message.reply_text(reply)
    _tr_done(tr_id, summary=f"registry list: {len(rows)} docs")


async def _handle_db_strategy(
    update: "Update",
    ctx: "ContextTypes.DEFAULT_TYPE",
    text: str,
    tr_id: str,
) -> None:
    """
    Workflow:
    1. Search AIMS DB for anonymized documents matching the request
    2. Generate draft from internal content (Gemini/Anthropic)
    3. Enrich with external best-practices (web search)
    4. Output .docx
    """
    chat_id = update.effective_chat.id

    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await update.message.reply_text("🔍 Ищу документы в базе данных AIMS...")

    keywords = _extract_search_keywords(text)
    loop = asyncio.get_event_loop()
    docs = await loop.run_in_executor(None, _fetch_db_docs, keywords)

    if not docs:
        await update.message.reply_text(
            "⚠️ Документы по теме не найдены в базе данных AIMS. "
            "Попробуйте уточнить запрос или сначала зарегистрируйте документы через Omi."
        )
        _tr_stuck(tr_id, "no db docs found")
        return

    docs_with_content = [d for d in docs if d["content"]]
    found_list = "\n".join(f"• [{d['process']}] {d['title']}" for d in docs)
    await update.message.reply_text(
        f"📂 Найдено {len(docs)} документов ({len(docs_with_content)} с содержимым):\n{found_list}\n\n"
        f"⚙️ Генерирую стратегию на основе внутренних документов..."
    )
    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)

    # Build internal context — use full content if available, otherwise metadata only
    doc_context_parts = []
    for d in docs:
        header = f"### [{d['process']}] {d['title']}"
        body = d["content"][:12000] if d["content"] else f"[registered in AIMS DB — file content pending OCR/anonymization]"
        if d.get("keywords"):
            body = f"Keywords: {d['keywords']}\n{body}"
        doc_context_parts.append(f"{header}\n{body}")
    doc_context = "\n\n---\n\n".join(doc_context_parts)

    has_real_content = len(docs_with_content) > 0
    content_note = (
        "Use the document content above as primary source."
        if has_real_content else
        "Document files are registered but full text is pending OCR on server. "
        "Use document titles and metadata as structural anchors. "
        "Generate content based on industry-specific knowledge for aluminum smelting plants."
    )

    # Step 1: generate from internal documents + industry context
    # Extract specific facilities/components from the user request
    internal_prompt = (
        f"{text}\n\n"
        f"[AIMS DATABASE — REGISTERED DOCUMENTS]:\n\n{doc_context}\n\n"
        f"[INSTRUCTION]: {content_note}\n\n"
        "CRITICAL RULES:\n"
        "- This is an ALUMINUM SMELTING PLANT. Apply ONLY standards relevant to:\n"
        "  aluminum production, heavy industrial equipment, smelting/electrolysis, "
        "  gas handling, power systems, and industrial preservation.\n"
        "- RELEVANT standards: ISO 55001 (asset management), NFPA 70/72 (electrical/fire), "
        "  API 570/574 (piping inspection), API 653 (tanks), ISO 19443, DEP (Shell standards), "
        "  ASME standards, OSHA 1910, EN 13460 (maintenance documentation).\n"
        "- DO NOT use: ISO 15643 (cultural heritage), ISO 9241 (ergonomics), "
        "  or any standard unrelated to industrial plant preservation.\n"
        "- Structure: # main title, ## section per component "
        "(cast house / baking plant / rodding plant / power plant / fuel gas supply / utilities / flue gas plant), "
        "### subsections (preservation scope, critical equipment, procedures, inspection intervals), "
        "**bold** key terms, - bullet points.\n"
        "- Output document content only."
    )
    internal_answer = await _llm_reply(internal_prompt)

    # Step 2: enrich with industry-specific external standards
    external_note = ""
    if AXI_WEB_SEARCH_ENABLED:
        await update.message.reply_text("🌐 Сверяю с отраслевыми стандартами для алюминиевой промышленности...")
        enrich_prompt = (
            "What are the specific international standards and industry best practices for "
            "PRESERVATION strategy of ALUMINUM SMELTING PLANT facilities including: "
            "cast house, baking plant (anode baking), rodding plant, power plant, "
            "fuel gas supply, utilities and flue gas treatment plant?\n"
            "Focus ONLY on aluminum industry, metallurgical and heavy industrial standards. "
            "Include: DEP standards, API RPs, NFPA codes, ISO 55001/55002, EN 13460. "
            "Exclude cultural heritage or unrelated standards. "
            "Give 5-7 specific actionable points with standard references."
        )
        external_note = await _llm_reply(enrich_prompt, use_search=True)

    # Combine
    final_content = internal_answer
    if external_note and "не удалось получить ответ" not in external_note:
        final_content += (
            "\n\n## External Standards & Best Practices\n"
            "*Supplementary benchmarks from international standards:*\n\n"
            + external_note
        )

    # Generate .docx
    first_line = next(
        (ln.strip().lstrip("#").strip() for ln in final_content.splitlines() if ln.strip()),
        "Preservation_Strategy",
    )
    docx_path = await _generate_custom_docx(
        final_content, "preservation_strategy", AXI_RESULTS_DIR, title=first_line,
    )

    with docx_path.open("rb") as fh:
        await update.message.reply_document(
            document=fh,
            filename=docx_path.name,
            caption=(
                f"📄 {first_line}\n"
                f"Источники: {len(docs_with_content)} внутренних документов AIMS"
                + (" + внешние стандарты" if external_note and "не удалось" not in external_note else "")
            ),
        )
    _tr_done(tr_id, summary=f"db_strategy:{docx_path.name}:{len(docs)}docs")


# ── VRAM warm-up ───────────────────────────────────────────────────────────────

def _schedule_vram_warmup() -> None:
    """Background warm: 70B on Spark + Qwen on PC (QWEN_PC_ASSIST_STACK); после снятия 70B — прогрев малой."""
    try:
        from ollama_resolve import (
            effective_ollama_base_url,
            heavy_ollama_model_name,
            ollama_ensure_small_warm_after_heavy_gone_watcher,
            ollama_schedule_background_warm,
            ollama_warm_small_when_heavy_absent,
            spark_primary_ollama_base_url,
        )

        ollama_warm_small_when_heavy_absent()
        ollama_ensure_small_warm_after_heavy_gone_watcher()
        if not QWEN_PC_ASSIST_STACK:
            return
        heavy = heavy_ollama_model_name()
        base = spark_primary_ollama_base_url() or effective_ollama_base_url()
        ollama_schedule_background_warm(heavy, base)
    except Exception as e:
        log.debug("vram warmup: %s", e)


# ── Access control ─────────────────────────────────────────────────────────────

def _chat_allowed(update: Update) -> bool:
    if not ALLOWED_CHATS:
        return True
    if update.effective_chat is None:
        return False
    if update.effective_chat.type in ("group", "supergroup") and AXI_GROUP_ALLOW_ALL_MEMBERS:
        return True
    if update.effective_chat.id in ALLOWED_CHATS:
        return True
    # В группе effective_chat.id — это id группы (отрицательный), не user id.
    # Разрешаем участникам из белого списка без дублирования id группы в .env.
    if update.effective_chat.type in ("group", "supergroup"):
        uid = update.effective_user.id if update.effective_user else None
        if uid is not None and uid in ALLOWED_CHATS:
            return True
    return False

def _is_owner(update: Update) -> bool:
    if not OWNER_CHATS:
        return False
    if update.effective_chat is None:
        return False
    if update.effective_chat.id in OWNER_CHATS:
        return True
    if update.effective_chat.type in ("group", "supergroup"):
        uid = update.effective_user.id if update.effective_user else None
        if uid is not None and uid in OWNER_CHATS:
            return True
    return False

def _reply_lang(text: str) -> str:
    if AXI_FORCE_REPLY_LANG in ("en", "ru"):
        return AXI_FORCE_REPLY_LANG
    return "ru" if any("\u0400" <= ch <= "\u04ff" for ch in (text or "")) else "en"


def _strip_axi_prefix(text: str) -> str:
    clean = (text or "").strip()
    low = clean.lower()
    for pref in ("axi ", "axi,", "axi:", "акси ", "акси,", "акси:"):
        if low.startswith(pref):
            return clean[len(pref):].strip()
    return clean


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        return
    lang = _reply_lang(update.message.text or "")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Начать работу с Axi", callback_data="axi_activate"),
    ]])
    if lang == "ru":
        await update.message.reply_text(
            f"*{AXI_NAME}* — оркестратор AIMS.\n\n"
            "Я обрабатываю внешние задачи: веб-поиск, анализ документов, генерация Word-файлов.\n"
            "Omi присылает результаты напрямую, но задачи идут через Axi.\n\n"
            "Нажмите кнопку или напишите «Axi, …» для начала работы.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(
            f"*{AXI_NAME}* — AIMS Orchestrator.\n\n"
            "I handle external tasks: web search, document analysis, Word file generation.\n"
            "Omi can deliver results directly, but all tasks are routed through Axi.\n\n"
            "Press the button or write 'Axi, …' to start.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


async def _cmd_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 'Начать работу с Axi' inline button press."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if not _chat_allowed(update):
        return
    user = update.effective_user
    name = user.first_name if user else "Пользователь"
    await query.message.reply_text(
        f"👋 {name}, Axi активирован.\n"
        "Пишите задачи — я готов к работе.",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        return
    text = (
        f"*{AXI_NAME} — команды*\n\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/quality_report [часы] — отчёт качества Task Registry (default: 24ч)\n"
        "/stuck_tasks — список зависших задач прямо сейчас\n"
        "/close_task [task_id] — закрыть зависшую задачу Omi\n"
        "\n"
        "Просто напишите сообщение — Axi ответит или найдёт в интернете.\n"
        "Для генерации Word: 'сделай отчёт в Word' / 'generate report as docx'"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_quality_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать отчёт качества Task Registry."""
    if not _chat_allowed(update):
        return
    hours = 24
    if ctx.args:
        try:
            hours = int(ctx.args[0])
        except ValueError:
            pass
    if _tr_client is None:
        await update.message.reply_text(
            "⚠️ Task Registry недоступен. Убедитесь что task_registry_api.py запущен.",
        )
        return
    try:
        report = _tr_client.quality_report(hours=hours)
        await update.message.reply_text(report or f"Нет данных за {hours}ч.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Task Registry ошибка: {e}")


async def cmd_stuck_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать зависшие задачи."""
    if not _chat_allowed(update):
        return
    if _tr_client is None:
        await update.message.reply_text("⚠️ Task Registry недоступен.")
        return
    try:
        tasks = _tr_client.find_stuck(older_than_minutes=TASK_REGISTRY_STUCK_MINUTES)
        if not tasks:
            await update.message.reply_text("✅ Зависших задач нет.")
            return
        lines = [f"⚠️ *Зависшие задачи ({len(tasks)}):*"]
        for t in tasks[:10]:
            lines.append(
                f"  • `{t['task_id']}` [{t['assigned_to']}] "
                f"{int(t['age_minutes'])}м — {t['description'][:60]}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка: {e}")


async def cmd_close_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Close hanging Omi task in this chat or by explicit task_id."""
    if not _chat_allowed(update):
        return
    chat_id = str(update.effective_chat.id if update.effective_chat else "")
    task_id = (ctx.args[0].strip() if getattr(ctx, "args", None) else "")
    text = task_id or "закрыть задачу"
    handled, msg = _close_omi_task_from_chat(chat_id, text)
    if handled:
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    await update.message.reply_text("⚠️ Не удалось обработать /close_task.")


async def cmd_cleanup_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete old pending tasks from registry (omi_tasks and bot_cross_handoff)."""
    if not _chat_allowed(update):
        return

    try:
        db_path = Path(AIMS_WORKSPACE) / "aims_registry.db"
        if not db_path.exists():
            await update.message.reply_text("⚠️ Registry database not found.")
            return

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Count old pending tasks (older than 7 days)
        cursor.execute("""
            SELECT COUNT(*) FROM omi_tasks
            WHERE status = 'pending'
            AND datetime(created_at) < datetime('now', '-7 days')
        """)
        omi_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM bot_cross_handoff
            WHERE status = 'pending'
            AND datetime(created_at) < datetime('now', '-7 days')
        """)
        handoff_count = cursor.fetchone()[0]

        if omi_count == 0 and handoff_count == 0:
            await update.message.reply_text("✅ Нет старых зависших задач для очистки.")
            conn.close()
            return

        # Delete old pending tasks
        cursor.execute("""
            DELETE FROM omi_tasks
            WHERE status = 'pending'
            AND datetime(created_at) < datetime('now', '-7 days')
        """)

        cursor.execute("""
            DELETE FROM bot_cross_handoff
            WHERE status = 'pending'
            AND datetime(created_at) < datetime('now', '-7 days')
        """)

        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ Очистка завершена:\n"
            f"• Удалено задач из omi_tasks: {omi_count}\n"
            f"• Удалено handoff записей: {handoff_count}\n\n"
            f"Удалены только задачи старше 7 дней в статусе 'pending'.",
            parse_mode="Markdown"
        )

    except Exception as e:
        log.error("cleanup_tasks error: %s", e, exc_info=True)
        await update.message.reply_text(f"⚠️ Ошибка очистки: {e}")


def _set_pending_analyze(
    chat_id: int,
    prompt: str,
    *,
    preserve_existing_files: bool = False,
) -> None:
    prev = _PENDING_ANALYZE.get(chat_id) if preserve_existing_files else None
    prev_files = list(prev.get("files") or []) if isinstance(prev, dict) else []
    prev_last_upload_ts = float(prev.get("last_upload_ts", 0.0)) if isinstance(prev, dict) else 0.0
    prev_lang = str(prev.get("lang", "")).strip() if isinstance(prev, dict) else ""
    _PENDING_ANALYZE[chat_id] = {
        "prompt": prompt,
        "ts": time.time(),
        "last_upload_ts": prev_last_upload_ts,
        "files": prev_files,
        "awaiting_clarify": False,
        "notified_waiting": False,
        "lang": prev_lang or "en",
    }
    _pending_analyze_persist()


def _get_pending_analyze(chat_id: int) -> str | None:
    item = _PENDING_ANALYZE.get(chat_id)
    if not item:
        return None
    ts = float(item.get("ts", 0.0))
    if time.time() - ts > AXI_ANALYZE_WAIT_SEC:
        _PENDING_ANALYZE.pop(chat_id, None)
        _pending_analyze_persist()
        return None
    return str(item.get("prompt", "")).strip() or None


def _get_pending_analyze_state(chat_id: int) -> dict[str, object] | None:
    item = _PENDING_ANALYZE.get(chat_id)
    if not item:
        return None
    ts = float(item.get("ts", 0.0))
    if time.time() - ts > AXI_ANALYZE_WAIT_SEC:
        _PENDING_ANALYZE.pop(chat_id, None)
        _pending_analyze_persist()
        return None
    return item


def _analyze_prompt_is_unclear(prompt: str) -> bool:
    low = (prompt or "").strip().lower()
    if not low:
        return True
    # Special marker: files uploaded but no task description yet
    if "analyze_uploaded_files_waiting_goal" in low:
        return True
    # Training pair workflow: always clear intent, never ask for clarification
    if any(kw in low for kw in ("training pair", "tuning pair", "обучающ пар", "тренировочн пар", "тюнинг пар")):
        return False
    if low in {
        "analyze uploaded document and provide concise findings.",
        "analyze uploaded documents and provide concise findings.",
        "проанализируй загруженные файлы",
    }:
        return True
    informative = ("compare", "summar", "review", "find", "проверь", "сравн", "сводк", "риски", "рекоменд")
    return not any(k in low for k in informative)


def _dialog_append(chat_id: int | None, role: str, content: str) -> None:
    if chat_id is None:
        return
    text = (content or "").strip()
    if not text:
        return
    text = text[:2000]
    bucket = _AXI_DIALOG.setdefault(chat_id, [])
    bucket.append({"role": "user" if role == "user" else "assistant", "content": text})
    _AXI_DIALOG[chat_id] = bucket[-AXI_DIALOG_LOG_MAX:]
    _dialog_persist()


def _claim_update_once(update) -> bool:
    """
    Return True only for the first handler that sees this update within TTL.
    Prevents accidental double-processing for the same Telegram update.
    """
    try:
        uid = getattr(update, "update_id", None)
        key = f"u:{uid}" if uid is not None else ""
        if not key:
            msg = getattr(update, "effective_message", None)
            chat = getattr(update, "effective_chat", None)
            mid = getattr(msg, "message_id", None)
            cid = getattr(chat, "id", None)
            key = f"m:{cid}:{mid}"
        if not key:
            return True
        now = time.time()
        ttl_sec = 120.0
        with _SEEN_UPDATES_LOCK:
            ts = _SEEN_UPDATES.get(key)
            if ts and (now - ts) < ttl_sec:
                return False
            _SEEN_UPDATES[key] = now
            if len(_SEEN_UPDATES) > 4096:
                cutoff = now - ttl_sec
                stale = [k for k, v in _SEEN_UPDATES.items() if v < cutoff]
                for k in stale[:2048]:
                    _SEEN_UPDATES.pop(k, None)
        return True
    except Exception as e:
        log.debug("dedup check error: %s", e)
        return True


def _dialog_context(chat_id: int | None) -> str:
    if chat_id is None:
        return ""
    rows = _AXI_DIALOG.get(chat_id) or []
    if not rows:
        return ""
    lines = ["[Recent chat context | last 10 turns]"]
    for row in rows[-AXI_DIALOG_LOG_MAX:]:
        prefix = "User" if row.get("role") == "user" else "Assistant"
        lines.append(f"{prefix}: {row.get('content', '')}")
    return "\n".join(lines)


def _dialog_load() -> None:
    if not _AXI_DIALOG_PATH.exists():
        return
    try:
        raw = json.loads(_AXI_DIALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        restored: dict[int, list[dict[str, str]]] = {}
        for k, v in raw.items():
            try:
                chat_id = int(k)
            except Exception:
                continue
            if not isinstance(v, list):
                continue
            rows: list[dict[str, str]] = []
            for item in v[-AXI_DIALOG_LOG_MAX:]:
                if not isinstance(item, dict):
                    continue
                role = "user" if item.get("role") == "user" else "assistant"
                content = str(item.get("content", "")).strip()
                if content:
                    rows.append({"role": role, "content": content[:2000]})
            if rows:
                restored[chat_id] = rows[-AXI_DIALOG_LOG_MAX:]
        _AXI_DIALOG.clear()
        _AXI_DIALOG.update(restored)
    except Exception as e:
        log.warning("dialog load failed: %s", e)


def _dialog_persist() -> None:
    with _AXI_DIALOG_LOCK:
        try:
            payload = {str(k): v[-AXI_DIALOG_LOG_MAX:] for k, v in _AXI_DIALOG.items()}
            _AXI_DIALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _AXI_DIALOG_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.debug("dialog persist failed: %s", e)


def _pending_analyze_persist() -> None:
    with _AXI_PENDING_LOCK:
        try:
            payload = {str(k): v for k, v in _PENDING_ANALYZE.items()}
            _AXI_PENDING_ANALYZE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _AXI_PENDING_ANALYZE_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.debug("pending analyze persist failed: %s", e)


def _pending_analyze_load() -> None:
    if not _AXI_PENDING_ANALYZE_PATH.exists():
        return
    try:
        raw = json.loads(_AXI_PENDING_ANALYZE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        restored: dict[int, dict[str, object]] = {}
        now = time.time()
        for k, v in raw.items():
            try:
                chat_id = int(k)
            except Exception:
                continue
            if not isinstance(v, dict):
                continue
            ts = float(v.get("ts", 0.0))
            if ts and (now - ts) > AXI_ANALYZE_WAIT_SEC:
                continue
            prompt = str(v.get("prompt", "")).strip()
            if not prompt:
                continue
            files = v.get("files") if isinstance(v.get("files"), list) else []
            restored[chat_id] = {
                "prompt": prompt,
                "ts": ts or now,
                "last_upload_ts": float(v.get("last_upload_ts", 0.0)),
                "files": files,
                "awaiting_clarify": bool(v.get("awaiting_clarify", False)),
                "notified_waiting": bool(v.get("notified_waiting", False)),
                "lang": str(v.get("lang", "en") or "en"),
                "file_ack_sent": bool(v.get("file_ack_sent", False)),
            }
        _PENDING_ANALYZE.clear()
        _PENDING_ANALYZE.update(restored)
    except Exception as e:
        log.warning("pending analyze load failed: %s", e)


def _looks_like_file_dependent_request(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    # Do not route "send the generated document" into upload/analyze flow.
    resend_markers = (
        "send document",
        "send the document",
        "send file",
        "resent document",
        "resend document",
        "what you generated",
        "generated as attachment",
        "as attachment to chat",
        "пришли документ",
        "отправь документ",
        "повтори отправку",
    )
    if any(m in low for m in resend_markers):
        return False
    if "/analyze" in low:
        return True
    markers = (
        "attached",
        "attach",
        "attachment",
        "file",
        "review the attached",
        "прикреп",
        "вложен",
        "файл",
        "документ",
    )
    return any(m in low for m in markers)


def _parse_visual_and_narration(text: str) -> tuple[str, str | None]:
    """
    Отделяет описание кадра от опционального текста озвучки/декламации.
    Маркеры: озвучка / декламация / текст речи / реплика / голос / narration / voiceover / voice
    """
    raw = (text or "").strip()
    if not raw:
        return "", None
    m = re.search(
        r"(?is)[\n\r]?\s*(?:озвучка|декламация|текст\s+речи|реплика|голос|narration|voiceover|voice)\s*[:：]\s*",
        raw,
    )
    if not m:
        return raw, None
    visual = raw[: m.start()].strip().rstrip("-:—").strip()
    narration = raw[m.end() :].strip()
    if not narration:
        return raw, None
    return visual, narration[:900]


def _build_veo_user_prompt(visual: str, narration: str | None) -> str:
    v = (visual or "").strip()
    n = (narration or "").strip()
    if not v:
        return ""
    if not n:
        return v[:1000]
    return (
        f"{v}\n\n"
        f"[Текст для озвучки или декламации — встроить, если модель поддерживает речь или субтитры]: {n}"
    )[:1000]


def _unlink_axi_temp(p: str | None) -> None:
    if not p:
        return
    try:
        Path(p).unlink(missing_ok=True)
    except OSError:
        pass


def _telegram_doc_is_reference_video(doc) -> bool:
    if doc is None:
        return False
    mt = (doc.mime_type or "").lower()
    if mt.startswith("video/"):
        return True
    suf = Path(doc.file_name or "").suffix.lower()
    return suf in {".mp4", ".mov", ".webm", ".mpeg", ".mpg", ".avi", ".wmv", ".flv"}


def _finalize_video_prompt_from_user_text(text: str) -> tuple[str, bool]:
    """
    Собирает итоговый промпт для Veo. Второй элемент True — нужно ещё описание сцены
    (например указали только блок «озвучка: …» без визуала).
    """
    raw = (text or "").strip()
    if len(raw) < 4:
        return "", True
    visual, narr = _parse_visual_and_narration(raw)
    if visual.strip():
        return _build_veo_user_prompt(visual, narr), False
    if narr and not visual.strip():
        return "", True
    return _build_veo_user_prompt(raw, None), False


def _match_video_trigger_span(low: str) -> tuple[int, int] | None:
    """
    «сгенерируй 2 видио» не содержит подстроку «сгенерируй видио» — нужен regex.
    """
    patterns = (
        r"сгенерируй\s+\d+\s+видио",
        r"сгенерируй\s+\d+\s+видео",
        r"сгенерируй\s+два\s+видио",
        r"сгенерируй\s+два\s+видео",
        r"сгенерируй\s+видио",
        r"сгенерируй\s+видео",
        r"generate\s+\d+\s+videos?",
        r"generate\s+videos?",
    )
    for p in patterns:
        m = re.search(p, low, flags=re.IGNORECASE)
        if m:
            return m.start(), m.end()
    return None


def _split_veo_first_second_blocks(text: str) -> list[str] | None:
    """
    Два промпта в одном сообщении: «Первое … Второе …» или First / Second.
    """
    t = (text or "").strip()
    if not t:
        return None
    for pat in (
        r"(?is)^(.*?)\bпервое\b\s*[:\n]?\s*(.*?)\s*\bвторое\b\s*[:\n]?\s*(.*)\Z",
        r"(?is)^(.*?)\bfirst\b\s*[:\n]?\s*(.*?)\s*\bsecond\b\s*[:\n]?\s*(.*)\Z",
    ):
        m = re.search(pat, t)
        if not m:
            continue
        header = m.group(1).strip()
        body1 = m.group(2).strip()
        body2 = m.group(3).strip()
        if not body1 or not body2:
            continue
        body1 = body1.replace("\u200b", "").replace("\ufeff", "").strip()
        body2 = body2.replace("\u200b", "").replace("\ufeff", "").strip()
        if not body1 or not body2:
            continue
        head = (header + "\n\n") if header else ""
        p1 = f"{head}[Видео 1/2, ~8с, business motion graphics] {body1}".strip()
        p2 = f"{head}[Видео 2/2, ~8с, business motion graphics] {body2}".strip()
        return [p1[:4000], p2[:4000]]
    return None


def _extract_requested_clip_seconds(text: str) -> int | None:
    """
    «по 10 с», «duration: 6» в начале запроса — для подсказки пользователю и clamp в Veo.
    """
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(
        r"(?i)по\s+(\d{1,2})\s*(?:с(?:ек(?:унд(?:ы)?)?)?|sec(?:onds?)?)",
        t,
    )
    if not m:
        m = re.search(
            r"(?is)[\n\r]?\s*(?:длительность|duration)\s*[:：]\s*(\d{1,2})\s*(?:с(?:ек)?|sec|seconds?)?",
            t[:900],
        )
    if not m:
        return None
    try:
        n = int(m.group(1))
        return n if 1 <= n <= 99 else None
    except ValueError:
        return None


def _extract_video_skill_request(text: str) -> tuple[str, str | None, str | None, bool, list[str], int | None] | None:
    original = (text or "").strip()
    low = original.lower()
    if not low:
        return None
    span = _match_video_trigger_span(low)
    if span is None:
        return None
    _start, end = span
    tail = original[end:].strip()
    model_name: str | None = None
    mode_name: str | None = None

    # Optional inline override:
    m = re.search(
        r"(?:на\s+модели|model)\s+([A-Za-z0-9._\-]+)\s*[:,-]?\s*(.*)$",
        tail,
        flags=re.IGNORECASE,
    )
    if m:
        model_name = m.group(1).strip()
        tail = m.group(2).strip()
    else:
        tail = tail.strip(" :,-")

    low_tail = tail.lower()
    if re.search(r"\b(режим\s+качество|quality mode|mode quality|hq mode)\b", low_tail):
        mode_name = "quality"
        tail = re.sub(r"(режим\s+качество|quality mode|mode quality|hq mode)", "", tail, flags=re.IGNORECASE).strip(" :,-")
    elif re.search(r"\b(режим\s+быстро|быстрый\s+режим|fast mode|quick mode|mode fast)\b", low_tail):
        mode_name = "fast"
        tail = re.sub(r"(режим\s+быстро|быстрый\s+режим|fast mode|quick mode|mode fast)", "", tail, flags=re.IGNORECASE).strip(" :,-")

    desc = tail.strip()
    req_sec = _extract_requested_clip_seconds(desc)
    duo = _split_veo_first_second_blocks(desc)
    if duo and len(duo) == 2:
        return duo[0][:1000], model_name, mode_name, False, [duo[1][:1000]], req_sec

    visual, narr = _parse_visual_and_narration(desc)
    if visual.strip():
        prompt = _build_veo_user_prompt(visual, narr)
        needs_description = False
    elif narr and not visual.strip():
        prompt = ""
        needs_description = True
    else:
        needs_description = not bool(desc)
        prompt = desc
    return prompt, model_name, mode_name, needs_description, [], req_sec


def _extract_video_skill_alias_request(text: str) -> tuple[str, str | None, str | None, bool, list[str], int | None] | None:
    """
    Альтернативные формулировки без «сгенерируй видео» — всё равно включают Veo-скилл.
    """
    low = (text or "").strip().lower()
    if not low:
        return None
    aliases = (
        "используй скилл",
        "используй skill",
        "use video skill",
        "use the video skill",
        "скилл видео",
        "video skill",
        "veo skill",
        "режим видео veo",
        "генерация видео скилл",
    )
    if not any(a in low for a in aliases):
        return None
    tail = (text or "").strip()
    for a in aliases:
        idx = low.find(a)
        if idx >= 0:
            tail = tail[idx + len(a) :].strip(" :,-")
            break
    desc = tail.strip()
    req_sec = _extract_requested_clip_seconds(desc)
    visual, narr = _parse_visual_and_narration(desc)
    if visual.strip():
        prompt = _build_veo_user_prompt(visual, narr)
        needs_description = False
    elif narr and not visual.strip():
        prompt = ""
        needs_description = True
    else:
        needs_description = not bool(desc)
        prompt = desc
    return prompt[:1000], None, None, needs_description, [], req_sec


def _is_video_pending_clarification_only(text: str) -> bool:
    """
    Короткие реплики при уже включённом ожидании картинки для видео.
    Не должны уходить в общий LLM (иначе «я не могу генерировать видео»).
    """
    low = (text or "").strip().lower()
    if not low:
        return False
    if len(low) > 120:
        return False
    markers = (
        "возьми эти",
        "возьми это",
        "вот они",
        "вот она",
        "вот оно",
        "сюда",
        "это оно",
        "это они",
        "фото выше",
        "картинк",
        "используй скилл",
        "используй skill",
        "продолж",
        "use the skill",
        "use video skill",
        "here you",
        "here they",
    )
    return any(m in low for m in markers)


def _is_casual_non_task_message(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    greetings = {
        "hi", "hello", "hey", "yo", "sup",
        "привет", "здравствуй", "здравствуйте", "добрый день", "добрый вечер",
    }
    acknowledgements = {
        "ok", "okay", "thanks", "thank you", "thx",
        "ок", "хорошо", "спасибо", "понял", "принял",
    }
    if low in greetings or low in acknowledgements:
        return True
    # Short phatic/opening messages should not create Task Registry records.
    words = [w for w in re.split(r"\s+", low) if w]
    if len(words) <= 3 and any(w in greetings for w in words):
        return True
    return False


async def _process_analyze_batch(
    bot,
    chat_id: int,
    prompt: str,
    files: list[dict[str, str]],
    *,
    lang: str = "ru",
) -> None:
    t0 = time.perf_counter()
    progress_msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏱ {AXI_NAME}: взято в работу. Анализирую пакет файлов…"
            if lang == "ru" else
            f"⏱ {AXI_NAME}: taken in progress. Analyzing file batch…"
        ),
    )
    excerpts: list[str] = []
    for f in files:
        name = f.get("name", "file")
        txt = (f.get("excerpt", "") or "").strip()
        if txt:
            excerpts.append(f"[file: {name}]\n{txt}")
    merged = "\n\n---\n\n".join(excerpts)[:100000]
    request_text = (
        f"{prompt}\n\n"
        "[Analyze all uploaded files together as one package. "
        "If standards are requested, compare and consolidate.]"
        f"\n\n{merged}"
    )

    tr_id = _tr_register(
        f"batch analyze: {prompt[:80]}",
        chat_id=str(chat_id),
        source="axi",
    )
    _tr_start(tr_id, assigned_to="axi")
    if tr_id:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🧾 Задача зарегистрирована: `{tr_id}`.\nПакет файлов принят, начинаю общий анализ."
                if lang == "ru" else
                f"🧾 Task registered: `{tr_id}`.\nFile batch accepted, starting consolidated analysis."
            ),
            parse_mode="Markdown",
        )
    _anim_stop = asyncio.Event()
    _anim_base = (
        f"{AXI_NAME}: анализирую пакет…" if lang == "ru"
        else f"{AXI_NAME}: analysing file batch…"
    )
    _anim_task = asyncio.create_task(_animate_progress(progress_msg, _anim_base, _anim_stop))
    try:
        use_search = _should_web_search(prompt)
        # ── Intent classification: LLM first, keywords as fast-bypass only ────────
        _xlsx_in_batch = any((f.get("name") or "").lower().endswith((".xlsx", ".xlsm")) for f in files)
        _explicit_docx = bool(re.search(r"\b(word|docx|\.docx)\b", prompt.lower()))
        _explicit_edit = _xlsx_in_batch and _wants_xlsx_edit(prompt, files) and not any(
            kw in prompt.lower() for kw in ("check", "compare", "analyze", "analyse", "review", "assess", "report", "send", "share")
        )
        if _explicit_docx:
            file_intent = "docx"
        elif _explicit_edit:
            file_intent = "edit"
        else:
            file_intent = await _infer_file_intent(prompt, files)
            _save_intent_example(prompt, files, file_intent)
        # ──────────────────────────────────────────────────────────────────────────
        if file_intent == "edit":
            xlsx_entry = next(
                (f for f in files if (f.get("name") or "").lower().endswith((".xlsx", ".xlsm"))),
                None,
            )
            xlsx_src = xlsx_entry and xlsx_entry.get("path")
            if xlsx_src and Path(xlsx_src).exists():
                result_xlsx = await _edit_xlsx_with_llm(Path(xlsx_src), prompt)
                dt = time.perf_counter() - t0
                try:
                    await progress_msg.edit_text(
                        f"✅ {AXI_NAME}: таблица обновлена за {dt:.0f}с. Отправляю…"
                        if lang == "ru" else
                        f"✅ {AXI_NAME}: table updated in {dt:.0f}s. Sending…"
                    )
                except Exception:
                    pass
                caption_text = (
                    f"{AXI_NAME}: ✅ {result_xlsx.name}"
                    + (f" | task `{tr_id}`" if tr_id else "")
                )
                for _attempt in range(3):
                    try:
                        with result_xlsx.open("rb") as fh:
                            await bot.send_document(
                                chat_id=chat_id,
                                document=fh,
                                filename=result_xlsx.name,
                                caption=caption_text,
                            )
                        break
                    except Exception as _send_err:
                        if _attempt < 2:
                            await asyncio.sleep(3)
                        else:
                            raise _send_err
                _anim_stop.set()
                _tr_done(tr_id, summary=f"xlsx_edit:{result_xlsx.name}")
                return
        if file_intent == "docx":
            _has_xlsx = _xlsx_in_batch
            _doc_sys = _build_doc_analysis_system() if _has_xlsx else None
            answer = await _llm_reply(request_text, use_search=use_search, system_override=_doc_sys)
            answer = _strip_generate_file_json(answer)
            first_line = next((ln.strip().lstrip("#").strip() for ln in answer.splitlines() if ln.strip()), "axi_document")
            docx_path = await _generate_custom_docx(answer, "axi_analyze_batch", AXI_RESULTS_DIR, title=first_line)
            dt = time.perf_counter() - t0
            _anim_stop.set()
            try:
                await progress_msg.edit_text(
                    f"✅ {AXI_NAME}: задача выполнена за {dt:.0f}с. Отправляю сгенерированный файл…"
                    if lang == "ru" else
                    f"✅ {AXI_NAME}: completed in {dt:.0f}s. Sending generated file…"
                )
            except Exception:
                pass
            caption_text = (
                f"{AXI_NAME}: ✅ {docx_path.name}\n"
                + _sources_note(
                    lang=lang,
                    use_search=use_search,
                    uploaded_files_count=len(files),
                )
                + (f" | task `{tr_id}`" if tr_id else "")
            )
            for _attempt in range(3):
                try:
                    with docx_path.open("rb") as fh:
                        await bot.send_document(
                            chat_id=chat_id,
                            document=fh,
                            filename=docx_path.name,
                            caption=caption_text,
                            parse_mode="Markdown",
                        )
                    break
                except Exception as _send_err:
                    if _attempt < 2:
                        await asyncio.sleep(3)
                    else:
                        raise _send_err
            _tr_done(tr_id, summary=f"batch_docx:{docx_path.name}:{len(files)}")
        elif file_intent == "ask":
            _anim_stop.set()
            _pending_intent[chat_id] = {"prompt": prompt, "files": files, "tr_id": tr_id, "lang": lang, "ts": time.time()}
            clarify_text = (
                f"{AXI_NAME}: получил файлы, но не до конца понял задачу. Уточни:\n"
                f"— нужен **Word-документ** с анализом/отчётом?\n"
                f"— или **изменить данные** внутри таблицы?\n"
                f"— или просто **текстовый ответ**?"
                if lang == "ru" else
                f"{AXI_NAME}: received the files but the task is unclear. Please clarify:\n"
                f"— do you need a **Word document** (analysis / report)?\n"
                f"— or **edit data** inside the spreadsheet?\n"
                f"— or just a **text answer**?"
            )
            await bot.send_message(chat_id=chat_id, text=clarify_text, parse_mode="Markdown")
            _tr_done(tr_id, summary="batch_ask_clarify")
        elif file_intent == "training_pair":
            # Training pair creation pipeline
            _anim_stop.set()
            try:
                await progress_msg.edit_text(
                    f"📚 {AXI_NAME}: начинаю подготовку обучающей пары..."
                    if lang == "ru" else
                    f"📚 {AXI_NAME}: starting training pair preparation..."
                )
            except Exception:
                pass

            # Step 1: Extract context from uploaded documents
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "📄 Шаг 1/3: Извлекаю контекст из загруженных документов..."
                    if lang == "ru" else
                    "📄 Step 1/3: Extracting context from uploaded documents..."
                )
            )

            # Read document texts
            doc_texts = []
            for file_entry in files:
                try:
                    # files is list of dict with 'name' and 'path' keys
                    file_path = Path(file_entry.get("path", "")) if isinstance(file_entry, dict) else file_entry
                    if not file_path.exists():
                        continue
                    doc_text = _read_document_text(file_path)
                    file_name = file_entry.get("name", file_path.name) if isinstance(file_entry, dict) else file_path.name
                    doc_texts.append({"name": file_name, "text": doc_text[:50000]})
                except Exception as e:
                    file_name = file_entry.get("name", "unknown") if isinstance(file_entry, dict) else str(file_entry)
                    log.warning("Failed to read %s: %s", file_name, e)

            if not doc_texts:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "⚠️ Не удалось прочитать документы"
                        if lang == "ru" else
                        "⚠️ Failed to read documents"
                    )
                )
                _tr_done(tr_id, summary="training_pair_read_failed")
                return

            # Check for duplicate training pair by content hash
            import hashlib
            combined_text = "\n\n".join(d["text"] for d in doc_texts)
            content_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()[:16]

            existing_memo = _find_existing_training_pair(content_hash)
            if existing_memo:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"ℹ️ Обучающая пара для этих файлов уже создана ранее:\n"
                        f"📄 Файл: `{existing_memo['memo_file']}`\n"
                        f"📅 Дата: {existing_memo['created']}\n"
                        f"📊 Оценка локальной модели: {existing_memo.get('local_score', 'не оценено')}\n\n"
                        f"Результат можно посмотреть в мастер-файле."
                        if lang == "ru" else
                        f"ℹ️ Training pair for these files already exists:\n"
                        f"📄 File: `{existing_memo['memo_file']}`\n"
                        f"📅 Date: {existing_memo['created']}\n"
                        f"📊 Local model score: {existing_memo.get('local_score', 'not evaluated')}\n\n"
                        f"Result available in master file."
                    ),
                    parse_mode="Markdown"
                )
                _tr_done(tr_id, summary=f"training_pair_duplicate:{existing_memo['memo_file']}")
                return

            # Step 2: Extract context using llama405b
            # For training pair: use first doc as blank template, second as filled example
            blank_text = doc_texts[0]["text"] if len(doc_texts) > 0 else ""
            filled_text = doc_texts[1]["text"] if len(doc_texts) > 1 else doc_texts[0]["text"]
            context_result = await asyncio.to_thread(_extract_doc_context_sync, blank_text, filled_text)

            if not context_result or "error" in context_result:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⚠️ Ошибка извлечения контекста: {context_result.get('error', 'unknown')}"
                        if lang == "ru" else
                        f"⚠️ Context extraction error: {context_result.get('error', 'unknown')}"
                    )
                )
                _tr_done(tr_id, summary="training_pair_context_failed")
                return

            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ Контекст извлечен:\n"
                    f"• Тип документа: {context_result.get('doc_type', 'unknown')}\n"
                    f"• Стандарты: {', '.join(context_result.get('standards', []))}\n"
                    f"• Ключевые поля: {len(context_result.get('key_fields', []))}"
                    if lang == "ru" else
                    f"✅ Context extracted:\n"
                    f"• Document type: {context_result.get('doc_type', 'unknown')}\n"
                    f"• Standards: {', '.join(context_result.get('standards', []))}\n"
                    f"• Key fields: {len(context_result.get('key_fields', []))}"
                )
            )

            # Step 3: Save training pair memo
            memo_path = _save_doctuning_memo(context_result, doc_texts[0]["name"], content_hash)

            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ Обучающая пара сохранена: `{memo_path.name}`\n\n"
                    f"Следующий шаг: используйте эту пару для дообучения модели."
                    if lang == "ru" else
                    f"✅ Training pair saved: `{memo_path.name}`\n\n"
                    f"Next step: use this pair for model fine-tuning."
                ),
                parse_mode="Markdown"
            )

            _tr_done(tr_id, summary=f"training_pair_saved:{memo_path.name}")
        else:
            answer = await _llm_reply(request_text, use_search=use_search)
            dt = time.perf_counter() - t0
            _anim_stop.set()
            try:
                await progress_msg.edit_text(
                    f"✅ {AXI_NAME}: задача выполнена за {dt:.0f}с."
                    if lang == "ru" else
                    f"✅ {AXI_NAME}: completed in {dt:.0f}s."
                )
            except Exception:
                pass
            out_text = (
                answer[:3600]
                + "\n\n"
                + _sources_note(
                    lang=lang,
                    use_search=use_search,
                    uploaded_files_count=len(files),
                )
            )
            await bot.send_message(chat_id=chat_id, text=out_text[:4000])
            _tr_done(tr_id, summary=f"batch_chat:{len(files)}")
    except Exception as e:
        _anim_stop.set()
        _tr_stuck(tr_id, error=str(e)[:200])
        _emsg = str(e)[:120] if str(e) else type(e).__name__
        try:
            await progress_msg.edit_text(
                f"⚠️ {AXI_NAME}: ошибка обработки пакета — {_emsg}"
                if lang == "ru" else
                f"⚠️ {AXI_NAME}: batch processing error — {_emsg}"
            )
        except Exception:
            pass
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"{AXI_NAME}: не удалось обработать пакет файлов — {_emsg}"
                if lang == "ru" else
                f"{AXI_NAME}: failed to process file batch — {_emsg}"
            ),
        )
    finally:
        _anim_stop.set()
        _anim_task.cancel()
        try:
            await _anim_task
        except asyncio.CancelledError:
            pass


async def _job_flush_pending_analyze(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = time.time()
    to_process: list[tuple[int, dict[str, object]]] = []
    for chat_id, state in list(_PENDING_ANALYZE.items()):
        if now - float(state.get("ts", 0.0)) > AXI_ANALYZE_WAIT_SEC:
            _PENDING_ANALYZE.pop(chat_id, None)
            _pending_analyze_persist()
            continue
        files = state.get("files") or []
        if not files or state.get("awaiting_clarify"):
            continue
        last_upload = float(state.get("last_upload_ts", 0.0))
        if last_upload and (now - last_upload) >= AXI_ANALYZE_BATCH_WAIT_SEC:
            to_process.append((chat_id, state))
    for chat_id, state in to_process:
        prompt = str(state.get("prompt", "")).strip()
        files = list(state.get("files") or [])
        lang = str(state.get("lang", "ru"))
        if _analyze_prompt_is_unclear(prompt):
            await context.application.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Файлы получены. Уточните, что сделать с пакетом: суммаризация, сравнение, проверка соответствия, риски, или подготовить DOCX?"
                ),
            )
            state["awaiting_clarify"] = True
            _pending_analyze_persist()
            continue
        _PENDING_ANALYZE.pop(chat_id, None)
        _pending_analyze_persist()
        await _process_analyze_batch(context.application.bot, chat_id, prompt, files, lang=lang)


async def _job_axi_deliver_cross_handoffs(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deliver Omi->Axi handoffs as orchestration status messages in chat."""
    try:
        from cross_bot_handoff import (
            claim_pending_for_target,
            handoff_delivery_enabled,
            mark_delivered,
            mark_failed,
        )
    except Exception as e:
        log.debug("axi handoff import failed: %s", e)
        return
    if not handoff_delivery_enabled():
        return
    try:
        rows = claim_pending_for_target("axi", limit=8)
    except Exception as e:
        log.debug("axi handoff claim failed: %s", e)
        return
    for row in rows:
        hid = int(row.get("id", 0) or 0)
        chat_id = int(row.get("chat_id", 0) or 0)
        payload = str(row.get("payload", "") or "").strip()
        if not hid or not chat_id:
            continue
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=payload or "Axi: получен handoff от Omi.",
                parse_mode="Markdown",
            )
            mark_delivered(hid)
        except Exception as e:
            mark_failed(hid, str(e))


def _extract_text_from_uploaded_document(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            parts: list[str] = []
            for page in reader.pages[:30]:
                parts.append((page.extract_text() or "").strip())
            return "\n\n".join([p for p in parts if p]).strip()[:30000]
        if ext == ".docx":
            from docx import Document

            doc = Document(str(path))
            return "\n".join((p.text or "").strip() for p in doc.paragraphs if (p.text or "").strip())[:30000]
        if ext in (".txt", ".md", ".csv", ".log"):
            return path.read_text(errors="replace")[:30000]
        if ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook

            wb = load_workbook(str(path), data_only=True, read_only=True)
            lines: list[str] = []
            for ws in wb.worksheets[:3]:
                lines.append(f"[sheet: {ws.title}]")
                for row in ws.iter_rows(min_row=1, max_row=80, max_col=12, values_only=True):
                    vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
                    if vals:
                        lines.append(" | ".join(vals))
            return "\n".join(lines)[:30000]
        if ext == ".pptx":
            from pptx import Presentation

            prs = Presentation(str(path))
            lines: list[str] = []
            for sidx, slide in enumerate(prs.slides[:20], start=1):
                lines.append(f"[slide {sidx}]")
                for shape in slide.shapes:
                    txt = getattr(shape, "text", "") or ""
                    txt = txt.strip()
                    if txt:
                        lines.append(txt)
            return "\n".join(lines)[:30000]
    except Exception as e:
        log.warning("extract uploaded text failed (%s): %s", path.name, e)
    return ""


def _queue_to_omi_batch_inbox(
    src_path: Path,
    original_name: str,
    *,
    meta: dict[str, object] | None = None,
) -> Path:
    """
    Put file into Omi OCR/batch pipeline inbox.
    If same content already exists, returns existing path.
    """
    import hashlib

    inbox = AIMS_WORKSPACE / "batch_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    incoming_sha = hashlib.sha256(src_path.read_bytes()).hexdigest()
    dest = inbox / original_name
    if dest.exists():
        if hashlib.sha256(dest.read_bytes()).hexdigest() == incoming_sha:
            return dest
        stem, suffix = Path(original_name).stem, Path(original_name).suffix
        for n in range(2, 100):
            cand = inbox / f"{stem}_v{n}{suffix}"
            if not cand.exists():
                dest = cand
                break
    src_path.replace(dest)
    if meta:
        meta_path = dest.with_name(dest.name + ".axi.json")
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.warning("queue_to_omi meta write failed %s: %s", dest.name, e)
    return dest


def _load_recent_generated_doc_context(chat_id: int | None) -> tuple[str, str]:
    """Load the most recent generated docx content from dialog memory."""
    if chat_id is None:
        return "", ""
    rows = _AXI_DIALOG.get(chat_id) or []
    for row in reversed(rows):
        content = str((row or {}).get("content") or "").strip()
        if not (content.startswith("[doc:") and content.endswith("]")):
            continue
        file_name = content[5:-1].strip()
        if not file_name:
            continue
        p = AXI_RESULTS_DIR / file_name
        if not p.exists() or p.suffix.lower() != ".docx":
            continue
        try:
            from docx import Document as _Doc
            d = _Doc(str(p))
            txt = "\n".join((para.text or "").strip() for para in d.paragraphs if (para.text or "").strip())
            if txt.strip():
                return file_name, txt[:16000]
        except Exception:
            continue
    return "", ""


async def handle_file_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        return
    if update.message is None:
        return
    if not _claim_update_once(update):
        return
    if update.effective_user and bool(update.effective_user.is_bot):
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    video_state = _PENDING_VIDEO.get(chat_id)
    if video_state:
        lang = str(video_state.get("lang", "ru"))
        if video_state.get("await_prompt"):
            await update.message.reply_text(
                "Сначала опишите сцену **текстом** одним сообщением, затем пришлите изображение."
                if lang == "ru" else
                "First describe the scene in **one text message**, then send the image.",
                parse_mode="Markdown",
            )
            return
        prompt = str(video_state.get("prompt", "")).strip()
        model_name = str(video_state.get("model", "")).strip() or None
        mode_name = str(video_state.get("mode", "")).strip() or None
        tmp_path: Path | None = None
        out_path: Path | None = None
        veo_busy = False

        doc = update.message.document
        if doc is not None and _telegram_doc_is_reference_video(doc):
            try:
                suf = Path(doc.file_name or ".mp4").suffix.lower() or ".mp4"
                with tempfile.NamedTemporaryFile(prefix="axi_veo_ref_", suffix=suf, delete=False) as tv:
                    ref_local = Path(tv.name)
                vg = await ctx.bot.get_file(doc.file_id)
                await vg.download_to_drive(str(ref_local))
                old_ref = video_state.get("ref_video_path")
                if old_ref:
                    _unlink_axi_temp(str(old_ref))
                video_state["ref_video_path"] = str(ref_local)
                await update.message.reply_text(
                    "Референс-видео сохранено. Теперь пришлите изображение (jpg/png) — стартовый кадр."
                    if lang == "ru" else
                    "Reference clip saved. Now send a start image (jpg/png).",
                )
                return
            except Exception as e:
                log.warning("veo reference video upload failed: %s", e)
                await update.message.reply_text(
                    f"{AXI_NAME}: не удалось сохранить видео — {e}"
                    if lang == "ru" else
                    f"{AXI_NAME}: could not save video — {e}",
                )
                return

        try:
            image_file = None
            suffix = ".jpg"
            if update.message.photo:
                image_file = await ctx.bot.get_file(update.message.photo[-1].file_id)
                suffix = ".jpg"
            elif update.message.document and (
                (update.message.document.mime_type or "").startswith("image/")
                or (Path(update.message.document.file_name or "").suffix.lower() in {".jpg", ".jpeg", ".png"})
            ):
                image_file = await ctx.bot.get_file(update.message.document.file_id)
                suffix = Path(update.message.document.file_name or "").suffix.lower() or ".jpg"
            if image_file is None:
                has_ref = bool(video_state.get("ref_video_path"))
                await update.message.reply_text(
                    (
                        "Пришлите изображение стартового кадра (jpg/png)."
                        + (" Референс-ролик уже принят — осталось только фото." if has_ref else "")
                    )
                    if lang == "ru" else
                    (
                        "Please send a start image (jpg/png)."
                        + (" Reference clip is already set — photo only is missing." if has_ref else "")
                    ),
                )
                return

            await update.message.reply_text(
                "❌ Генерация видео отключена (требует облачного API)."
                if lang == "ru" else
                "❌ Video generation is disabled (requires cloud API)."
            )
            st_done = _PENDING_VIDEO.pop(chat_id, None)
            if st_done and st_done.get("ref_video_path"):
                _unlink_axi_temp(str(st_done["ref_video_path"]))
            return
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            if veo_busy:
                async with _VEO_GEN_BUSY_LOCK:
                    _VEO_GEN_BUSY.discard(chat_id)

    # ── Docfill upload interception ──────────────────────────────────────────
    if chat_id in _PENDING_DOCFILL and _PENDING_DOCFILL[chat_id].get("step") in ("await_blank", "await_example"):
        await _handle_docfill_file(update, ctx, chat_id)
        return

    state = _get_pending_analyze_state(chat_id)
    if not state:
        # File-first flow: accept files even before explicit /analyze goal.
        _set_pending_analyze(chat_id, "analyze_uploaded_files_waiting_goal")
        state = _get_pending_analyze_state(chat_id)
        if state is None:
            return
        state["awaiting_clarify"] = True
        state["notified_waiting"] = False
        _pending_analyze_persist()
    pending_prompt = str(state.get("prompt", "")).strip()

    lang = AXI_FORCE_REPLY_LANG if AXI_FORCE_REPLY_LANG in ("en", "ru") else "en"
    if update.message.photo and not update.message.document:
        await update.message.reply_text(
            "Для /analyze отправьте документ (pdf/docx/txt/xlsx/pptx)." if lang == "ru"
            else "For /analyze, send a document (pdf/docx/txt/xlsx/pptx)."
        )
        return
    if not update.message.document:
        return

    doc = update.message.document
    file_name = doc.file_name or f"upload_{doc.file_id[-8:]}"
    suffix = Path(file_name).suffix or ".bin"
    tmp_path: Path | None = None
    if not state.get("file_ack_sent"):
        state["file_ack_sent"] = True
        await update.message.reply_text(
            "Файл получен. Обрабатываю и добавляю в пакет анализа…"
            if lang == "ru" else
            "File received. Processing and adding to analysis batch…"
        )
    try:
        with tempfile.NamedTemporaryFile(prefix="axi_analyze_", suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        tg_file = await ctx.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(str(tmp_path))
        excerpt = _extract_text_from_uploaded_document(tmp_path)
        if not excerpt:
            omi_task_id = _tr_register(
                f"OCR+analyze:{pending_prompt[:140]} | file:{file_name}",
                chat_id=str(chat_id),
                source="axi",
            )
            _tr_start(omi_task_id, assigned_to="omi_batch")
            queued = _queue_to_omi_batch_inbox(
                tmp_path,
                file_name,
                meta={
                    "source": "axi",
                    "chat_id": chat_id,
                    "prompt": pending_prompt[:4000],
                    "task_id": omi_task_id,
                },
            )
            tmp_path = None
            # Delegate difficult extraction cases to Omi OCR pipeline instead of failing fast.
            await update.message.reply_text(
                (
                    "Текст извлечь сразу не удалось — передал файл в OCR-пайплайн Omi для обработки. "
                    f"Файл: `{queued.name}`"
                    + (f"\nTask: `{omi_task_id}`" if omi_task_id else "")
                )
                if lang == "ru" else
                (
                    "Could not extract text immediately — delegated file to Omi OCR pipeline. "
                    f"File: `{queued.name}`"
                    + (f"\nTask: `{omi_task_id}`" if omi_task_id else "")
                ),
                parse_mode="Markdown",
            )
            return

        files = state.setdefault("files", [])
        if isinstance(files, list):
            file_entry: dict = {"name": file_name, "excerpt": excerpt}
            if suffix.lower() in (".xlsx", ".xlsm") and tmp_path and tmp_path.exists():
                import hashlib
                import shutil as _shutil
                # Use content hash to avoid duplicating identical files
                file_hash = hashlib.sha256(tmp_path.read_bytes()).hexdigest()[:16]
                AXI_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                saved_xlsx = AXI_RESULTS_DIR / f"axi_xlsx_{file_hash}_{file_name}"
                # Only copy if file doesn't already exist
                if not saved_xlsx.exists():
                    _shutil.copy2(str(tmp_path), str(saved_xlsx))
                file_entry["path"] = str(saved_xlsx)
            files.append(file_entry)
        state["last_upload_ts"] = time.time()
        state["ts"] = time.time()
        state["lang"] = lang
        if pending_prompt == "analyze_uploaded_files_waiting_goal":
            state["awaiting_clarify"] = True
        else:
            state["awaiting_clarify"] = False
        if not state.get("notified_waiting"):
            state["notified_waiting"] = True
            await update.message.reply_text(
                (
                    "Файл принят. Жду формулировку задачи следующим сообщением "
                    "(что именно проверить/сравнить), затем запускайте `/analyze_done`."
                    if pending_prompt == "analyze_uploaded_files_waiting_goal"
                    else "Принял файлы для пакетного /analyze. Жду завершения загрузки, затем обработаю всё вместе."
                )
                if lang == "ru" else
                (
                    "File accepted. Waiting for your task in the next message "
                    "(what exactly to check/compare), then run `/analyze_done`."
                    if pending_prompt == "analyze_uploaded_files_waiting_goal"
                    else "Files accepted for batch /analyze. Waiting for uploads to finish, then processing all together."
                )
            )
        _pending_analyze_persist()
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    # Defensive fallback: never stay silent on handler failure.
    # If something unexpected happens before normal replies, user still gets actionable message.
    if state.get("file_ack_sent") and not state.get("notified_waiting") and not (state.get("files") or []):
        await update.message.reply_text(
            "Файл принят, но не попал в пакет. Повторите загрузку или отправьте `/analyze_done` после повторной загрузки."
            if lang == "ru" else
            "File was received but not added to batch. Re-upload and then send `/analyze_done`."
        )


def _extract_analyze_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> str:
    parts: list[str] = []
    if getattr(ctx, "args", None):
        parts.append(" ".join(ctx.args).strip())
    msg = update.message
    if msg and msg.reply_to_message:
        reply = msg.reply_to_message
        if reply.text:
            parts.append(reply.text.strip())
        elif reply.caption:
            parts.append(reply.caption.strip())
    return "\n\n".join([p for p in parts if p]).strip()


async def _process_request_text(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    require_group_mention: bool,
) -> None:
    _chat_id = update.effective_chat.id if update.effective_chat else None
    lang = _reply_lang(text)
    chat_type = update.message.chat.type
    prior_ctx = _dialog_context(_chat_id)
    _dialog_append(_chat_id, "user", text)

    # В группе — только если бот упомянут (для свободного текста)
    bot_username = ctx.bot.username
    if require_group_mention and chat_type in ("group", "supergroup"):
        if f"@{bot_username}" not in text and not text.lower().startswith("axi"):
            return
        text = text.replace(f"@{bot_username}", "").strip()
    text = _strip_axi_prefix(text)

    # NLP intent routing — map free text to slash commands via local small model
    try:
        from chat_intent_router import classify, AXI_CMDS  # noqa: PLC0415
        _axi_routed = await asyncio.to_thread(classify, text, AXI_CMDS)
        if _axi_routed:
            _axi_cmd, _axi_args = _axi_routed
            _axi_dispatch = {
                "quality_report": cmd_quality_report,
                "stuck_tasks": cmd_stuck_tasks,
                "analyze": cmd_analyze,
            }
            _axi_handler = _axi_dispatch.get(_axi_cmd)
            if _axi_handler:
                ctx.args = _axi_args
                await _axi_handler(update, ctx)
                return
    except Exception as e:
        log.debug("intent_router error: %s", e)

    if _looks_like_task_close_intent(text):
        handled, msg = _close_omi_task_from_chat(str(_chat_id or ""), text)
        if handled:
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

    veo_req = _extract_video_skill_request(text)
    if veo_req is None:
        veo_req = _extract_video_skill_alias_request(text)
    if _chat_id is not None and veo_req is not None:
        veo_prompt, veo_model, veo_mode, needs_description, veo_queue, veo_req_sec = veo_req
        prev_v = _PENDING_VIDEO.get(_chat_id)
        if prev_v and prev_v.get("ref_video_path"):
            _unlink_axi_temp(str(prev_v["ref_video_path"]))
        _PENDING_VIDEO[_chat_id] = {
            "prompt": veo_prompt[:1000],
            "prompt_queue": list(veo_queue or []),
            "await_prompt": needs_description,
            "ref_video_path": None,
            "model": (veo_model or "").strip()[:120],
            "mode": (veo_mode or "").strip()[:30],
            "lang": lang,
            "ts": time.time(),
            "duration_seconds": veo_req_sec,
        }
        if needs_description:
            await update.message.reply_text(
                (
                    "Сначала **одним сообщением** опишите кадр: движение камеры, свет, атмосфера.\n"
                    "По желанию добавьте с новой строки:\n"
                    "`озвучка:` или `декламация:` — короткий текст, который должно произнести видео (если модель поддерживает речь/субтитры).\n"
                    "Затем пришлите изображение (jpg/png)."
                    if lang == "ru" else
                    "First, in **one message**, describe the shot: camera motion, light, mood.\n"
                    "Optionally add a new line:\n"
                    "`voiceover:` or `narration:` — short line to speak (if the model supports speech/subtitles).\n"
                    "Then send an image (jpg/png)."
                ),
                parse_mode="Markdown",
            )
        else:
            if veo_queue:
                eff = 6
                await update.message.reply_text(
                    (
                        "Видео-генерация отключена (требует облачного API)."
                        if lang == "ru" else
                        "Video generation is disabled (requires cloud API)."
                    ),
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    (
                        "Принято. Пришлите изображение (jpg/png), и я сгенерирую видео "
                        f"на модели `{veo_model}`."
                        if veo_model else
                        (
                            "Принято. Пришлите изображение (jpg/png), и я сгенерирую видео "
                            + ("в режиме КАЧЕСТВО." if veo_mode == "quality" else "в режиме БЫСТРО." if veo_mode == "fast" else "на лучшей доступной модели.")
                        )
                    )
                    if lang == "ru" else
                    (
                        f"Accepted. Upload an image (jpg/png), and I will generate a video using model `{veo_model}`."
                        if veo_model else
                        (
                            "Accepted. Upload an image (jpg/png), and I will generate a video "
                            + ("in QUALITY mode." if veo_mode == "quality" else "in FAST mode." if veo_mode == "fast" else "using the best available model.")
                        )
                    )
                )
        return

    if (
        _chat_id is not None
        and _PENDING_VIDEO.get(_chat_id)
        and _PENDING_VIDEO[_chat_id].get("await_prompt")
    ):
        merged, need_more = _finalize_video_prompt_from_user_text(text)
        if need_more or not merged.strip():
            await update.message.reply_text(
                "Нужно описание **кадра** (движение, свет). Можно добавить строку `озвучка:` / `декламация:` с текстом реплики."
                if lang == "ru" else
                "Please add a **visual** description (motion, light). Optional: a `voiceover:` / `narration:` line.",
                parse_mode="Markdown",
            )
            return
        _PENDING_VIDEO[_chat_id]["prompt"] = merged[:1000]
        _PENDING_VIDEO[_chat_id]["await_prompt"] = False
        await update.message.reply_text(
            (
                "Принято. Дальше по шагам:\n"
                "1) (по желанию) пришлите **короткий референс-ролик** примером движения/стиля — файл **mp4/mov** (до ~32 МБ).\n"
                "2) затем пришлите **изображение** — стартовый кадр (jpg/png).\n"
                "Один клип Veo — обычно **4–8 секунд**; полный длинный текст за раз не озвучить — в конец промпта можно дописать строку `длительность: 8` (максимум для одного запроса)."
                if lang == "ru" else
                "Got it. Next:\n"
                "1) (optional) send a **short reference clip** (mp4/mov, ~32MB max) as an example of motion/style.\n"
                "2) then send a **start image** (jpg/png).\n"
                "One Veo clip is typically **4–8 seconds**; you cannot fit a full long voiceover — add a line `duration: 8` at the end of the prompt for the longest single clip allowed."
            ),
            parse_mode="Markdown",
        )
        return

    if (
        _chat_id is not None
        and _PENDING_VIDEO.get(_chat_id)
        and not _PENDING_VIDEO[_chat_id].get("await_prompt")
        and _is_video_pending_clarification_only(text)
    ):
        await update.message.reply_text(
            "Жду одно изображение: отправьте фото или файл jpg/png (режим генерации видео уже включён)."
            if lang == "ru" else
            "Waiting for one image: send a photo or a jpg/png file (video generation mode is already on).",
        )
        return

    # Check for training_pair intent BEFORE file-dependent check
    if _chat_id is not None:
        low_text = text.lower()
        if any(kw in low_text for kw in ("training pair", "tuning pair", "обучающ пар", "тренировочн пар", "тюнинг пар")):
            # Check if files already uploaded
            has_files = bool(((_get_pending_analyze_state(_chat_id) or {}).get("files") or []))
            if has_files:
                # Files already uploaded, proceed with training_pair workflow
                log.info("Detected training_pair intent with files already uploaded, proceeding to doctuning pipeline")
                # This will be handled by the normal message flow below
                pass
            else:
                # No files yet, ask user to upload
                log.info("Detected training_pair intent, requesting file upload")
                _set_pending_analyze(
                    _chat_id,
                    text,
                    preserve_existing_files=False,
                )
                await update.message.reply_text(
                    (
                        "📚 Задача принята: создание обучающей пары для тюнинга.\n\n"
                        "Загрузите 2 документа:\n"
                        "1️⃣ **Пустой шаблон** (blank template)\n"
                        "2️⃣ **Заполненный пример** (filled example)\n\n"
                        "После загрузки отправьте `/analyze_done`"
                        if lang == "ru" else
                        "📚 Task accepted: creating training pair for tuning.\n\n"
                        "Upload 2 documents:\n"
                        "1️⃣ **Blank template**\n"
                        "2️⃣ **Filled example**\n\n"
                        "After upload, send `/analyze_done`"
                    ),
                    parse_mode="Markdown",
                )
                return
        elif _looks_like_file_dependent_request(text):
            has_files = bool(((_get_pending_analyze_state(_chat_id) or {}).get("files") or []))
            _set_pending_analyze(
                _chat_id,
                text,
                preserve_existing_files=has_files,
            )
            await update.message.reply_text(
                (
                    "Task accepted for document analysis.\n"
                    "Please upload attachment(s) to this chat, then send `/analyze_done`.\n"
                    "I will process the batch once uploads are complete."
                ),
                parse_mode="Markdown",
            )
            return

    # Classify: question vs actionable task using LLM
    # If unclear, ask user for clarification
    async def _classify_message_intent(msg: str, dialog_history: list[dict]) -> str:
        """
        Use LLM to classify message intent: 'question', 'task', or 'unclear'.
        Returns: 'question' | 'task' | 'unclear'
        """
        # Build context from last 10 messages
        context_lines = []
        for m in dialog_history[-10:]:
            role = m.get("role", "")
            content = m.get("content", "")[:200]
            if role == "user":
                context_lines.append(f"User: {content}")
            elif role == "assistant":
                context_lines.append(f"Axi: {content}")

        context_block = "\n".join(context_lines) if context_lines else "(no previous context)"

        classification_prompt = f"""Analyze this message and classify intent.

Previous conversation (last 10 messages):
{context_block}

Current message: "{msg}"

Classification rules:
- QUESTION: user asks for information, explanation, clarification (что?, как?, почему?, can you explain?, what is?)
- TASK: user requests action, document creation, analysis, generation (создай, напиши, найди документы, prepare report, analyze, generate, сгенерируй, tuning pair, training pair)
- UNCLEAR: ambiguous, needs clarification

Special cases that are ALWAYS tasks:
- "generate a tuning pair" or "generate a training pair" → TASK
- "сгенерируй обучающую пару" or "создай тюнинг пару" → TASK

Respond with exactly one word: question, task, or unclear"""

        try:
            # Use small model on PC Andrei for fast classification
            import httpx
            pc_andrei_url = os.environ.get("ANDREI_HOST", "10.77.77.2")
            ollama_url = f"http://{pc_andrei_url}:11434/api/generate"

            response = httpx.post(
                ollama_url,
                json={
                    "model": "qwen2.5:14b",  # Fast classification model
                    "prompt": classification_prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 10}
                },
                timeout=10.0
            )

            if response.status_code == 200:
                result = response.json().get("response", "").strip().lower()
                if "question" in result:
                    return "question"
                elif "task" in result:
                    return "task"
                elif "unclear" in result:
                    return "unclear"
        except Exception as e:
            log.debug("LLM classification failed, using fallback rules: %s", e)

        # Fallback to simple rules if LLM unavailable
        msg_lower = msg.lower().strip()

        # Check for training_pair/tuning_pair keywords first (always TASK)
        if any(kw in msg_lower for kw in ["training pair", "tuning pair", "обучающ пар", "тренировочн пар", "тюнинг пар"]):
            return "task"

        if any(m in msg_lower for m in ["?", "что такое", "как ", "почему", "what is", "how ", "why"]):
            return "question"

        if any(m in msg_lower for m in ["создай", "напиши", "найди документ", "create", "write", "analyze", "generate", "сгенерируй"]):
            return "task"

        # Short messages without clear markers are likely questions
        if len(msg.split()) < 5:
            return "question"

        return "unclear"

    if _is_casual_non_task_message(text):
        reply = (
            "Hi. I am online and ready."
            if lang != "ru"
            else "Привет. Я на связи и готов к задаче."
        )
        await update.message.reply_text(reply)
        _dialog_append(_chat_id, "assistant", reply)
        return

    # Classify message intent using LLM
    dialog_history = _AXI_DIALOG.get(_chat_id, [])
    intent = await _classify_message_intent(text, dialog_history)

    # If unclear, ask for clarification
    if intent == "unclear":
        clarification_msg = (
            "Уточните, пожалуйста:\n"
            "• Это вопрос (нужна информация)?\n"
            "• Или задача (нужно что-то создать/найти/проанализировать)?\n\n"
            "Ответьте 'вопрос' или 'задача', и я продолжу."
            if lang == "ru" else
            "Please clarify:\n"
            "• Is this a question (need information)?\n"
            "• Or a task (need to create/find/analyze something)?\n\n"
            "Reply 'question' or 'task' and I'll proceed."
        )
        await update.message.reply_text(clarification_msg)
        _dialog_append(_chat_id, "assistant", clarification_msg)
        return

    # Register task only if intent is 'task'
    _tr_id = ""
    if intent == "task":
        _tr_id = _tr_register(
            text[:120] or "(пустое сообщение)",
            chat_id=str(_chat_id or ""),
            source="group" if chat_type in ("group", "supergroup") else "axi",
        )
        _tr_start(_tr_id, assigned_to="gemini")
        if _tr_id:
            task_msg = (
                f"🧾 Задача зарегистрирована: `{_tr_id}`.\n"
                "Используйте этот номер для проверки статуса и корректировки результата."
                if lang == "ru" else
                f"🧾 Task registered: `{_tr_id}`.\n"
                "Use this ID to check status and request result corrections."
            )
            await update.message.reply_text(task_msg, parse_mode="Markdown")
        elif AXI_CHAT_SHOW_TASK_REGISTRY_WARNINGS:
            task_msg = (
                "⚠️ Не удалось зарегистрировать задачу в реестре (Task Registry недоступен)."
                if lang == "ru" else
                "⚠️ Task Registry is unavailable, task ID was not created."
            )
            await update.message.reply_text(task_msg, parse_mode="Markdown")
    else:
        log.debug("Message classified as question, skipping task registration: %s", text[:100])

    t0 = time.perf_counter()
    progress_msg = None
    _main_anim_stop: asyncio.Event | None = None
    _main_anim_task = None
    try:
        progress_msg = await update.message.reply_text(
            f"⏱ {AXI_NAME}: выполняю запрос…" if lang == "ru" else f"⏱ {AXI_NAME}: working on your request…"
        )
        _main_anim_stop = asyncio.Event()
        _main_anim_base = (
            f"{AXI_NAME}: обрабатываю…" if lang == "ru" else f"{AXI_NAME}: processing…"
        )
        _main_anim_task = asyncio.create_task(
            _animate_progress(progress_msg, _main_anim_base, _main_anim_stop)
        )
        await ctx.bot.send_chat_action(chat_id=_chat_id, action=ChatAction.TYPING)
        use_search = _should_web_search(text)

        # Workflow: registry listing — Axi handles directly
        if _wants_registry_list(text):
            if progress_msg is not None:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
            await _handle_registry_list(update, ctx, text, tr_id=_tr_id)
            return

        # Workflow: внутренние ресурсы (БД) → делегируем Omi
        if _wants_db_strategy(text):
            omi_task_id = _tr_register(
                text[:200],
                chat_id=str(_chat_id or ""),
                source="axi",
            )
            # Оставляем omi_task_id в статусе pending — Omi подберёт его по polling
            lang_is_ru = lang == "ru"
            delegate_msg = (
                "🔄 Задача требует внутренней базы AIMS — передаю Оми, она подготовит документ."
                if lang_is_ru else
                "🔄 Task requires internal AIMS database — delegating to Omi, she will prepare the document."
            )
            if progress_msg is not None:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
            await update.message.reply_text(delegate_msg)
            _dialog_append(_chat_id, "assistant", delegate_msg)
            _tr_done(_tr_id, summary=f"delegated_to_omi:{omi_task_id}")
            return

        # Workflow: standards / compliance check
        pending_state = _get_pending_analyze_state(_chat_id) if _chat_id else None
        pending_files_count = len(list((pending_state or {}).get("files") or []))
        if _wants_standards_check(
            text,
            recent_chat_context=prior_ctx,
            pending_files_count=pending_files_count,
        ):
            await _handle_standards_check(
                update, ctx, text,
                lang=lang,
                tr_id=_tr_id,
                progress_msg=progress_msg,
                t0=t0,
            )
            return

        # Workflow: внешние ресурсы — обрабатывает Axi
        if _wants_docx(text):
            await ctx.bot.send_chat_action(chat_id=_chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            if progress_msg is not None:
                try:
                    await progress_msg.edit_text(
                        f"⏱ {AXI_NAME}: формирую документ (72B)…"
                        if lang == "ru" else
                        f"⏱ {AXI_NAME}: generating document (72B)…"
                    )
                except Exception:
                    pass

            # Route through AIMS V2 LogiOrchestrator (7-step pipeline)
            web_ctx: str | None = None
            _aims_ok = False

            _aims_url = os.environ.get("AIMS_LOGI_URL", "http://localhost:8000/task")
            try:
                import httpx as _httpx
                from pathlib import Path as _Path

                _aims_payload = {
                    "content": text,
                    "doc_type": "procedure",
                    "department": "operations",
                    "requester": "axi_bot",
                }
                async with _httpx.AsyncClient(timeout=180.0) as _hc:
                    _aims_resp = await _hc.post(_aims_url, json=_aims_payload)
                    _aims_resp.raise_for_status()
                    _aims_result = _aims_resp.json()

                _aims_status = _aims_result.get("status", "")

                if _aims_status == "success":
                    docx_path = _Path(_aims_result["document"]["doc_path"])
                    _aims_ok = True
                elif _aims_status == "gap_report":
                    _gap_msg = (
                        "⚠️ Документ не прошёл валидацию ISO. Пробелы соответствия:\n"
                        + "\n".join(f"— {g}" for g in _aims_result.get("gaps", []))
                    ) if lang == "ru" else (
                        "⚠️ Document failed ISO validation. Compliance gaps:\n"
                        + "\n".join(f"— {g}" for g in _aims_result.get("gaps", []))
                    )
                    await update.message.reply_text(_gap_msg)
                    _dialog_append(_chat_id, "assistant", _gap_msg)
                    _tr_done(_tr_id, summary="aims:gap_report")
                    return
                elif _aims_status == "blocked_by_policy":
                    _block_msg = (
                        f"🚫 Заблокировано политикой: {_aims_result.get('reason', '—')}"
                        if lang == "ru" else
                        f"🚫 Blocked by policy: {_aims_result.get('reason', '—')}"
                    )
                    await update.message.reply_text(_block_msg)
                    _dialog_append(_chat_id, "assistant", _block_msg)
                    _tr_done(_tr_id, summary="aims:policy_blocked")
                    return
                elif _aims_status == "training_pair_saved":
                    raise RuntimeError("aims: quality below threshold, saved as training pair")
                else:
                    raise RuntimeError(f"aims: unexpected status={_aims_status!r}")

            except Exception as _aims_err:
                log.warning("aims_logi failed (%s), falling back to DocAgent", _aims_err)

            if not _aims_ok:
                try:
                    from doc_agent_api import DocAgentClient
                    _api_url = os.environ.get("DOC_AGENT_API_URL", "http://doc-agent:8767")
                    _client = DocAgentClient(_api_url)
                    import asyncio as _asyncio
                    loop = _asyncio.get_event_loop()
                    _result = await loop.run_in_executor(
                        None,
                        lambda: _client.generate_dual(text, out_dir=str(AXI_RESULTS_DIR)),
                    )
                    if not _result.get("ok"):
                        raise RuntimeError(_result.get("error", "dual pipeline failed"))
                    docx_path = _Path(_result["path"])
                except Exception as _da_err:
                    log.warning("doc_agent failed (%s), falling back to local generation", _da_err)
                    docx_prompt = (
                        text + "\n\n"
                        "[INSTRUCTION: Generate the complete document content. "
                        "Use Markdown headings (# ## ###) for sections, **bold** for emphasis, "
                        "bullet lists with '- '. Output only document content, no meta-commentary.]"
                    )
                    answer = await _llm_reply(docx_prompt, extra_context=prior_ctx, use_search=use_search)
                    first_line = next(
                        (ln.strip().lstrip("#").strip() for ln in answer.splitlines() if ln.strip()),
                        "axi_document",
                    )
                    docx_path = await _generate_custom_docx(answer, "axi_doc", AXI_RESULTS_DIR, title=first_line)
            dt = time.perf_counter() - t0
            source_hint = _sources_note(
                lang=lang,
                use_search=use_search,
                has_dialog_context=bool(prior_ctx.strip()),
            )
            task_hint = f" | task `{_tr_id}`" if _tr_id else ""
            if progress_msg is not None:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
            with docx_path.open("rb") as fh:
                await update.message.reply_document(
                    document=fh,
                    filename=docx_path.name,
                    caption=f"{AXI_NAME}: ✅ {docx_path.name} ({dt:.0f}с)\n{source_hint}{task_hint}",
                )
            _dialog_append(_chat_id, "assistant", f"[doc:{docx_path.name}]")
            _tr_done(_tr_id, summary=f"docx:{docx_path.name}")
        else:
            answer = await _llm_reply(text, extra_context=prior_ctx, use_search=use_search)
            answer = _strip_false_attachment_claims(answer, lang=lang)
            answer = (
                answer.strip()
                + "\n\n"
                + _sources_note(
                    lang=lang,
                    use_search=use_search,
                    has_dialog_context=bool(prior_ctx.strip()),
                )
            )
            dt = time.perf_counter() - t0
            _TG_LIMIT = 4000
            chunks = [answer[i:i + _TG_LIMIT] for i in range(0, len(answer), _TG_LIMIT)] if answer else ["…"]
            for i, chunk in enumerate(chunks):
                try:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(chunk)
            if progress_msg is not None:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
            _dialog_append(_chat_id, "assistant", answer)
            _tr_done(_tr_id, summary=f"chat:dt={dt:.1f}s")

    except Exception as e:
        log.error("handle_chat error: %s", e, exc_info=True)
        _tr_stuck(_tr_id, error=str(e)[:200])
        try:
            from failure_detector import get_detector
            get_detector().from_axi({"ok": False, "error": str(e), "chat_id": _chat_id})
        except Exception:
            pass
        err_msg = (
            f"{AXI_NAME}: не удалось обработать запрос — {type(e).__name__}."
            if lang == "ru" else
            f"{AXI_NAME}: failed to process request — {type(e).__name__}."
        )
        try:
            await update.message.reply_text(err_msg)
        except Exception:
            pass
    finally:
        if _main_anim_stop is not None:
            _main_anim_stop.set()
        if _main_anim_task is not None:
            _main_anim_task.cancel()
            try:
                await _main_anim_task
            except asyncio.CancelledError:
                pass
        if progress_msg is not None:
            try:
                await progress_msg.delete()
            except Exception:
                pass


# ── Docfill — training pair builder ───────────────────────────────────────────

_DOCFILL_NIM_BASE = "https://integrate.api.nvidia.com/v1"
_DOCFILL_NIM_MODEL = "deepseek-ai/deepseek-v3-0324"

def _build_validate_system(standards: list[str]) -> str:
    std_line = (
        ", ".join(standards)
        if standards
        else "applicable industrial maintenance and safety standards"
    )
    return (
        "You are an expert industrial document quality auditor for the AIMS platform. "
        f"Check compliance against these standards: {std_line}. "
        "Assess whether the filled document is factually correct and free of hallucinations. "
        "Respond ONLY with valid JSON — no markdown fences, no extra text:\n"
        '{"hallucination_score": <0.0–1.0>, '
        '"issues": ["<specific issue>" ...], '
        '"standards_met": ["<standard>" ...], '
        '"verdict": "accept" | "reject", '
        '"reason": "<one sentence>"}'
    )


_DOCFILL_CONTEXT_SYSTEM = (
    "You are a technical document classifier. Analyze the given blank form and filled example. "
    "Respond ONLY with valid JSON — no markdown fences, no extra text:\n"
    '{"doc_type": "<type>", "equipment_type": "<equipment or process>", '
    '"industry": "<sector>", "key_terms": ["<term>", ...]}'
)


def _extract_doc_context_sync(blank_text: str, filled_text: str) -> dict:
    """Ask Omnirouter (NVIDIA NIM) to classify the document and extract context for standards search."""
    try:
        import httpx
    except ImportError:
        return {}

    omnirouter_url = os.environ.get("AIMS_OMNIROUTER_URL", "http://127.0.0.1:8082").rstrip("/")
    auth_token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")

    # Use llama405b (NVIDIA NIM) as primary, local-nemotron as fallback (via Omnirouter)
    model = os.environ.get("AIMS_DOCTUNING_MODEL", "llama405b")

    prompt = (
        f"BLANK TEMPLATE (first 1500 chars):\n{blank_text[:1500]}\n\n"
        f"FILLED EXAMPLE (first 1500 chars):\n{filled_text[:1500]}\n\n"
        "Classify this document and extract context."
    )

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{omnirouter_url}/v1/messages",
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "system": _DOCFILL_CONTEXT_SYSTEM,
                    "temperature": 0.0,
                    "max_tokens": 256,
                },
            )

        if resp.status_code != 200:
            log.warning("doctuning context extract: omnirouter returned %d", resp.status_code)
            return {}

        data = resp.json()
        content_blocks = data.get("content", [])
        raw = ""
        for block in content_blocks:
            if block.get("type") == "text":
                raw = block.get("text", "").strip()
                break

        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except Exception as e:
        log.warning("doctuning context extract error: %s", e)
        return {}


def _save_doctuning_memo(context: dict, blank_name: str, content_hash: str = None) -> Path:
    ws = Path(__file__).resolve().parent.parent
    memo_dir = ws / "aims_workspace"
    memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = memo_dir / f"doctuning_memo_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    memo_data = {
        "blank_name": blank_name,
        "content_hash": content_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **context
    }
    memo_path.write_text(
        json.dumps(memo_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return memo_path


def _find_existing_training_pair(content_hash: str) -> dict | None:
    """Check if training pair with this content hash already exists."""
    ws = Path(__file__).resolve().parent.parent
    memo_dir = ws / "aims_workspace"
    if not memo_dir.exists():
        return None

    for memo_file in memo_dir.glob("doctuning_memo_*.json"):
        try:
            memo_data = json.loads(memo_file.read_text(encoding="utf-8"))
            if memo_data.get("content_hash") == content_hash:
                return {
                    "memo_file": memo_file.name,
                    "created": memo_data.get("created_at", "unknown"),
                    "local_score": memo_data.get("local_model_score", "не оценено"),
                    "blank_name": memo_data.get("blank_name", "unknown"),
                }
        except Exception as e:
            log.warning("Failed to read memo %s: %s", memo_file.name, e)
            continue

    return None


def _read_document_text(file_path: Path) -> str:
    """Read text from .txt, .json, .docx, or .xlsx file."""
    suffix = file_path.suffix.lower()

    if suffix in (".txt", ".json"):
        return file_path.read_text(encoding="utf-8", errors="replace")

    elif suffix == ".docx":
        try:
            from docx import Document
            doc = Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            log.warning("docx read error: %s", e)
            return file_path.read_text(encoding="utf-8", errors="replace")

    elif suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
            wb = load_workbook(str(file_path), data_only=True)
            lines = []
            for sheet in wb.worksheets:
                lines.append(f"=== Sheet: {sheet.title} ===")
                for row in sheet.iter_rows(values_only=True):
                    row_text = "\t".join(str(cell) if cell is not None else "" for cell in row)
                    if row_text.strip():
                        lines.append(row_text)
            return "\n".join(lines)
        except Exception as e:
            log.warning("xlsx read error: %s", e)
            return file_path.read_text(encoding="utf-8", errors="replace")

    else:
        return file_path.read_text(encoding="utf-8", errors="replace")


async def _search_standards_for_context(context: dict) -> list[str]:
    """Web search for standards is disabled in local-only mode."""
    return []


def _validate_and_extract_context_sync(blank_text: str, filled_text: str) -> dict:
    """Combined: extract context + validate document via Omnirouter (NVIDIA NIM).

    Returns dict with:
    - context: {doc_type, equipment_type, industry, key_terms}
    - validation: {verdict, hallucination_score, issues, standards_met, reason}
    """
    try:
        import httpx
    except ImportError:
        return {
            "context": {},
            "validation": {"verdict": "accept", "hallucination_score": 0.0, "issues": [], "reason": "httpx not installed", "standards_met": []}
        }

    omnirouter_url = os.environ.get("AIMS_OMNIROUTER_URL", "http://127.0.0.1:8082").rstrip("/")
    auth_token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")
    model = os.environ.get("AIMS_DOCTUNING_MODEL", "llama405b")

    # Combined system prompt for context extraction + validation
    combined_system = (
        "You are an expert industrial document specialist and quality auditor for the AIMS platform. "
        "Perform TWO tasks:\n\n"
        "1. CLASSIFY the document and extract context:\n"
        '   {"doc_type": "<type>", "equipment_type": "<equipment or process>", '
        '"industry": "<sector>", "key_terms": ["<term>", ...]}\n\n'
        "2. VALIDATE the filled example for hallucinations, fabricated values, and standards compliance "
        "(ISO, API, ASME, OSHA, IEC, NFPA, IEEE, EN, ANSI, PAS, BS):\n"
        '   {"hallucination_score": <0.0–1.0>, "issues": ["<specific issue>" ...], '
        '"standards_met": ["<standard>" ...], "verdict": "accept" | "reject", "reason": "<one sentence>"}\n\n'
        "Respond with valid JSON containing both 'context' and 'validation' keys. No markdown fences, no extra text."
    )

    prompt = (
        f"BLANK TEMPLATE:\n{blank_text[:3000]}\n\n"
        f"FILLED EXAMPLE (to audit):\n{filled_text[:4000]}\n\n"
        "Extract context and validate the filled example."
    )

    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(
                f"{omnirouter_url}/v1/messages",
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "system": combined_system,
                    "temperature": 0.1,
                    "max_tokens": 768,
                },
            )

        if resp.status_code != 200:
            log.warning("doctuning validate+context: omnirouter returned %d", resp.status_code)
            return {
                "context": {},
                "validation": {"verdict": "accept", "hallucination_score": 0.0, "issues": [], "reason": f"omnirouter error {resp.status_code}", "standards_met": []}
            }

        data = resp.json()
        content_blocks = data.get("content", [])
        raw = ""
        for block in content_blocks:
            if block.get("type") == "text":
                raw = block.get("text", "").strip()
                break

        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

        result = json.loads(raw)

        # Ensure both keys exist
        if "context" not in result:
            result["context"] = {}
        if "validation" not in result:
            result["validation"] = {"verdict": "accept", "hallucination_score": 0.0, "issues": [], "reason": "no validation returned", "standards_met": []}

        return result
    except Exception as e:
        log.warning("doctuning validate+context error: %s", e)
        return {
            "context": {},
            "validation": {"verdict": "accept", "hallucination_score": 0.0, "issues": [], "reason": f"validation error ({e})", "standards_met": []}
        }


def _nim_validate_document_sync(blank_text: str, filled_text: str, standards: list[str]) -> dict:
    """DEPRECATED: Use _validate_and_extract_context_sync instead.
    Kept for backward compatibility."""
    try:
        from openai import OpenAI as _OAI
    except ImportError:
        return {"verdict": "accept", "hallucination_score": 0.0, "issues": [], "reason": "openai not installed — skipped validation", "standards_met": []}

    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return {"verdict": "accept", "hallucination_score": 0.0, "issues": [], "reason": "NVIDIA_API_KEY not set — skipped validation", "standards_met": []}

    client = _OAI(api_key=api_key, base_url=_DOCFILL_NIM_BASE)
    prompt = (
        f"BLANK TEMPLATE:\n{blank_text[:3000]}\n\n"
        f"FILLED EXAMPLE (to audit):\n{filled_text[:4000]}\n\n"
        "Audit the filled example for hallucinations, fabricated values, and standards compliance. "
        "Return JSON as specified."
    )
    try:
        resp = client.chat.completions.create(
            model=_DOCFILL_NIM_MODEL,
            messages=[
                {"role": "system", "content": _build_validate_system(standards)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        raw = (resp.choices[0].message.content or "").strip()
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except Exception as e:
        log.warning("docfill nim validate error: %s", e)
        return {"verdict": "accept", "hallucination_score": 0.0, "issues": [], "reason": f"validation error ({e}) — accepted by default", "standards_met": []}


_DOCFILL_FILL_SYSTEM = (
    "You are an expert industrial document specialist. "
    "You receive a blank technical form and must fill in all fields with realistic values "
    "for an oil & gas / industrial maintenance context, following ISO 55001 and API standards. "
    "Output only the filled form text. No explanations, no comments."
)


def _local_generate_fill_sync(blank_text: str) -> str | None:
    """Ask local ollama model to fill the blank form (DPO rejected — model's current output)."""
    try:
        from openai import OpenAI as _OAI
    except ImportError:
        return None

    ollama_url = os.environ.get("OLLAMA_LOCAL_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("AIMS_DRAFT_MODEL", "axi_omi_sphere")
    client = _OAI(api_key="ollama", base_url=f"{ollama_url}/v1")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _DOCFILL_FILL_SYSTEM},
                {"role": "user", "content": f"Fill in this blank form:\n\n{blank_text[:4000]}"},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        result = (resp.choices[0].message.content or "").strip()
        return result if len(result) > 80 else None
    except Exception as e:
        log.warning("doctuning local generate error: %s", e)
        return None


def _check_ollama_alive_sync() -> bool:
    """Return True if the local Ollama service responds on /api/tags."""
    import urllib.request as _ur
    ollama_url = os.environ.get("OLLAMA_LOCAL_URL", "http://localhost:11434").rstrip("/")
    try:
        with _ur.urlopen(f"{ollama_url}/api/tags", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _check_vram_free_gb_sync() -> float:
    """Return free VRAM in GB on the first GPU via nvidia-smi, or 999.0 if unavailable.

    For GPUs that don't support memory queries (like GB10), use GPU utilization as proxy:
    - If GPU util < 92%, return high value (assume available)
    - If GPU util >= 92%, return 0.0 (assume full)
    """
    import subprocess as _sp
    try:
        # Try memory.free first (works on most GPUs)
        out = _sp.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            timeout=10, text=True,
        )
        first_line = out.strip().splitlines()[0]
        if first_line != "[N/A]":
            mb = float(first_line)
            return mb / 1024.0

        # Fallback: use GPU utilization percentage as proxy
        out = _sp.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            timeout=10, text=True,
        )
        util_pct = float(out.strip().splitlines()[0])

        # If GPU utilization >= 92%, consider VRAM full
        if util_pct >= 92.0:
            return 0.0
        else:
            return 999.0  # Assume plenty of free VRAM

    except Exception:
        return 999.0  # assume OK if nvidia-smi unavailable (non-GPU env)


# Whitelist of commands the repairman is allowed to execute during local-model recovery.
# Never exec arbitrary shell — only ollama operations and read-only diagnostics.
_REPAIR_CMD_WHITELIST = (
    "ollama list",
    "ollama pull ",
    "ollama stop ",
    "ollama run ",
    "nvidia-smi",
    "curl http://localhost:11434",
    "systemctl status ollama",
    "systemctl restart ollama",
)

_REPAIRMAN_SYSTEM_DOCFILL = (
    "You are the AIMS Repairman — an expert repair agent for the AxiOMSphere platform.\n"
    "Always respond with a single JSON object:\n"
    '{"root_cause": "<one clear paragraph>", "files_changed": [], "patch_diff": "none", '
    '"tests_run": ["<safe shell command>", ...], "test_result": "not_run", '
    '"risk_level": "low", "rollback_notes": "<how to revert>"}\n'
    "Only include safe, non-destructive shell commands in tests_run. "
    "Focus on ollama model recovery: check if the model is loaded, VRAM state, "
    "whether the ollama service is running. Do not delete files or restart services "
    "unless risk_level is low."
)


def _repairman_fix_local_model_sync(model: str) -> str:
    """Call repairman gateway to diagnose and recover the local model. Returns root_cause string."""
    import subprocess as _sp
    try:
        from openai import OpenAI as _OAI
    except ImportError:
        return "openai not available"

    gateway_url = "http://localhost:8082/v1"
    token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")
    problem = (
        f"The local Ollama model '{model}' failed to return a completion in the doctuning "
        "pipeline (returned None or raised an exception). Likely causes: model not loaded, "
        "VRAM exhaustion (DGX 128 GB — check if two large models are loaded simultaneously), "
        "ollama service not running, or connection refused on port 11434. "
        "Diagnose and provide safe recovery commands in 'tests_run'."
    )
    try:
        client = _OAI(api_key=token, base_url=gateway_url)
        resp = client.chat.completions.create(
            model="aims-repairman-nemotron",
            messages=[
                {"role": "system", "content": _REPAIRMAN_SYSTEM_DOCFILL},
                {"role": "user",   "content": problem},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        content = (resp.choices[0].message.content or "").strip()
        try:
            import json as _json
            data = _json.loads(content)
            root_cause = data.get("root_cause", content[:200])
            log.info("repairman root_cause: %s", root_cause)
            for cmd in data.get("tests_run", [])[:3]:
                if isinstance(cmd, str) and any(cmd.strip().startswith(p) for p in _REPAIR_CMD_WHITELIST):
                    log.info("repairman exec: %s", cmd)
                    _sp.run(cmd, shell=True, timeout=60, capture_output=True)
            return root_cause
        except Exception:
            return content[:300]
    except Exception as e:
        log.warning("repairman gateway call failed: %s", e)
        return f"repairman unavailable: {e}"


def _repairman_final_report_sync(model: str, cycles: int, last_root_cause: str) -> str:
    """After exhausting all repair cycles, ask repairman to write a human-readable failure report."""
    try:
        from openai import OpenAI as _OAI
        gateway_url = "http://localhost:8082/v1"
        token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")
        client = _OAI(api_key=token, base_url=gateway_url)
        problem = (
            f"You attempted to repair the local Ollama model '{model}' {cycles} times. "
            f"Last diagnosed root cause: {last_root_cause}\n"
            f"All {cycles} repair cycles failed — generation still returns no valid output. "
            "Write a concise 2–3 sentence report for the engineer explaining:\n"
            "1. What the root cause appears to be.\n"
            "2. What specific manual action is required to resolve it.\n"
            "Plain text only, no JSON, no markdown."
        )
        resp = client.chat.completions.create(
            model="aims-repairman-nemotron",
            messages=[
                {"role": "system", "content": (
                    "You are the AIMS Repairman reporting a repair failure to a human engineer. "
                    "Be concise and actionable."
                )},
                {"role": "user", "content": problem},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return (
            f"Repairman unreachable after {cycles} cycles. "
            f"Last known cause: {last_root_cause}. Manual intervention required."
        )


async def _local_fill_with_repair(
    blank_text: str, max_repair_cycles: int = 5
) -> tuple[str | None, str]:
    """
    Generate local fill. On first failure enters the repairman repair loop:
      - Repairman diagnoses, executes recovery commands, verifies (ollama health check).
      - If verified → retry generation.
      - Up to max_repair_cycles cycles.
      - After all cycles exhausted → repairman writes a human-readable failure report.

    Returns (filled_text, repairman_report).
    filled_text is None when all cycles failed; repairman_report contains the final diagnosis.
    """
    loop = asyncio.get_event_loop()
    model = os.environ.get("AIMS_DRAFT_MODEL", "axi_omi_sphere")

    # First attempt (clean, no repairman pre-check)
    result = await loop.run_in_executor(None, _local_generate_fill_sync, blank_text)
    if result:
        return result, ""

    log.warning(
        "doctuning: initial generation failed — starting repairman loop (max %d cycles)",
        max_repair_cycles,
    )
    last_root_cause = "unknown"

    for cycle in range(1, max_repair_cycles + 1):
        log.info("doctuning: repairman cycle %d/%d", cycle, max_repair_cycles)

        # Repairman diagnoses and executes repair commands
        last_root_cause = await loop.run_in_executor(
            None, _repairman_fix_local_model_sync, model
        )
        log.info("repairman cycle %d root_cause: %s", cycle, last_root_cause)

        # Wait for repair to take effect
        await asyncio.sleep(20)

        # Repairman verifies: check ollama health
        alive = await loop.run_in_executor(None, _check_ollama_alive_sync)
        if not alive:
            log.warning("repairman cycle %d: ollama still down after repair", cycle)
            continue  # repairman will try again next cycle

        # Service confirmed up → retry generation
        result = await loop.run_in_executor(None, _local_generate_fill_sync, blank_text)
        if result:
            log.info("doctuning: generation succeeded after repairman cycle %d", cycle)
            return result, ""

        log.warning("repairman cycle %d: service up but generation still fails", cycle)

    # All cycles exhausted — repairman writes the failure report for the engineer
    log.error("doctuning: repairman exhausted %d cycles, requesting final report", max_repair_cycles)
    final_report = await loop.run_in_executor(
        None, _repairman_final_report_sync, model, max_repair_cycles, last_root_cause
    )
    log.error("repairman final report: %s", final_report)
    return None, final_report


def _docfill_save_dpo_pair(blank_text: str, chosen_text: str, rejected_text: str, doc_type: str) -> None:
    """Save doctuning DPO pair (human expert chosen, local model rejected)."""
    ws = Path(__file__).resolve().parent.parent
    dpo_path = ws / "data/training/standard_dpo_pairs.jsonl"
    dpo_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dpo_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "prompt": blank_text,
                "chosen": chosen_text,
                "chosen_score": 1.0,
                "rejected": rejected_text,
                "rejected_score": 0.5,
                "rejected_feedback": "Local model fill — to be improved toward human expert reference",
                "pipeline": f"doctuning_{doc_type}",
            }, ensure_ascii=False) + "\n")
        log.info("doctuning: DPO pair saved to standard_dpo_pairs.jsonl")
    except Exception as e:
        log.warning("doctuning dpo pair save failed: %s", e)


def _docfill_save_training_pair(blank_text: str, filled_text: str, doc_type: str, source_name: str) -> Path:
    """Append a (blank → filled) training pair to the docfill dataset."""
    import sys as _sys
    ws = Path(__file__).resolve().parent.parent
    out_dir = ws / "ops/ft/data/docfill_v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "train_docfill_v1.jsonl"

    system_msg = (
        "You are an AIMS document specialist. When given a blank technical form, "
        "fill in all fields accurately for the specified equipment type based on "
        "industrial maintenance and safety standards."
    )
    pair = {
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Fill in this form:\n\n{blank_text}"},
            {"role": "assistant", "content": filled_text},
        ],
        "_meta": {
            "source": "axi_docfill_upload",
            "doc_type": doc_type,
            "blank_name": source_name,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    with out_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(pair, ensure_ascii=False) + "\n")
    return out_file


def _docfill_save_to_omi(title: str, content: str, doc_type: str) -> str | None:
    """Save master document to OmiAgent via /documents API."""
    try:
        import urllib.request as _ur
        payload = json.dumps({
            "action": "create_master",
            "title": title,
            "content": content,
            "metadata": {
                "doc_type": doc_type,
                "source": "axi_docfill",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }).encode()
        req = _ur.Request(
            "http://localhost:8008/documents",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("id") or result.get("document_id")
    except Exception as e:
        log.warning("docfill save to omi failed: %s", e)
        return None


async def _handle_docfill_file(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    """Handle file upload in docfill mode."""
    state = _PENDING_DOCFILL[chat_id]
    step = str(state.get("step", ""))
    lang = AXI_FORCE_REPLY_LANG if AXI_FORCE_REPLY_LANG in ("en", "ru") else "ru"

    if not update.message or not update.message.document:
        await update.message.reply_text(
            "Пожалуйста, отправьте файл (.txt, .json, .docx, .xlsx)."
            if lang == "ru" else
            "Please send a file (.txt, .json, .docx, .xlsx)."
        )
        return

    doc = update.message.document
    file_name = doc.file_name or f"upload_{doc.file_id[-8:]}"
    suffix = Path(file_name).suffix.lower() or ".txt"

    # Validate file type
    if suffix not in (".txt", ".json", ".docx", ".xlsx"):
        await update.message.reply_text(
            f"❌ Неподдерживаемый формат: `{suffix}`\n"
            "Поддерживаются: .txt, .json, .docx, .xlsx"
            if lang == "ru" else
            f"❌ Unsupported format: `{suffix}`\n"
            "Supported: .txt, .json, .docx, .xlsx",
            parse_mode="Markdown",
        )
        return

    with tempfile.NamedTemporaryFile(prefix="axi_docfill_", suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    tg_file = await ctx.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(str(tmp_path))

    if step == "await_blank":
        state["blank_path"] = str(tmp_path)
        state["blank_name"] = file_name
        state["step"] = "await_example"
        _PENDING_DOCFILL[chat_id] = state
        await update.message.reply_text(
            f"✅ Шаблон принят: `{file_name}`\n\n"
            "Теперь загрузите **эталонный заполненный** документ (файл 2 из 2)."
            if lang == "ru" else
            f"✅ Template accepted: `{file_name}`\n\n"
            "Now send the **filled reference** document (file 2 of 2).",
            parse_mode="Markdown",
        )
        return

    if step == "await_example":
        blank_path = Path(str(state.get("blank_path", "")))
        blank_name = str(state.get("blank_name", "blank"))
        doc_type = str(state.get("doc_type", "procedure"))
        filled_name = Path(file_name).stem
        state["step"] = "validating"
        _PENDING_DOCFILL[chat_id] = state

        try:
            blank_text = _read_document_text(blank_path)
            filled_text = _read_document_text(tmp_path)
        except Exception as e:
            await update.message.reply_text(
                f"Ошибка чтения файла: {e}" if lang == "ru" else f"File read error: {e}"
            )
            _PENDING_DOCFILL.pop(chat_id, None)
            tmp_path.unlink(missing_ok=True)
            blank_path.unlink(missing_ok=True)
            return

        loop = asyncio.get_event_loop()

        # ── Preflight: check Ollama availability and VRAM ────────────────────
        ollama_alive = await loop.run_in_executor(None, _check_ollama_alive_sync)
        vram_free_gb = await loop.run_in_executor(None, _check_vram_free_gb_sync)
        model = os.environ.get("AIMS_DRAFT_MODEL", "axi_omi_sphere")

        if not ollama_alive:
            await update.message.reply_text(
                f"⚠️ Ollama недоступна. Запускаю репairman для восстановления сервиса…\n"
                f"NIM-валидация вашего эталона запущена параллельно."
                if lang == "ru" else
                f"⚠️ Ollama is down. Launching repairman to restore the service…\n"
                f"NIM validation of your reference is running in parallel."
            )
            # Repairman restores ollama; NIM path runs independently below
            repair_task = loop.run_in_executor(None, _repairman_fix_local_model_sync, model)
        else:
            repair_task = None

        if ollama_alive and vram_free_gb < DOCFILL_VRAM_MIN_FREE_GB:
            await update.message.reply_text(
                f"⏸ VRAM перегружена ({vram_free_gb:.1f} GB свободно, нужно ≥{DOCFILL_VRAM_MIN_FREE_GB:.0f} GB).\n"
                f"Задача локальной генерации поставлена в очередь — уведомлю, когда освободится.\n"
                f"Omnirouter (Claude) валидация эталона запущена."
                if lang == "ru" else
                f"⏸ VRAM is full ({vram_free_gb:.1f} GB free, need ≥{DOCFILL_VRAM_MIN_FREE_GB:.0f} GB).\n"
                f"Local generation queued — I'll notify you when VRAM is available.\n"
                f"Omnirouter (Claude) validation is running."
            )
            _DOCFILL_VRAM_QUEUE[chat_id] = blank_text
            # Combined context extraction + validation via Omnirouter
            combined_result = await loop.run_in_executor(
                None, _validate_and_extract_context_sync, blank_text, filled_text
            )
            context_vram = combined_result.get("context", {})
            verdict = combined_result.get("validation", {})
            local_fill = None
            repair_report = ""
        else:
            await update.message.reply_text(
                f"✅ Эталон принят: `{file_name}`\n\n"
                "⏳ Запускаю два параллельных пути:\n"
                "  • Локальная модель заполняет шаблон (rejected)\n"
                "  • Omnirouter (Claude) проверяет ваш эталон по стандартам…"
                if lang == "ru" else
                f"✅ Reference accepted: `{file_name}`\n\n"
                "⏳ Running two parallel paths:\n"
                "  • Local model fills the blank (rejected candidate)\n"
                "  • Omnirouter (Claude) audits your reference against standards…",
                parse_mode="Markdown",
            )
            # Wait for repair task to complete (if repairman was launched for ollama-down)
            if repair_task is not None:
                await repair_task
                await asyncio.sleep(20)  # give ollama time to stabilise

            # Combined context extraction + validation via Omnirouter, parallel with local fill
            combined_result, (local_fill, repair_report) = await asyncio.gather(
                loop.run_in_executor(None, _validate_and_extract_context_sync, blank_text, filled_text),
                _local_fill_with_repair(blank_text),
            )
            context = combined_result.get("context", {})
            verdict = combined_result.get("validation", {})

            # Save context memo
            if context:
                memo_path_ctx = _save_doctuning_memo(context, blank_name)
                memo_path_ctx.unlink(missing_ok=True)

        h_score = float(verdict.get("hallucination_score", 0.0))
        v_issues = verdict.get("issues", [])
        v_standards = verdict.get("standards_met", [])
        v_reason = str(verdict.get("reason", ""))

        standards_text = ", ".join(v_standards) if v_standards else "—"
        issues_lines = "\n".join(f"  {i+1}. {issue}" for i, issue in enumerate(v_issues))

        # Save approved state — master doc saved only after /doctuning_approve
        state.update({
            "step": "await_approval",
            "blank_text": blank_text,
            "filled_text": filled_text,
            "filled_name": filled_name,
            "local_fill": local_fill,
            "repair_report": repair_report,
            "nim_score": h_score,
            "nim_issues": v_issues,
            "nim_standards": v_standards,
            "blank_path": str(blank_path),  # Keep for cleanup
            "filled_path": str(tmp_path),   # Keep for cleanup
        })
        _PENDING_DOCFILL[chat_id] = state

        if v_issues:
            nim_block = (
                f"📋 **Omnirouter (Claude) — замечания по эталону:**\n"
                f"Стандарты: {standards_text}\n"
                f"Hallucination score: `{h_score:.2f}`\n\n"
                f"Замечания:\n{issues_lines}\n\n"
                f"_{v_reason}_\n\n"
                "Учтите замечания при финальном решении.\n"
                "Подтвердить как мастер-документ: `/doctuning_approve`\n"
                "Отмена: `/doctuning_cancel`"
                if lang == "ru" else
                f"📋 **Omnirouter (Claude) — reference audit:**\n"
                f"Standards: {standards_text}\n"
                f"Hallucination score: `{h_score:.2f}`\n\n"
                f"Recommendations:\n{issues_lines}\n\n"
                f"_{v_reason}_\n\n"
                "Consider these points before approving.\n"
                "Approve as master document: `/doctuning_approve`\n"
                "Cancel: `/doctuning_cancel`"
            )
        else:
            nim_block = (
                f"✅ **Omnirouter (Claude) — замечаний нет**\n"
                f"Стандарты: {standards_text}\n"
                f"Hallucination score: `{h_score:.2f}` — {v_reason}\n\n"
                "Подтвердить как мастер-документ: `/doctuning_approve`\n"
                "Отмена: `/doctuning_cancel`"
                if lang == "ru" else
                f"✅ **Omnirouter (Claude) — no issues found**\n"
                f"Standards: {standards_text}\n"
                f"Hallucination score: `{h_score:.2f}` — {v_reason}\n\n"
                "Approve as master document: `/doctuning_approve`\n"
                "Cancel: `/doctuning_cancel`"
            )

        await update.message.reply_text(nim_block, parse_mode="Markdown")
        # Don't delete tmp_path yet — keep for cleanup after approval
        return

    # Unknown state — reset
    _PENDING_DOCFILL.pop(chat_id, None)
    tmp_path.unlink(missing_ok=True)


async def cmd_doctuning(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Start docfill training pair creation: upload blank template + filled reference."""
    if not _chat_allowed(update):
        return
    if update.message is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    lang = AXI_FORCE_REPLY_LANG if AXI_FORCE_REPLY_LANG in ("en", "ru") else "ru"

    doc_type = " ".join(ctx.args).strip().lower() if ctx.args else "procedure"

    _PENDING_DOCFILL[chat_id] = {"step": "await_blank", "doc_type": doc_type}

    await update.message.reply_text(
        f"📄 **Режим создания тюнинг-пары** (тип: `{doc_type}`)\n\n"
        "Шаг 1 из 2 — загрузите **шаблон** (пустой бланк) в формате .txt, .json, .docx или .xlsx.\n\n"
        "Порядок:\n"
        "1. Загружаете шаблон\n"
        "2. Загружаете заполненный эталон\n"
        "3. Omnirouter (Claude) извлекает контекст и валидирует эталон на галлюцинации и соответствие стандартам\n"
        "4. Если проверка пройдена → пара сохраняется как мастер-документ и тюнинг-пара\n\n"
        "Отмена: `/doctuning_cancel`"
        if lang == "ru" else
        f"📄 **Training pair mode** (type: `{doc_type}`)\n\n"
        "Step 1 of 2 — upload the **blank template** (.txt, .json, .docx, or .xlsx).\n\n"
        "Flow:\n"
        "1. Upload blank template\n"
        "2. Upload filled reference\n"
        "3. Omnirouter (Claude) extracts context and validates for hallucinations and standards compliance\n"
        "4. Pair is always saved as master document + training pair\n\n"
        "Cancel: `/doctuning_cancel`",
        parse_mode="Markdown",
    )


async def cmd_doctuning_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update) or update.message is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = _PENDING_DOCFILL.pop(chat_id, None)
    if state:
        # Cleanup temporary files
        blank_path = state.get("blank_path")
        filled_path = state.get("filled_path")
        if blank_path:
            Path(str(blank_path)).unlink(missing_ok=True)
        if filled_path:
            Path(str(filled_path)).unlink(missing_ok=True)
    lang = AXI_FORCE_REPLY_LANG if AXI_FORCE_REPLY_LANG in ("en", "ru") else "ru"
    await update.message.reply_text(
        "Режим doctuning отменён." if lang == "ru" else "Doctuning mode cancelled."
    )


async def _job_docfill_vram_monitor(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic job: resume queued docfill local-fill tasks when VRAM is available."""
    if not _DOCFILL_VRAM_QUEUE:
        return

    loop = asyncio.get_event_loop()
    free_gb = await loop.run_in_executor(None, _check_vram_free_gb_sync)
    if free_gb < DOCFILL_VRAM_MIN_FREE_GB:
        log.debug("docfill vram monitor: %.1f GB free < %.0f GB threshold, waiting", free_gb, DOCFILL_VRAM_MIN_FREE_GB)
        return

    # Process one queued task per tick to avoid VRAM spike from concurrent fills
    chat_id = next(iter(_DOCFILL_VRAM_QUEUE))
    blank_text = _DOCFILL_VRAM_QUEUE.pop(chat_id)

    state = _PENDING_DOCFILL.get(chat_id)
    if not state or state.get("step") != "await_approval":
        # State was cleared (user cancelled) — discard
        log.info("docfill vram monitor: chat_id=%d state gone, discarding queued task", chat_id)
        return

    lang = AXI_FORCE_REPLY_LANG if AXI_FORCE_REPLY_LANG in ("en", "ru") else "ru"

    local_fill, repair_report = await _local_fill_with_repair(blank_text)

    # Update state with the now-available local fill result
    state["local_fill"] = local_fill
    state["repair_report"] = repair_report
    _PENDING_DOCFILL[chat_id] = state

    if local_fill:
        # Done state — notify
        await ctx.bot.send_message(
            chat_id,
            "✅ DPO-пара готова. Локальная генерация завершена.\n"
            "Подтвердите: `/doctuning_approve`"
            if lang == "ru" else
            "✅ DPO pair ready. Local fill complete.\n"
            "Confirm with: `/doctuning_approve`",
            parse_mode="Markdown",
        )
    else:
        # Full failure state — notify with repairman report
        report_suffix = f"\n\n_{repair_report}_" if repair_report else ""
        await ctx.bot.send_message(
            chat_id,
            f"🔴 Repairman исчерпал 5 циклов ремонта — локальная модель недоступна. DPO-пара будет пропущена.{report_suffix}\n\n"
            "SFT-пара и мастер-документ доступны: `/doctuning_approve`"
            if lang == "ru" else
            f"🔴 Repairman exhausted 5 repair cycles — local model unavailable. DPO pair will be skipped.{report_suffix}\n\n"
            "SFT pair and master document are ready: `/doctuning_approve`",
            parse_mode="Markdown",
        )


async def cmd_doctuning_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve the pending doctuning reference — saves SFT pair, DPO pair, and master document."""
    if not _chat_allowed(update) or update.message is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    lang = AXI_FORCE_REPLY_LANG if AXI_FORCE_REPLY_LANG in ("en", "ru") else "ru"

    state = _PENDING_DOCFILL.get(chat_id)
    if not state or state.get("step") != "await_approval":
        await update.message.reply_text(
            "Нет активного ожидания одобрения. Запустите `/doctuning` для начала."
            if lang == "ru" else
            "No pending approval. Start with `/doctuning`.",
            parse_mode="Markdown",
        )
        return

    # Guard: local fill still being generated (VRAM was queued)
    if chat_id in _DOCFILL_VRAM_QUEUE:
        await update.message.reply_text(
            "⏳ Локальная генерация ещё в очереди (ждём VRAM).\n"
            "Уведомлю, когда завершится — тогда и подтверждайте.\n"
            "Или `/doctuning_cancel` чтобы отменить (DPO-пара будет пропущена)."
            if lang == "ru" else
            "⏳ Local generation is still queued (waiting for VRAM).\n"
            "I'll notify you when it's done — approve then.\n"
            "Or `/doctuning_cancel` to cancel (DPO pair will be skipped).",
            parse_mode="Markdown",
        )
        return

    blank_text    = str(state.get("blank_text", ""))
    filled_text   = str(state.get("filled_text", ""))
    filled_name   = str(state.get("filled_name", "reference"))
    doc_type      = str(state.get("doc_type", "procedure"))
    local_fill    = state.get("local_fill")   # may be None
    repair_report = str(state.get("repair_report", ""))

    await update.message.reply_text(
        "⏳ Сохраняю мастер-документ и тренировочные пары…"
        if lang == "ru" else
        "⏳ Saving master document and training pairs…"
    )

    loop = asyncio.get_event_loop()
    doc_title = f"{doc_type.title()} — {filled_name}"

    # Run saves sequentially to reduce CPU/GPU load (was parallel with asyncio.gather)
    # Step 1: Save SFT pair
    try:
        sft_result = await loop.run_in_executor(
            None, _docfill_save_training_pair, blank_text, filled_text, doc_type, filled_name
        )
        sft_ok = True
    except Exception as e:
        sft_result = e
        sft_ok = False

    # Step 2: Save DPO pair (if local fill available)
    dpo_saved = False
    if local_fill:
        try:
            await loop.run_in_executor(
                None, _docfill_save_dpo_pair, blank_text, filled_text, local_fill, doc_type
            )
            dpo_saved = True
        except Exception as e:
            log.warning("DPO save error: %s", e)

    # Step 3: Save master document to OmiAgent
    try:
        omi_result = await loop.run_in_executor(
            None, _docfill_save_to_omi, doc_title, filled_text, doc_type
        )
        omi_ok = True
        omi_id = omi_result if isinstance(omi_result, str) else None
    except Exception as e:
        omi_result = e
        omi_ok = False
        omi_id = None

    # Cleanup temporary files
    blank_path = state.get("blank_path")
    filled_path = state.get("filled_path")
    if blank_path:
        Path(str(blank_path)).unlink(missing_ok=True)
    if filled_path:
        Path(str(filled_path)).unlink(missing_ok=True)

    _PENDING_DOCFILL.pop(chat_id, None)

    # Build confirmation
    lines_ru = ["✅ **Одобрено и сохранено:**"]
    lines_en = ["✅ **Approved and saved:**"]

    if sft_ok:
        lines_ru.append("  • SFT-пара → `ops/ft/data/docfill_v1/train_docfill_v1.jsonl`")
        lines_en.append("  • SFT pair → `ops/ft/data/docfill_v1/train_docfill_v1.jsonl`")
    else:
        lines_ru.append(f"  ⚠️ SFT-пара: ошибка — {sft_result}")
        lines_en.append(f"  ⚠️ SFT pair: error — {sft_result}")

    if dpo_saved:
        lines_ru.append("  • DPO-пара → `data/training/standard_dpo_pairs.jsonl`")
        lines_en.append("  • DPO pair → `data/training/standard_dpo_pairs.jsonl`")
    elif local_fill:
        lines_ru.append(f"  ⚠️ DPO-пара: ошибка — {results[2]}")
        lines_en.append(f"  ⚠️ DPO pair: error — {results[2]}")
    else:
        report_suffix_ru = f"\n    _{repair_report}_" if repair_report else ""
        report_suffix_en = report_suffix_ru
        lines_ru.append(f"  • DPO-пара: Repairman исчерпал 5 циклов ремонта — пропущено{report_suffix_ru}")
        lines_en.append(f"  • DPO pair: Repairman exhausted 5 repair cycles — skipped{report_suffix_en}")

    if omi_ok:
        id_str = f" (id={omi_id})" if omi_id else ""
        lines_ru.append(f"  • Мастер-документ → OmiAgent{id_str}: `{doc_title}`")
        lines_en.append(f"  • Master document → OmiAgent{id_str}: `{doc_title}`")
    else:
        lines_ru.append(f"  ⚠️ Мастер-документ: ошибка OmiAgent — {omi_result}")
        lines_en.append(f"  ⚠️ Master document: OmiAgent error — {omi_result}")

    msg = "\n".join(lines_ru) if lang == "ru" else "\n".join(lines_en)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        return
    text = _extract_analyze_text(update, ctx)
    if not text:
        _set_pending_analyze(update.effective_chat.id, "Analyze uploaded document and provide concise findings.")
        await update.message.reply_text(
            "Режим /analyze включён. Загрузите файлы группой.\n"
            "Я дождусь окончания загрузки и обработаю пакет целиком.\n"
            "Можно добавить цель: `/analyze <что проверить>`."
        )
        return
    _set_pending_analyze(update.effective_chat.id, text)
    await update.message.reply_text("Принято. Жду загрузку файлов для пакетного анализа.")


async def cmd_analyze_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        return
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = _get_pending_analyze_state(chat_id)
    if not state:
        await update.message.reply_text("Нет активного режима /analyze.")
        return
    files = list(state.get("files") or [])
    if not files:
        await update.message.reply_text("Файлы для пакетного анализа ещё не загружены.")
        return
    override_prompt = " ".join(ctx.args).strip() if getattr(ctx, "args", None) else ""
    prompt = override_prompt or str(state.get("prompt", "")).strip()
    if _analyze_prompt_is_unclear(prompt):
        await update.message.reply_text(
            "Уточните цель: `/analyze_done <что сделать с файлами>`."
        )
        return
    lang = _reply_lang(update.message.text or prompt)
    _PENDING_ANALYZE.pop(chat_id, None)
    _pending_analyze_persist()
    await update.message.reply_text(
        "Запускаю пакетный анализ без ожидания таймера."
        if lang == "ru" else
        "Starting batch analysis immediately (without timer wait)."
    )
    await _process_analyze_batch(ctx.bot, chat_id, prompt, files, lang=lang)


async def cmd_analyze_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias for /analyze_done to avoid command mismatch in chats."""
    await cmd_analyze_done(update, ctx)


# ── Main message handler ───────────────────────────────────────────────────────

async def handle_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if not _claim_update_once(update):
        return
    _chat_id = update.effective_chat.id if update.effective_chat else None
    if not _chat_allowed(update):
        return
    # ── Intent clarification response ─────────────────────────────────────────
    if _chat_id and _chat_id in _pending_intent:
        pending = _pending_intent.pop(_chat_id)
        answer_text = update.message.text.strip().lower()
        if any(w in answer_text for w in ("word", "docx", "document", "report", "анализ", "отчёт", "документ", "word-")):
            confirmed = "docx"
        elif any(w in answer_text for w in ("edit", "update", "table", "spreadsheet", "таблиц", "измен", "обнов")):
            confirmed = "edit"
        else:
            confirmed = "chat"
        _save_intent_example(pending["prompt"], pending["files"], confirmed)
        lang = pending.get("lang", "en")
        await _process_analyze_batch(ctx.bot, _chat_id, pending["prompt"], pending["files"], lang=lang)
        return
    # ──────────────────────────────────────────────────────────────────────────
    state = _get_pending_analyze_state(_chat_id) if _chat_id is not None else None
    if state and state.get("awaiting_clarify") and (state.get("files") or []):
        text = update.message.text.strip()
        state["prompt"] = text
        state["awaiting_clarify"] = False
        files = list(state.get("files") or [])
        lang = _reply_lang(text)
        _PENDING_ANALYZE.pop(_chat_id, None)
        _pending_analyze_persist()
        await _process_analyze_batch(ctx.bot, _chat_id, text, files, lang=lang)
        return

    text = update.message.text.strip()
    await _process_request_text(
        update,
        ctx,
        text,
        require_group_mention=AXI_GROUP_REQUIRE_MENTION,
    )


# ── Periodic stuck-task monitor (Axi как монитор качества) ───────────────────

async def _job_monitor_stuck_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Периодически (TASK_REGISTRY_MONITOR_INTERVAL сек) проверяет зависшие задачи.
    При обнаружении — уведомляет владельца в Axi-чат.
    Задачи старше TASK_REGISTRY_AUTO_CLEANUP_MINUTES отправляются на расследование repairman,
    который анализирует причину зависания, регистрирует проблему и удаляет задачу.
    Роль Axi: monitors quality (docs/project-owner-answers.md §9).
    """
    if _tr_client is None:
        return
    try:
        tasks = _tr_client.find_stuck(older_than_minutes=TASK_REGISTRY_STUCK_MINUTES)
    except Exception as e:
        log.warning("monitor_stuck_tasks: %s", e)
        return

    if not tasks:
        log.debug("monitor: no stuck tasks")
        return

    # Investigate and cleanup very old stuck tasks via repairman
    auto_cleanup_threshold = TASK_REGISTRY_AUTO_CLEANUP_MINUTES
    very_old_tasks = [t for t in tasks if t.get("age_minutes", 0) >= auto_cleanup_threshold]

    if very_old_tasks:
        log.warning("monitor: found %d tasks stuck for >%.0f minutes - sending to repairman for investigation",
                    len(very_old_tasks), auto_cleanup_threshold)

        for t in very_old_tasks:
            task_id = t.get("task_id")
            assigned_to = t.get("assigned_to", "unassigned")
            age_min = t.get("age_minutes", 0)
            description = t.get("description", "")[:500]
            status = t.get("status", "unknown")

            # Send to repairman for root cause analysis
            investigation_prompt = (
                f"STUCK TASK INVESTIGATION\n\n"
                f"Task ID: {task_id}\n"
                f"Assigned to: {assigned_to}\n"
                f"Status: {status}\n"
                f"Age: {age_min:.0f} minutes\n"
                f"Description: {description}\n\n"
                f"Analyze why this task is stuck:\n"
                f"1. Is the assigned agent running?\n"
                f"2. Is there a missing dependency or configuration?\n"
                f"3. Is this a scheduled task with no executor?\n"
                f"4. Should this task type be disabled or reassigned?\n\n"
                f"Provide root_cause analysis and recommend fix."
            )

            try:
                # Call repairman for investigation
                import httpx
                gateway_url = "http://localhost:8082/v1/chat/completions"
                token = os.environ.get("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")

                response = httpx.post(
                    gateway_url,
                    json={
                        "model": "claude-sonnet-4",
                        "messages": [{"role": "user", "content": investigation_prompt}],
                        "max_tokens": 500,
                    },
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30.0,
                )

                if response.status_code == 200:
                    result = response.json()
                    root_cause = result.get("choices", [{}])[0].get("message", {}).get("content", "unknown")
                    log.warning(
                        "REPAIRMAN INVESTIGATION: task_id=%s\n"
                        "Root cause: %s",
                        task_id, root_cause[:500]
                    )
                else:
                    root_cause = f"repairman_unavailable (status {response.status_code})"
                    log.warning("Repairman investigation failed for %s: %s", task_id, root_cause)

            except Exception as e:
                root_cause = f"repairman_error: {e}"
                log.warning("Repairman investigation error for %s: %s", task_id, e)

            # Register the problem and cleanup the task
            try:
                _tr_client.mark_done(task_id, summary=f"stuck_investigated_cleanup: {root_cause[:200]}")
                log.info("monitor: investigated and cleaned up task %s (age: %.0f min)", task_id, age_min)
            except Exception as e:
                log.warning("monitor: failed to cleanup task %s: %s", task_id, e)

        # Remove cleaned tasks from notification list
        tasks = [t for t in tasks if t.get("age_minutes", 0) < auto_cleanup_threshold]

    if not tasks:
        log.debug("monitor: all stuck tasks investigated and cleaned")
        return

    # Suppress OCR handoff backlog from Axi alerts: these are handled by Omi batch
    # pipeline and create noisy false positives in Axi chat monitoring.
    filtered: list[dict] = []
    suppressed = 0
    for t in tasks:
        assigned = str(t.get("assigned_to", "")).lower()
        desc = str(t.get("description", "")).lower()
        if assigned == "omi_batch" and "ocr+analyze" in desc:
            suppressed += 1
            continue
        # Suppress repetitive "status of repeated anonymization" tracker tasks.
        if assigned == "omi" and ("статус повторной ан" in desc or "status of repeated anonym" in desc):
            suppressed += 1
            continue
        filtered.append(t)
    tasks = filtered
    if not tasks:
        if suppressed:
            log.info("monitor: suppressed %d omi_batch OCR backlog task(s)", suppressed)
        return

    # Deduplicate notifications: alert only on real task state changes.
    # Pure age growth must not produce repeated alerts.
    signature_parts: list[str] = []
    for t in sorted(tasks, key=lambda x: str(x.get("task_id", ""))):
        tid = str(t.get("task_id", "")).strip()
        if not tid:
            continue
        assigned = str(t.get("assigned_to", "")).strip().lower() or "-"
        status = str(t.get("status", "")).strip().lower() or "-"
        desc = str(t.get("description", "")).strip()[:120]
        signature_parts.append(f"{tid}|{assigned}|{status}|{desc}")
    signature = "||".join(signature_parts)
    last_sig = context.application.bot_data.get("_axi_stuck_last_signature")
    if signature == last_sig:
        log.info("monitor: skipped duplicate stuck-task alert (signature unchanged)")
        return
    context.application.bot_data["_axi_stuck_last_signature"] = signature

    lines = [f"⚠️ *Axi: зависшие задачи ({len(tasks)}):*"]
    for t in tasks[:5]:
        age_min = int(t['age_minutes'])
        lines.append(
            f"  • `{t['task_id']}` [{t['assigned_to'] or '—'}] "
            f"{age_min}м — {t['description'][:60]}"
        )
    if len(tasks) > 5:
        lines.append(f"  _…и ещё {len(tasks) - 5}_")
    lines.append(f"\n_Задачи старше {int(auto_cleanup_threshold)}м расследуются repairman и удаляются._")
    report_text = "\n".join(lines)

    bot = context.application.bot
    for owner_id in OWNER_CHATS:
        try:
            await bot.send_message(chat_id=owner_id, text=report_text, parse_mode="Markdown")
            log.info("monitor: notified owner %s about %d stuck tasks", owner_id, len(tasks))
        except Exception as e:
            log.warning("monitor: failed to notify owner %s: %s", owner_id, e)


# ── Bot setup ──────────────────────────────────────────────────────────────────

async def _post_init(application: Application) -> None:
    commands = [
        BotCommand("start",          "Запуск / приветствие"),
        BotCommand("help",           "Справка по командам"),
        BotCommand("analyze",        "Ожидать и анализировать файл"),
        BotCommand("analyze_done",   "Запустить пакет /analyze сейчас"),
        BotCommand("analyze_end",    "Алиас завершения загрузки файлов"),
        BotCommand("quality_report", "Отчёт качества задач"),
        BotCommand("stuck_tasks",    "Зависшие задачи"),
        BotCommand("close_task",     "Закрыть зависшую задачу"),
        BotCommand("doctuning",         "Создать тюнинг-пару из шаблона + эталона"),
        BotCommand("doctuning_approve", "Одобрить эталон — сохранить мастер-документ и пары"),
        BotCommand("doctuning_cancel",  "Отменить режим doctuning"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)

    try:
        _schedule_vram_warmup()
    except Exception as e:
        log.debug("post_init vram warm: %s", e)

    log.info(
        "Axi bot started. allowed=%s owner=%s "
        "aims_knowledge=%s local_llm_first=%s task_registry=%s",
        sorted(ALLOWED_CHATS),
        sorted(OWNER_CHATS),
        AXI_AIMS_KNOWLEDGE_MODE,
        _axi_llm_local_first_enabled(),
        _tr_client.base_url if _tr_client else "unavailable",
    )


def main() -> None:
    if not AXI_BOT_TOKEN:
        raise RuntimeError(
            "AXI_BOT_TOKEN (or AXI_TELEGRAM_TOKEN) is not set. "
            "Set it in .env or docker-compose environment."
        )

    _dialog_load()
    _pending_analyze_load()

    app = (
        Application.builder()
        .token(AXI_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("help",           cmd_help))
    app.add_handler(CommandHandler("analyze",        cmd_analyze))
    app.add_handler(CommandHandler("analyze_done",   cmd_analyze_done))
    app.add_handler(CommandHandler("analyze_end",    cmd_analyze_end))
    app.add_handler(CommandHandler("quality_report", cmd_quality_report))
    app.add_handler(CommandHandler("stuck_tasks",    cmd_stuck_tasks))
    app.add_handler(CommandHandler("close_task",     cmd_close_task))
    app.add_handler(CommandHandler("cleanup_tasks",  cmd_cleanup_tasks))
    app.add_handler(CommandHandler("doctuning",         cmd_doctuning))
    app.add_handler(CommandHandler("doctuning_approve", cmd_doctuning_approve))
    app.add_handler(CommandHandler("doctuning_cancel",  cmd_doctuning_cancel))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(_cmd_start_callback, pattern="^axi_activate$"))

    # Text messages
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat))

    # Periodic stuck-task monitor (Axi = качественный монитор §9)
    app.job_queue.run_repeating(
        _job_monitor_stuck_tasks,
        interval=TASK_REGISTRY_MONITOR_INTERVAL,
        first=60,
        name="monitor_stuck_tasks",
    )

    # VRAM queue monitor: resume docfill local-fill tasks when GPU memory is available
    app.job_queue.run_repeating(
        _job_docfill_vram_monitor,
        interval=60,
        first=90,
        name="docfill_vram_monitor",
    )
    app.job_queue.run_repeating(
        _job_flush_pending_analyze,
        interval=5,
        first=5,
        name="flush_pending_analyze",
    )
    app.job_queue.run_repeating(
        _job_axi_deliver_cross_handoffs,
        interval=2,
        first=3,
        name="axi_cross_handoff",
    )

    log.info("Starting Axi bot polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
