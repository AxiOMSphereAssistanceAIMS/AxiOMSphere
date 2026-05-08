#!/usr/bin/env python3
"""
argus_bot.py
────────────
Argus — AIMS Infrastructure Watchdog Bot.

Monitors Docker containers, Ollama models, task registry, nightly schedules.
Sends Telegram alerts with [Рестарт] / [Диагноз] / [Игнор] buttons.
All blocking I/O (Docker, Ollama, DB, HTTP) runs in asyncio.to_thread() so the
event loop is never frozen.

Переменные окружения:
  ARGUS_BOT_TOKEN           — Telegram bot token (@AIMS_argus_bot)
  ARGUS_ALLOWED_USER_IDS    — comma-separated Telegram user IDs
  ARGUS_OWNER_CHAT_IDS      — comma-separated chat IDs for alerts
  ARGUS_COMPOSE_FILE        — path to docker-compose.yml (default: /workspace/docker-compose.yml)
  ARGUS_COMPOSE_PROJECT     — compose project name (default: axiomsphere)
  ARGUS_LOCAL_DIAG_MODEL    — small Ollama model for AI diagnosis
  ARGUS_DIAG_BACKEND        — auto|local|claude|gemini (default: auto)
  ARGUS_AUTO_RESTART        — 1: auto-restart crashed containers (default: 1)
  ARGUS_AUTO_RESTART_MAX    — max restarts per hour (default: 3)
  TASK_REGISTRY_URL         — task registry HTTP API (default: http://task-registry:8765)
  DGX_OLLAMA_URL, OLLAMA_LOCAL_URL, PC_ANDREY_OLLAMA_URL — Ollama node URLs
  ANTHROPIC_API_KEY         — Claude API key
  GEMINI_API_KEY_1..4       — Gemini API keys
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv

load_dotenv("/workspace/.env", override=False)
load_dotenv("/workspace/ops/.env.argus", override=True)

from telegram import (
    BotCommand,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from argus_storage import ArgusStorage
from argus_docker import DockerManager
from argus_ollama import OllamaManager, resolve_model_name
from argus_code_agent import (
    ask_claude_code_headless,
    ask_local_model,
    code_backend_summary,
    collect_code_context,
    review_prompt,
)
from argus_monitor import ArgusMonitor, MonitorEvent
from argus_keepalive import KeepaliveManager
from argus_orchestrator import ArgusOrchestrator, PlanStep
from ft_lifecycle import (
    collect_checkpoints as ft_collect_checkpoints,
    create_version_from as ft_create_version_from,
    evaluate_benchmark_decision as ft_evaluate_benchmark_decision,
    latest_version_summary as ft_latest_version_summary,
    load_registry as ft_load_registry,
    next_version as ft_next_version,
    parse_version_token as ft_parse_version_token,
    resolve_active as ft_resolve_active,
    update_version_status as ft_update_version_status,
    version_paths as ft_version_paths,
)
import argus_diagnose as _diag

# ── Argument parsing helpers ───────────────────────────────────────────────────

_KNOWN_NODES = {"DGX", "DGX_WIFI", "SPARK", "PC_ANDREI"}


def _parse_model_node(args: list[str]) -> tuple[str, str | None]:
    """
    Parse (model_name, node_name) from command args intelligently.

    Supports all natural notations:
      /load small              → ("qwen2.5-aims-ft-v6", None)
      /load small DGX          → ("qwen2.5-aims-ft-v6", "DGX")
      /load DGX small          → ("qwen2.5-aims-ft-v6", "DGX")    ← node-first
      /unload PC_ANDREI: qwen  → ("qwen2.5-aims-ft-v6", "PC_ANDREI")  ← with colon
      /unload PC_ANDREI:qwen2.5-aims-ft-v6  → same
    """
    if not args:
        return "", None

    a0 = args[0].rstrip(":")
    a0_up = a0.upper()

    # Pattern: "NODE:model" merged in one token (e.g. "PC_ANDREI:qwen2.5...")
    if ":" in args[0]:
        node_part, _, model_part = args[0].partition(":")
        if node_part.upper() in _KNOWN_NODES:
            model = resolve_model_name(model_part) if model_part else (
                resolve_model_name(args[1]) if len(args) > 1 else ""
            )
            return model, node_part.upper()

    # Pattern: first arg is a bare node name (with or without trailing colon)
    if a0_up in _KNOWN_NODES:
        model = resolve_model_name(args[1]) if len(args) > 1 else ""
        return model, a0_up

    # Standard: model [node]
    model = resolve_model_name(args[0])
    node  = args[1].upper().rstrip(":") if len(args) > 1 else None
    # Validate node; if it's not a known node name just ignore it (may be extra text)
    if node and node not in _KNOWN_NODES and not node.startswith("HTTP"):
        node = None
    return model, node

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("argus")

# ── Config ─────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("ARGUS_BOT_TOKEN", "").strip()
ALLOWED_IDS: set[int] = {
    int(x)
    for x in os.environ.get("ARGUS_ALLOWED_USER_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}
OWNER_CHAT_IDS: list[int] = [
    int(x)
    for x in os.environ.get("ARGUS_OWNER_CHAT_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
]
AUTO_RESTART    = os.environ.get("ARGUS_AUTO_RESTART", "1").strip() == "1"
DB_PATH         = os.environ.get("ARGUS_DB_PATH", "/data/argus.db")
TASK_REG_URL    = os.environ.get("TASK_REGISTRY_URL", "http://task-registry:8765").rstrip("/")
CODE_REPO_PATH  = os.environ.get("ARGUS_CODE_REPO", "/workspace")
CODE_MODEL      = os.environ.get("ARGUS_CODE_MODEL", "qwen3:32b-q8_0")
CHAT_MODEL      = os.environ.get("ARGUS_CHAT_MODEL", CODE_MODEL)
ANALYSIS_MODEL  = os.environ.get("ARGUS_ANALYSIS_MODEL", CODE_MODEL or CHAT_MODEL).strip()
CHAT_ENABLED    = os.environ.get("ARGUS_CHAT_ENABLED", "1").strip() == "1"
BOT_USERNAME    = os.environ.get("ARGUS_BOT_USERNAME", "").strip().lstrip("@")
LLM_BACKEND     = os.environ.get("ARGUS_LLM_BACKEND", "ollama_api").strip().lower()
_UNSUPPORTED_MODELS_RAW = os.environ.get(
    "ARGUS_CLAUDE_CODE_UNSUPPORTED_MODELS",
    "qwen3:32b-q8_0",
).strip()
CLAUDE_CODE_UNSUPPORTED_MODELS = {
    m.strip().lower() for m in _UNSUPPORTED_MODELS_RAW.split(",") if m.strip()
}
_RUNTIME_MODEL_BLOCKLIST_RAW = os.environ.get(
    "ARGUS_RUNTIME_MODEL_BLOCKLIST",
    "",
).strip()
RUNTIME_MODEL_BLOCKLIST = {
    m.strip().lower() for m in _RUNTIME_MODEL_BLOCKLIST_RAW.split(",") if m.strip()
}
WARM_HEAVY_ON_REQUEST = os.environ.get("ARGUS_WARM_HEAVY_ON_REQUEST", "1").strip() == "1"
WARM_HEAVY_MODEL = os.environ.get("ARGUS_WARM_HEAVY_MODEL", CHAT_MODEL or CODE_MODEL)
WARM_HEAVY_NODE = os.environ.get("ARGUS_WARM_HEAVY_NODE", "DGX")
WARM_HEAVY_KEEPALIVE = os.environ.get("ARGUS_WARM_HEAVY_KEEPALIVE", "2h")
WARM_HEAVY_COOLDOWN_SEC = max(10, int(os.environ.get("ARGUS_WARM_HEAVY_COOLDOWN_SEC", "90")))
# Skip heavy warm if existing VRAM usage already exceeds this threshold (GB).
# Prevents double-loading when Cursor/coder model is already occupying VRAM.
WARM_HEAVY_VRAM_THRESHOLD_GB = float(os.environ.get("ARGUS_WARM_HEAVY_VRAM_THRESHOLD_GB", "60"))
SMALL_MODEL = os.environ.get("ARGUS_SMALL_MODEL", os.environ.get("FT_MODEL_14", os.environ.get("ARGUS_LOCAL_DIAG_MODEL", "qwen2.5-aims-ft-v7:latest"))).strip()
SMALL_NODE = os.environ.get("ARGUS_SMALL_NODE", "PC_ANDREI").strip()
SMALL_KEEPALIVE = os.environ.get("ARGUS_SMALL_KEEPALIVE", "24h").strip()
# Средняя (напр. qwen2.5-coder:32b) — отдельный keepalive-слот, по умолчанию DGX.
MEDIUM_MODEL = os.environ.get("ARGUS_MEDIUM_MODEL", "").strip()
MEDIUM_NODE = os.environ.get("ARGUS_MEDIUM_NODE", "DGX").strip()
MEDIUM_KEEPALIVE = os.environ.get("ARGUS_MEDIUM_KEEPALIVE", "24h").strip()
WARM_MEDIUM_ON_START = os.environ.get("ARGUS_WARM_MEDIUM_ON_START", "1").strip() == "1"
WARM_HEAVY_ON_START = os.environ.get("ARGUS_WARM_HEAVY_ON_START", "1").strip() == "1"
USE_SMALL_WHILE_HEAVY_LOADING = os.environ.get("ARGUS_USE_SMALL_WHILE_HEAVY_LOADING", "1").strip() == "1"
WARM_SMALL_ON_START = os.environ.get("ARGUS_WARM_SMALL_ON_START", "1").strip() == "1"
WARM_SMALL_INTERVAL_SEC = max(60, int(os.environ.get("ARGUS_WARM_SMALL_INTERVAL_SEC", "900")))
USE_SHARED_OLLAMA_RESOLVE = os.environ.get("ARGUS_USE_SHARED_OLLAMA_RESOLVE", "1").strip() == "1"
CHAT_CONTEXT_TURNS = max(1, int(os.environ.get("ARGUS_CHAT_CONTEXT_TURNS", "8")))
CLAUDE_CODE_APPROVAL_TTL_SEC = max(60, int(os.environ.get("ARGUS_CLAUDE_CODE_APPROVAL_TTL_SEC", "600")))
_CLAUDE_CODE_ADD_DIRS_RAW = os.environ.get("ARGUS_CLAUDE_CODE_ADD_DIRS", "").strip()
if _CLAUDE_CODE_ADD_DIRS_RAW:
    CLAUDE_CODE_ADD_DIRS = [x.strip() for x in _CLAUDE_CODE_ADD_DIRS_RAW.split(",") if x.strip()]
else:
    CLAUDE_CODE_ADD_DIRS = [CODE_REPO_PATH, "/workspace", "/ops", "/argus"]
_seen_add_dirs: set[str] = set()
CLAUDE_CODE_ADD_DIRS = [d for d in CLAUDE_CODE_ADD_DIRS if not (d in _seen_add_dirs or _seen_add_dirs.add(d))]
KNOMI_ENABLED = os.environ.get("ARGUS_KNOMI_ENABLED", "1").strip() == "1"
KNOMI_TOP_K = max(1, int(os.environ.get("ARGUS_KNOMI_TOP_K", "5")))
CLAUDE_CHANGE_MAX_LOOPS = max(1, int(os.environ.get("ARGUS_CLAUDE_CHANGE_MAX_LOOPS", "3")))
CLAUDE_ANALYSIS_TIMEOUT_SEC = max(60, int(os.environ.get("ARGUS_CLAUDE_ANALYSIS_TIMEOUT_SEC", "180")))
THERMAL_GUARD_ENABLED = os.environ.get("ARGUS_THERMAL_GUARD_ENABLED", "1").strip() == "1"
THERMAL_GUARD_INTERVAL_SEC = max(5, int(os.environ.get("ARGUS_THERMAL_GUARD_INTERVAL_SEC", "15")))
THERMAL_CPU_TEMP_WARM_C = float(os.environ.get("ARGUS_CPU_TEMP_WARM_C", "65"))
THERMAL_CPU_TEMP_HOT_C = float(os.environ.get("ARGUS_CPU_TEMP_HOT_C", "75"))
THERMAL_CPU_TEMP_RESUME_C = float(os.environ.get("ARGUS_CPU_TEMP_RESUME_C", "68"))
THERMAL_CPU_UTIL_HIGH_PCT = float(os.environ.get("ARGUS_CPU_UTIL_HIGH_PCT", "92"))
THERMAL_CPU_UTIL_RESUME_PCT = float(os.environ.get("ARGUS_CPU_UTIL_RESUME_PCT", "80"))
THERMAL_RESUME_STABLE_SEC = max(30, int(os.environ.get("ARGUS_THERMAL_RESUME_STABLE_SEC", "180")))
THERMAL_GPU_TEMP_HOT_C = float(os.environ.get("ARGUS_GPU_TEMP_HOT_C", "82"))
THERMAL_GPU_TEMP_CRITICAL_C = float(os.environ.get("ARGUS_GPU_TEMP_CRITICAL_C", "85"))
THERMAL_CPU_TEMP_CRITICAL_C = float(os.environ.get("ARGUS_CPU_TEMP_CRITICAL_C", "78"))
THERMAL_TEMP_RISE_RATE_C = float(os.environ.get("ARGUS_TEMP_RISE_RATE_C", "3.0"))  # °C rise per guard interval → fast-rise trigger
THERMAL_GPU_TEMP_WARM_C = float(os.environ.get("ARGUS_GPU_TEMP_RISE_MIN_C", "75"))  # fast-rise only triggers above this GPU temp
THERMAL_CPU_TEMP_RISE_MIN_C = float(os.environ.get("ARGUS_CPU_TEMP_RISE_MIN_C", "75"))  # fast-rise only triggers above this CPU temp
GPU_POWER_CAP_ENABLED = os.environ.get("ARGUS_GPU_POWER_CAP_ENABLED", "0").strip() == "1"
GPU_POWER_LOW_W = int(os.environ.get("ARGUS_GPU_POWER_LOW_W", "60"))   # GB10 GPU ≈90-100W max; 60W ≈ throttled
GPU_POWER_HIGH_W = int(os.environ.get("ARGUS_GPU_POWER_HIGH_W", "0"))   # 0 = nvidia default
GPU_POWER_CAP_TEMP_C = float(os.environ.get("ARGUS_GPU_POWER_CAP_TEMP_C", "72"))
OMI_REQUEST_WORKER_AUTO = os.environ.get("ARGUS_OMI_REQUEST_WORKER_AUTO", "1").strip() == "1"
TELEGRAM_MODE = os.environ.get("ARGUS_TELEGRAM_MODE", "polling").strip().lower()
WEBHOOK_PUBLIC_URL = os.environ.get("ARGUS_WEBHOOK_URL", "").strip()
WEBHOOK_PATH = os.environ.get("ARGUS_WEBHOOK_PATH", "/telegram/argus").strip() or "/telegram/argus"
WEBHOOK_LISTEN = os.environ.get("ARGUS_WEBHOOK_LISTEN", "0.0.0.0").strip()
WEBHOOK_PORT = int(os.environ.get("ARGUS_WEBHOOK_PORT", "8088"))
WEBHOOK_SECRET = os.environ.get("ARGUS_WEBHOOK_SECRET", "").strip()
REPAIRMAN_URL = os.environ.get("REPAIRMAN_URL", "http://repairman-api:8010")
AIMS_SERVICE_TOKEN = os.environ.get("AIMS_SERVICE_TOKEN", "aims-service-token")

# ── Services ───────────────────────────────────────────────────────────────────
storage    = ArgusStorage(DB_PATH)
docker_mgr = DockerManager()
ollama_mgr = OllamaManager()

_alert_queue: asyncio.Queue[MonitorEvent] = asyncio.Queue()
_app: Application | None = None
_last_heavy_warm_ts = 0.0
_heavy_warm_lock = threading.Lock()
_chat_ctx_lock = threading.Lock()
_chat_context: dict[int, deque[tuple[str, str]]] = {}
_cc_approval_lock = threading.Lock()
_pending_cc_approvals: dict[str, dict[str, object]] = {}
_ft_confirm_lock = threading.Lock()
_pending_ft_confirms: dict[str, dict[str, object]] = {}
_thermal_state_lock = threading.Lock()
_thermal_paused = False
_thermal_pause_reason = ""
_thermal_cool_since = 0.0
_last_gpu_temp = 0.0
_last_cpu_temp = 0.0
_last_temp_snap_ts = 0.0
_gpu_power_capped = False
_last_ft_launch_pid: int | None = None
_last_ft_launch_meta: dict[str, str] = {}
_pending_ft_launch_queue: deque[dict[str, object]] = deque(maxlen=32)
_pending_ft_workflow_queue: deque[dict[str, object]] = deque(maxlen=64)
_pending_chat_retry_queue: deque[dict[str, object]] = deque(maxlen=64)
_PENDING_QUEUES_PATH = Path(os.environ.get("ARGUS_PENDING_QUEUES_PATH", "/data/argus_pending_queues.json"))
# Serializes heavy LLM calls so at most 1 request hits the GPU at a time.
# Prevents GPU utilization spikes to 96%+ and CPU thermal shutdowns.
_chat_llm_lock: asyncio.Lock | None = None


def _get_chat_llm_lock() -> asyncio.Lock:
    global _chat_llm_lock
    if _chat_llm_lock is None:
        _chat_llm_lock = asyncio.Lock()
    return _chat_llm_lock
_FT_LOCAL_LOG_BY_ALIAS = {
    "14": Path("/workspace/ops/ft/logs/train_v7_local_argus.log"),
    "70": Path("/workspace/ops/ft/logs/train_70_local_argus.log"),
    "72": Path("/workspace/ops/ft/logs/train_72_local_argus.log"),
}
_FT_CHAIN_STATUS_PATH = Path("/workspace/ops/ft/logs/ft_chain_status.json")
_FT_V7_LOG_PATH = Path("/workspace/ops/ft/logs/train_v7_local_argus.log")
_FT_V8_LOG_PATH = Path("/workspace/ops/ft/logs/train_v8_local_argus.log")
_FT_OUTPUT_DIR = Path("/workspace/ops/ft/output")
_FT_CFG_V7_PATH = Path("/workspace/ops/ft/configs/train_config.json")
_FT_CFG_V8_PATH = Path("/workspace/ops/ft/configs/train_config_v8.json")


def _persist_pending_queues() -> None:
    try:
        _PENDING_QUEUES_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ft": list(_pending_ft_launch_queue),
            "ft_workflow": list(_pending_ft_workflow_queue),
            "chat": list(_pending_chat_retry_queue),
            "saved_at": time.time(),
        }
        _PENDING_QUEUES_PATH.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    except Exception as exc:
        log.warning("pending queue persist failed: %s", exc)


def _load_pending_queues() -> None:
    if not _PENDING_QUEUES_PATH.exists():
        return
    try:
        payload = json.loads(_PENDING_QUEUES_PATH.read_text(encoding="utf-8"))
        for item in payload.get("ft", []):
            if isinstance(item, dict):
                _pending_ft_launch_queue.append(item)
        for item in payload.get("ft_workflow", []):
            if isinstance(item, dict):
                _pending_ft_workflow_queue.append(item)
        for item in payload.get("chat", []):
            if isinstance(item, dict):
                _pending_chat_retry_queue.append(item)
        if _pending_ft_launch_queue or _pending_ft_workflow_queue or _pending_chat_retry_queue:
            log.info(
                "restored pending queues: ft=%d ft_workflow=%d chat=%d",
                len(_pending_ft_launch_queue),
                len(_pending_ft_workflow_queue),
                len(_pending_chat_retry_queue),
            )
    except Exception as exc:
        log.warning("pending queue restore failed: %s", exc)


def _on_monitor_event(ev: MonitorEvent) -> None:
    """Called from background threads — put into async queue."""
    try:
        asyncio.get_event_loop().call_soon_threadsafe(_alert_queue.put_nowait, ev)
    except Exception:
        pass
    if ev.severity == "critical":
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from failure_detector import get_detector
            get_detector().from_argus({
                "service": ev.service,
                "event_type": ev.event_type,
                "message": ev.message,
            })
        except Exception:
            pass


def _on_keepalive_event(service: str, message: str) -> None:
    """Keepalive notifications → owner chat via alert queue."""
    ev = MonitorEvent(
        service=service,
        event_type="keepalive",
        message=message,
        severity="info",
    )
    _on_monitor_event(ev)


def _get_queue_depths() -> dict[str, int]:
    return {
        "ft_launch":   len(_pending_ft_launch_queue),
        "ft_workflow": len(_pending_ft_workflow_queue),
        "chat_retry":  len(_pending_chat_retry_queue),
    }

monitor  = ArgusMonitor(docker_mgr, ollama_mgr, storage, _on_monitor_event, queue_depth_fn=_get_queue_depths)
ka_mgr   = KeepaliveManager(docker_mgr, _on_keepalive_event)

# ── Orchestrator ───────────────────────────────────────────────────────────────

def _orch_notify(html_text: str) -> None:
    """Send plain HTML message to all owner chats (thread-safe)."""
    if _app is None:
        return
    async def _send():
        for cid in OWNER_CHAT_IDS:
            try:
                await _app.bot.send_message(cid, html_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.warning("orch_notify: %s", e)
    try:
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.ensure_future(_send())
        )
    except Exception as e:
        log.warning("orch_notify dispatch: %s", e)


def _orch_approval_request(step: PlanStep) -> None:
    """Send approval buttons to owner for a step that requires_approval."""
    if _app is None:
        return
    reason_block = f"\n⚠️ {step.approval_reason}" if step.approval_reason else ""
    text = (
        f"🔐 <b>Требуется одобрение</b>\n\n"
        f"<b>{step.description}</b>{reason_block}\n\n"
        f"Шаг: <code>{step.id}</code> · План: {step.plan_name}"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Выполнить", callback_data=f"plan_approve:{step.id}"),
            InlineKeyboardButton("⏸ Отложить 12ч", callback_data=f"plan_defer:{step.id}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"plan_cancel:{step.id}"),
        ]
    ])
    async def _send():
        for cid in OWNER_CHAT_IDS:
            try:
                await _app.bot.send_message(
                    cid, text, parse_mode=ParseMode.HTML, reply_markup=keyboard
                )
            except Exception as e:
                log.warning("orch_approval: %s", e)
    try:
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.ensure_future(_send())
        )
    except Exception as e:
        log.warning("orch_approval dispatch: %s", e)


orchestrator = ArgusOrchestrator(
    on_notify=_orch_notify,
    on_approval_request=_orch_approval_request,
    storage=storage,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _allowed(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    cid = update.effective_chat.id if update.effective_chat else None
    log.info("COMMAND uid=%s cid=%s ALLOWED_IDS=%s", uid, cid, ALLOWED_IDS)
    if not ALLOWED_IDS:
        return True
    result = uid in ALLOWED_IDS or cid in ALLOWED_IDS
    if not result:
        log.warning("BLOCKED uid=%s cid=%s", uid, cid)
    return result


def _is_owner(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    cid = update.effective_chat.id if update.effective_chat else None
    return (uid in OWNER_CHAT_IDS) or (cid in OWNER_CHAT_IDS)


def _approval_summary(prompt: str, model: str) -> str:
    text = " ".join((prompt or "").strip().split())
    if not text:
        return f"Изменение проекта через Claude Code ({model})"
    if len(text) > 180:
        text = text[:177] + "..."
    return f"Изменение проекта: {text} (модель: {model})"


def _build_change_analysis_prompt(user_request: str) -> str:
    return (
        "You are Claude Code in pre-change analysis mode.\n"
        "Before any edits, evaluate compatibility across project chains and integrations.\n"
        "Required output:\n"
        "1) Impact scope (files/chains/integrations)\n"
        "2) Regression and dependency risks\n"
        "3) Safeguards to avoid breakage\n"
        "4) Change plan and test plan\n"
        "5) Success criterion (what counts as PASS)\n"
        "Format: concise and structured.\n\n"
        f"Change request:\n{user_request}"
    )


def _build_change_apply_prompt(user_request: str, analysis: str, prev_feedback: str = "") -> str:
    extra = f"\n\nPrevious failed-attempt context:\n{prev_feedback}\n" if prev_feedback else ""
    return (
        "You are Claude Code in change-application mode.\n"
        "First validate compatibility impact, then apply requested changes.\n"
        "After each step, run relevant tests/checks and fix issues found.\n"
        f"Run up to {CLAUDE_CHANGE_MAX_LOOPS} internal loops: check -> fix -> apply -> test.\n"
        "At the end, you MUST output exactly one status line:\n"
        "FINAL_STATUS: PASS\n"
        "or\n"
        "FINAL_STATUS: FAIL\n"
        "and a short report: changed files, tests run, final outcome.\n\n"
        f"Original request:\n{user_request}\n\n"
        f"Pre-analysis:\n{analysis}\n"
        f"{extra}"
    )


def _mini_test_status(output: str) -> str:
    text = (output or "").lower()
    if "final_status: pass" in text:
        return "PASSED"
    if "final_status: fail" in text:
        return "FAILED"
    if any(x in text for x in ("failed", "error", "traceback", "assertionerror")):
        return "FAILED"
    if any(x in text for x in ("test", "pytest", "smoke", "ok", "passed")):
        return "TEST_SIGNAL"
    return "NO_TEST_SIGNAL"


def _put_cc_approval(
    chat_id: int,
    user_id: int,
    prompt: str,
    model: str,
    url: str,
    summary: str | None = None,
) -> str:
    req_id = uuid4().hex[:12]
    with _cc_approval_lock:
        _pending_cc_approvals[req_id] = {
            "ts": time.time(),
            "chat_id": chat_id,
            "user_id": user_id,
            "prompt": prompt,
            "model": model,
            "url": url,
            "summary": (summary or _approval_summary(prompt, model)),
        }
    return req_id


def _pop_cc_approval(req_id: str) -> dict[str, object] | None:
    with _cc_approval_lock:
        item = _pending_cc_approvals.pop(req_id, None)
    if not item:
        return None
    ts = float(item.get("ts", 0.0))
    if time.time() - ts > CLAUDE_CODE_APPROVAL_TTL_SEC:
        return None
    return item


def _put_ft_confirm(
    chat_id: int,
    user_id: int,
    normalized_text: str,
    summary: str,
    confidence: float,
) -> str:
    req_id = f"ft-{uuid4().hex[:10]}"
    with _ft_confirm_lock:
        _pending_ft_confirms[req_id] = {
            "ts": time.time(),
            "chat_id": int(chat_id),
            "user_id": int(user_id),
            "normalized_text": str(normalized_text),
            "summary": str(summary),
            "confidence": float(confidence),
        }
    return req_id


def _pop_ft_confirm(req_id: str) -> dict[str, object] | None:
    with _ft_confirm_lock:
        item = _pending_ft_confirms.pop(req_id, None)
    if not item:
        return None
    ts = float(item.get("ts", 0.0))
    if time.time() - ts > CLAUDE_CODE_APPROVAL_TTL_SEC:
        return None
    return item


def _knomi_paths() -> tuple[str, str, str]:
    return (
        "/workspace/ops/knomi/collector.py",
        "/workspace/ops/knomi/indexer.py",
        "/workspace/ops/knomi/search.py",
    )


def _knomi_prefetch_context(query: str) -> str:
    if not KNOMI_ENABLED:
        return ""
    collector, indexer, search = _knomi_paths()
    if not (Path(collector).exists() and Path(indexer).exists() and Path(search).exists()):
        return ""
    try:
        subprocess.run(["python3", collector], cwd="/workspace", check=False, capture_output=True, text=True, timeout=25)
        subprocess.run(["python3", indexer], cwd="/workspace", check=False, capture_output=True, text=True, timeout=90)
        p = subprocess.run(
            ["python3", search, "--query", query, "--top-k", str(KNOMI_TOP_K), "--recent-decisions", "5", "--json"],
            cwd="/workspace",
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if p.returncode != 0:
            return ""
        data = json.loads((p.stdout or "").strip() or "{}")
        results = data.get("results") or []
        decisions = data.get("recent_decisions") or []
        if not results and not decisions:
            return ""
        lines = ["Knomi context prefetch:"]
        for i, r in enumerate(results[:KNOMI_TOP_K], start=1):
            lines.append(
                f"{i}) [{float(r.get('score', 0.0)):.3f}] {r.get('kind','?')} {r.get('title','?')}: "
                f"{str(r.get('text','')).strip()[:280]}"
            )
        if decisions:
            lines.append("Recent decisions:")
            for d in decisions[:5]:
                lines.append(f"- {d.get('title','?')}: {str(d.get('text','')).strip()[:220]}")
        return "\n".join(lines)
    except Exception as exc:
        log.warning("knomi prefetch failed: %s", exc)
        return ""


def _knomi_log_event(kind: str, payload: dict[str, object]) -> None:
    if not KNOMI_ENABLED:
        return
    root = Path("/workspace/knowledge/events")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "argus_claude_events.jsonl"
    row = {"ts": datetime.utcnow().isoformat() + "Z", "kind": kind, **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _extract_omi_request(text: str) -> str | None:
    m = re.search(r"OMI_REQUEST\s*:\s*(.+)", text or "", flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    req = " ".join(m.group(1).strip().split())
    if not req:
        return None
    return req[:1200]


def _register_omi_request(origin: str, query: str, request_text: str) -> None:
    _knomi_log_event(
        "argus.omi.request",
        {
            "origin": origin,
            "query": query[:1200],
            "request": request_text,
            "status": "queued",
        },
    )
    if OMI_REQUEST_WORKER_AUTO:
        try:
            subprocess.Popen(
                ["python3", "/workspace/ops/knomi/omi_request_worker.py", "--once", "--json"],
                cwd="/workspace",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            log.warning("omi_request_worker auto start failed: %s", exc)


def _current_vram_total_gb() -> float:
    """Return total VRAM (GB) currently occupied across all loaded Ollama models on DGX."""
    try:
        import json as _json
        import urllib.request as _ur
        dgx_url = (
            os.environ.get("DGX_OLLAMA_URL", "")
            or os.environ.get("OLLAMA_LOCAL_URL", "")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        with _ur.urlopen(f"{dgx_url}/api/ps", timeout=3) as r:
            ps = _json.loads(r.read())
        return sum(mm.get("size_vram", 0) for mm in ps.get("models", [])) / 1e9
    except Exception:
        return 0.0


def _warm_heavy_model_now() -> None:
    """Best-effort heavy model warm-up on configured node."""
    model = resolve_model_name(WARM_HEAVY_MODEL) if WARM_HEAVY_MODEL else ""
    if not model:
        return
    vram_gb = _current_vram_total_gb()
    if vram_gb >= WARM_HEAVY_VRAM_THRESHOLD_GB:
        log.info("heavy warm skipped: VRAM %.1f GB >= threshold %.1f GB", vram_gb, WARM_HEAVY_VRAM_THRESHOLD_GB)
        return
    ok, msg = ollama_mgr.load_model(model, node=WARM_HEAVY_NODE, keep_alive=WARM_HEAVY_KEEPALIVE)
    if ok:
        log.info("heavy warm ok: %s", msg)
    else:
        log.warning("heavy warm failed: %s", msg)


def _warm_small_model_now() -> None:
    """Best-effort small model keepalive warm-up."""
    model = resolve_model_name(SMALL_MODEL) if SMALL_MODEL else ""
    if not model:
        return
    ok, msg = ollama_mgr.load_model(model, node=SMALL_NODE, keep_alive=SMALL_KEEPALIVE)
    if ok:
        log.info("small warm ok: %s", msg)
    else:
        log.warning("small warm failed: %s", msg)


def _warm_medium_model_now() -> None:
    """Best-effort medium model (e.g. coder 32B) keepalive — typically on DGX."""
    if not MEDIUM_MODEL:
        return
    model = resolve_model_name(MEDIUM_MODEL)
    if not model:
        return
    ok, msg = ollama_mgr.load_model(model, node=MEDIUM_NODE, keep_alive=MEDIUM_KEEPALIVE)
    if ok:
        log.info("medium warm ok: %s", msg)
    else:
        log.warning("medium warm failed: %s", msg)


def _import_shared_ollama_resolve():
    """Load shared ops/ollama_resolve.py used by Axi/Omi."""
    if not USE_SHARED_OLLAMA_RESOLVE:
        return None
    for p in ("/ops", "/workspace/ops"):
        if p not in sys.path and os.path.isdir(p):
            sys.path.append(p)
    try:
        return importlib.import_module("ollama_resolve")
    except Exception:
        return None


async def _small_model_keeper_loop() -> None:
    """Periodically ensure small (PC), optional medium, and heavy (DGX) models stay warm."""
    if not WARM_SMALL_ON_START and not (WARM_MEDIUM_ON_START and MEDIUM_MODEL) and not WARM_HEAVY_ON_START:
        return
    while True:
        try:
            if WARM_SMALL_ON_START and SMALL_MODEL:
                await asyncio.to_thread(_warm_small_model_now)
            if WARM_MEDIUM_ON_START and MEDIUM_MODEL:
                await asyncio.to_thread(_warm_medium_model_now)
            if WARM_HEAVY_ON_START and WARM_HEAVY_MODEL:
                await asyncio.to_thread(_warm_heavy_model_now)
        except Exception as exc:
            log.warning("small/medium/heavy keeper loop error: %s", exc)
        await asyncio.sleep(WARM_SMALL_INTERVAL_SEC)


def _sigstop_ft_group(pid: int) -> None:
    """Send SIGSTOP to the entire process group of pid so child GPU processes also pause."""
    try:
        pgid = os.getpgid(pid)
        os.kill(-pgid, signal.SIGSTOP)
        return
    except ProcessLookupError:
        return
    except Exception:
        pass
    try:
        os.kill(pid, signal.SIGSTOP)
    except Exception:
        pass


def _sigcont_ft_group(pid: int) -> None:
    """Send SIGCONT to the entire process group of pid."""
    try:
        pgid = os.getpgid(pid)
        os.kill(-pgid, signal.SIGCONT)
        return
    except ProcessLookupError:
        return
    except Exception:
        pass
    try:
        os.kill(pid, signal.SIGCONT)
    except Exception:
        pass


def _set_gpu_power_limit(watts: int) -> tuple[bool, str]:
    """
    Apply nvidia-smi power limit on DGX host via SSH.
    watts=0 resets to driver default (nvidia-smi -pm 1 only keeps persistence).
    """
    ssh_host = os.environ.get("ARGUS_FT_SSH_HOST", "").strip()
    ssh_user = os.environ.get("ARGUS_FT_SSH_USER", "").strip()
    if not ssh_host or not ssh_user:
        return False, "SSH not configured (ARGUS_FT_SSH_HOST/ARGUS_FT_SSH_USER)"
    cmd = f"sudo nvidia-smi -pl {watts}" if watts > 0 else "sudo nvidia-smi -pl $(sudo nvidia-smi --query-gpu=power.max_limit --format=csv,noheader,nounits | head -1 | tr -d ' ')"
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             "-o", "BatchMode=yes", f"{ssh_user}@{ssh_host}", cmd],
            capture_output=True, text=True, timeout=12,
        )
        if r.returncode == 0:
            return True, (r.stdout or "ok").strip()[:200]
        return False, (r.stderr or r.stdout or "").strip()[:200]
    except Exception as exc:
        return False, str(exc)[:200]


async def _thermal_guard_loop() -> None:
    if not THERMAL_GUARD_ENABLED:
        return
    global _thermal_paused, _thermal_pause_reason, _thermal_cool_since
    global _last_gpu_temp, _last_cpu_temp, _last_temp_snap_ts, _gpu_power_capped
    _ft_was_stopped = False  # track whether we already sent SIGSTOP this episode

    while True:
        try:
            blocked, reason, snap = await asyncio.to_thread(_thermal_preflight_status)
            now_ts = time.time()
            gpu_temp = float(snap.get("gpu_temp", 0.0))
            cpu_temp = float(snap.get("cpu_temp", 0.0))

            # ── Fast-rise detection ─────────────────────────────────────────────
            # If temperature rises ≥ THERMAL_TEMP_RISE_RATE_C in one poll interval,
            # trigger a block immediately even if absolute threshold not yet reached.
            fast_rise = False
            if _last_temp_snap_ts > 0 and gpu_temp > 0:
                gpu_delta = gpu_temp - _last_gpu_temp
                cpu_delta = cpu_temp - _last_cpu_temp
                if (gpu_delta >= THERMAL_TEMP_RISE_RATE_C and gpu_temp >= THERMAL_GPU_TEMP_WARM_C) or \
                   (cpu_delta >= THERMAL_TEMP_RISE_RATE_C and cpu_temp >= THERMAL_CPU_TEMP_RISE_MIN_C):
                    fast_rise = True
                    if not blocked:
                        blocked = True
                        reason = f"fast_rise:gpu+{gpu_delta:.1f}C/cpu+{cpu_delta:.1f}C"
            _last_gpu_temp = gpu_temp
            _last_cpu_temp = cpu_temp
            _last_temp_snap_ts = now_ts

            # ── Critical thresholds → unload model immediately ──────────────────
            critical = (
                (gpu_temp > 0 and gpu_temp >= THERMAL_GPU_TEMP_CRITICAL_C) or
                (cpu_temp > 0 and cpu_temp >= THERMAL_CPU_TEMP_CRITICAL_C)
            )
            if critical and WARM_HEAVY_MODEL:
                try:
                    heavy = resolve_model_name(WARM_HEAVY_MODEL) if WARM_HEAVY_MODEL else ""
                    if heavy:
                        await asyncio.to_thread(ollama_mgr.unload_model, heavy, WARM_HEAVY_NODE)
                        log.warning(
                            "thermal guard: unloaded %s (gpu=%.0f°C cpu=%.0f°C)",
                            heavy, gpu_temp, cpu_temp,
                        )
                except Exception as exc:
                    log.warning("thermal guard unload error: %s", exc)

            # ── GPU power cap ───────────────────────────────────────────────────
            if GPU_POWER_CAP_ENABLED and gpu_temp > 0:
                if not _gpu_power_capped and gpu_temp >= GPU_POWER_CAP_TEMP_C:
                    ok, msg = await asyncio.to_thread(_set_gpu_power_limit, GPU_POWER_LOW_W)
                    _gpu_power_capped = True
                    log.info("GPU power cap applied (%dW): %s", GPU_POWER_LOW_W, msg)
                elif _gpu_power_capped and gpu_temp < GPU_POWER_CAP_TEMP_C - 4:
                    ok, msg = await asyncio.to_thread(_set_gpu_power_limit, GPU_POWER_HIGH_W)
                    _gpu_power_capped = False
                    log.info("GPU power cap released: %s", msg)

            with _thermal_state_lock:
                was_paused = _thermal_paused
                if blocked:
                    _thermal_paused = True
                    _thermal_pause_reason = reason
                    _thermal_cool_since = 0.0
                else:
                    if _thermal_paused:
                        if cpu_temp <= THERMAL_CPU_TEMP_RESUME_C and float(snap.get("cpu_util", 0.0)) <= THERMAL_CPU_UTIL_RESUME_PCT:
                            if _thermal_cool_since <= 0:
                                _thermal_cool_since = now_ts
                            elif (now_ts - _thermal_cool_since) >= THERMAL_RESUME_STABLE_SEC:
                                _thermal_paused = False
                                _thermal_pause_reason = ""
                                _thermal_cool_since = 0.0
                        else:
                            _thermal_cool_since = 0.0
                    was_paused = was_paused or _thermal_paused

            # ── SIGSTOP/SIGCONT entire process group ────────────────────────────
            if blocked and _last_ft_launch_pid:
                if not _ft_was_stopped:
                    await asyncio.to_thread(_sigstop_ft_group, _last_ft_launch_pid)
                    _ft_was_stopped = True
                    if _app is not None:
                        ft_meta = _last_ft_launch_meta
                        family = ft_meta.get("family", "?")
                        for cid in OWNER_CHAT_IDS:
                            try:
                                await _app.bot.send_message(
                                    cid,
                                    f"⏸ FT training paused — thermal guard triggered.\n"
                                    f"Reason: {_h(reason)} | "
                                    f"GPU={gpu_temp:.0f}°C CPU={cpu_temp:.0f}°C | "
                                    f"Family: {_h(family)}",
                                    parse_mode=ParseMode.HTML,
                                )
                            except Exception:
                                pass

            if not _thermal_paused and _last_ft_launch_pid and _ft_was_stopped:
                await asyncio.to_thread(_sigcont_ft_group, _last_ft_launch_pid)
                _ft_was_stopped = False
                if _app is not None:
                    ft_meta = _last_ft_launch_meta
                    family = ft_meta.get("family", "?")
                    for cid in OWNER_CHAT_IDS:
                        try:
                            await _app.bot.send_message(
                                cid,
                                f"▶️ FT training resumed — temperature normalized.\n"
                                f"GPU={gpu_temp:.0f}°C CPU={cpu_temp:.0f}°C | Family: {_h(family)}",
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            pass

            # Drain queued FT launches when cooling criteria is met.
            if not _thermal_paused and _pending_ft_launch_queue and _app is not None:
                item = _pending_ft_launch_queue.popleft()
                _persist_pending_queues()
                cmd = item.get("cmd")
                chat_id = int(item.get("chat_id", 0))
                alias = str(item.get("alias", ""))
                if isinstance(cmd, list) and cmd:
                    p = await asyncio.to_thread(
                        subprocess.run,
                        cmd,
                        cwd="/workspace",
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    body = (p.stdout or "").strip()
                    if p.stderr:
                        body = f"{body}\n{p.stderr.strip()}".strip()
                    msg = (
                        f"▶️ DGX cooled down. Resumed queued FT run ({_h(alias)}).\n"
                        f"<pre>{_h((body or '(no output)')[:1800])}</pre>"
                    )
                    if chat_id:
                        try:
                            await _app.bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML)
                        except Exception:
                            pass
            # Drain queued FT workflow requests, but enforce one active training globally.
            if not _thermal_paused and _pending_ft_workflow_queue and _app is not None:
                active = _global_training_entries()
                if not active:
                    item = _pending_ft_workflow_queue.popleft()
                    _persist_pending_queues()
                    chat_id = int(item.get("chat_id", 0))
                    text = str(item.get("user_text", "")).strip()
                    family = str(item.get("family", "")).strip()
                    target_version = str(item.get("target_version", "")).strip()
                    if chat_id and text:
                        result = await asyncio.to_thread(_ft_v7_v8_workflow_reply, text)
                        note = (
                            f"▶️ Scheduler resumed queued FT workflow ({_h(family)}:{_h(target_version)}).\n"
                            f"{_sanitize_chat_answer(result)[:3200]}"
                        )
                        try:
                            await _app.bot.send_message(chat_id, note)
                        except Exception:
                            pass
            # Drain queued chat retries when cooldown criteria is met.
            if not _thermal_paused and _pending_chat_retry_queue and _app is not None:
                item = _pending_chat_retry_queue.popleft()
                _persist_pending_queues()
                chat_id = int(item.get("chat_id", 0))
                text = str(item.get("text", "")).strip()
                route_mode = str(item.get("route_mode", "argus")).strip() or "argus"
                retries = int(item.get("retries", 0))
                if chat_id and text:
                    await _resume_queued_chat(chat_id, text, route_mode, retries=retries)
            if blocked and not was_paused and _app is not None:
                note = (
                    "🧯 Thermal guard: new heavy launches paused.\n"
                    f"Reason: {_h(reason)} | GPU={gpu_temp:.1f}°C CPU={cpu_temp:.1f}°C "
                    f"load={snap.get('cpu_util', 0):.1f}%."
                )
                for cid in OWNER_CHAT_IDS:
                    try:
                        await _app.bot.send_message(cid, note, parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
        except Exception as exc:
            log.warning("thermal guard loop error: %s", exc)
        await asyncio.sleep(THERMAL_GUARD_INTERVAL_SEC)


async def _ft_process_watcher_loop() -> None:
    """
    Watches _last_ft_launch_pid and sends English notifications on FT lifecycle events:
    start (new PID detected), paused (SIGSTOP from thermal guard), stopped/failed/completed (process exits).
    """
    last_reported_pid: int | None = None
    last_reported_start: int | None = None

    while True:
        await asyncio.sleep(30)
        try:
            pid = _last_ft_launch_pid
            if not pid:
                continue

            # New FT process started — send start notification once
            if pid != last_reported_start:
                last_reported_start = pid
                last_reported_pid = None  # allow exit report for new PID
                meta = _last_ft_launch_meta.copy()
                family = meta.get("family", "?")
                version = meta.get("version", "")
                label = f"{family}:{version}" if version else family
                if _app is not None:
                    for cid in OWNER_CHAT_IDS:
                        try:
                            await _app.bot.send_message(
                                cid,
                                f"🚀 FT training started: <b>{_h(label)}</b> (pid={pid})",
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            pass
                continue  # check exit on next iteration

            # Skip if we already reported exit for this PID
            if pid == last_reported_pid:
                continue

            # Check if process is still alive
            try:
                os.kill(pid, 0)
                continue  # still running — nothing to report
            except ProcessLookupError:
                pass
            except PermissionError:
                continue  # exists but inaccessible

            last_reported_pid = pid

            meta = _last_ft_launch_meta.copy()
            family = meta.get("family", "?")
            version = meta.get("version", "")
            label = f"{family}:{version}" if version else family

            # Read last log line for status determination
            log_path = _FT_LOCAL_LOG_BY_ALIAS.get(str(family))
            last_line = ""
            if log_path and log_path.exists():
                last_line = _read_last_nonempty_line(log_path)

            ll = last_line.lower()
            if any(w in ll for w in ("error", "traceback", "failed", "exception", "killed")):
                status, icon = "FAILED", "❌"
            elif any(w in ll for w in ("complete", "finished", "done", "success", "saved")):
                status, icon = "COMPLETED", "✅"
            else:
                status, icon = "STOPPED", "⏹"

            msg = f"{icon} FT {status}: <b>{_h(label)}</b> (pid={pid})"
            if last_line:
                msg += f"\nLast log: <code>{_h(last_line[:300])}</code>"

            if _app is not None:
                for cid in OWNER_CHAT_IDS:
                    try:
                        await _app.bot.send_message(cid, msg, parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
        except Exception as exc:
            log.debug("ft_process_watcher: %s", exc)


def _maybe_trigger_heavy_warm(update: Update) -> None:
    """
    Fire-and-forget warm-up when a new user request arrives.
    Uses cooldown to avoid excessive repeated warm requests.
    """
    global _last_heavy_warm_ts
    if not WARM_HEAVY_ON_REQUEST:
        return
    if update.effective_user is None or update.message is None:
        return
    now = time.time()
    with _heavy_warm_lock:
        if now - _last_heavy_warm_ts < WARM_HEAVY_COOLDOWN_SEC:
            return
        _last_heavy_warm_ts = now
    try:
        asyncio.get_running_loop().create_task(asyncio.to_thread(_warm_heavy_model_now))
    except Exception:
        pass


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled exception for update %s", update, exc_info=context.error)


def _h(text: str) -> str:
    """Escape for Telegram HTML parse mode."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_status(statuses: dict[str, dict]) -> str:
    if not statuses:
        return "Нет данных"
    lines = []
    for svc, info in sorted(statuses.items()):
        s    = info.get("status", "?")
        icon = "🟢" if s == "running" else ("🔴" if s == "exited" else "🟡")
        health = info.get("health", "N/A")
        h_tag  = f" [{_h(health)}]" if health not in ("N/A", "healthy", "") else ""
        oom    = " ⚠️OOM" if info.get("oom_killed") else ""
        lines.append(f"{icon} <code>{_h(svc)}</code> — {_h(s)}{h_tag}{oom}")
    return "\n".join(lines)


def _alert_keyboard(service: str, inc_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Рестарт",   callback_data=f"restart:{service}"),
        InlineKeyboardButton("🔍 Диагноз",   callback_data=f"diagnose:{service}:{inc_id}"),
        InlineKeyboardButton("🔇 Игнор 30м", callback_data=f"silence:{service}:30"),
    ]])


async def _trigger_repairman(ev: MonitorEvent) -> None:
    """Fire-and-forget: ask RepairmanAPI to inspect or repair on critical events."""
    mode = "repair" if ev.severity == "critical" else "inspect"
    task = (
        f"[Argus] {ev.event_type} on {ev.service}: {ev.message[:400]}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{REPAIRMAN_URL}/trigger",
                json={"task": task, "mode": mode, "source": "argus_agent"},
                headers={"Authorization": f"Bearer {AIMS_SERVICE_TOKEN}"},
            )
            log.info("repairman triggered: status=%s mode=%s service=%s", resp.status_code, mode, ev.service)
    except Exception as exc:
        log.warning("repairman trigger failed: %s", exc)


async def _send_alert(app: Application, ev: MonitorEvent) -> None:
    icon = "🚨" if ev.severity == "critical" else "⚠️"
    text = f"{icon} <b>{_h(ev.service)}</b> — {_h(ev.event_type)}\n{_h(ev.message)}"
    if ev.log_snippet:
        snippet = ev.log_snippet[-600:]
        text += f"\n<pre>{_h(snippet)}</pre>"
    kb = _alert_keyboard(ev.service, ev.inc_id)
    for cid in OWNER_CHAT_IDS:
        try:
            await app.bot.send_message(cid, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as exc:
            log.warning("send_alert to %s: %s", cid, exc)

    if AUTO_RESTART and ev.event_type in ("crash", "oom"):
        attempted, msg = await asyncio.to_thread(monitor.maybe_auto_restart, ev.service)
        if attempted:
            note = f"🔄 Авто-рестарт <code>{_h(ev.service)}</code>: {'✅' if 'ok' in msg else '❌'} {_h(msg[:100])}"
            for cid in OWNER_CHAT_IDS:
                try:
                    await app.bot.send_message(cid, note, parse_mode=ParseMode.HTML)
                except Exception:
                    pass

    if ev.severity in ("critical", "warning"):
        asyncio.ensure_future(_trigger_repairman(ev))


async def _alert_consumer(app: Application) -> None:
    while True:
        try:
            ev = await asyncio.wait_for(_alert_queue.get(), timeout=5.0)
            await _send_alert(app, ev)
        except asyncio.TimeoutError:
            continue
        except Exception:
            log.exception("alert_consumer error")


# ── Task registry helpers ──────────────────────────────────────────────────────

def _tasks_fetch(stuck_only: bool) -> list[dict]:
    """HTTP query to task-registry API. Runs in thread."""
    try:
        if stuck_only:
            url = f"{TASK_REG_URL}/tasks/stuck?older_than_minutes=15"
        else:
            url = f"{TASK_REG_URL}/tasks?limit=25"
        r = httpx.get(url, timeout=5.0)
        if r.status_code == 200:
            return r.json().get("tasks", [])
    except Exception as exc:
        log.debug("tasks_fetch: %s", exc)
    return []


def _fmt_tasks(rows: list[dict], stuck_only: bool) -> str:
    if not rows:
        return "Нет задач ✅" if stuck_only else "Реестр пуст"
    lines = []
    for r in rows:
        ts = ""
        for tf in ("created_at", "updated_at"):
            v = r.get(tf)
            if v:
                try:
                    ts = datetime.fromisoformat(str(v)).strftime("%m-%d %H:%M")
                    break
                except Exception:
                    ts = str(v)[:16]
        status  = r.get("status", "?")
        source  = r.get("source", r.get("agent", "?"))
        title   = (r.get("description") or r.get("title") or "")[:55]
        tid     = r.get("task_id") or r.get("id") or "?"
        lines.append(f"[{status}] {source} #{str(tid)[:12]} — {title} ({ts})")
    return "\n".join(lines)


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Start", callback_data="start_heavy")
    ]])
    reply_kb = ReplyKeyboardMarkup(
        [[KeyboardButton("🚀 Start")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
    await update.message.reply_text(
        "👁 <b>Argus</b> — AIMS Infrastructure Watchdog\n\n"
        "Мониторинг контейнеров, Ollama VRAM, реестра задач и расписания.\n"
        "Нажми <b>Start</b>: пока грузится большая модель, отвечаю малой.\n"
        "Используй /help для списка команд.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    await update.message.reply_text(
        "Кнопка быстрого старта закреплена снизу 👇",
        reply_markup=reply_kb,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    text = (
        "<b>Argus — команды</b>\n\n"
        "<b>Статус</b>\n"
        "/status — все контейнеры\n"
        "/models [node] — VRAM всех узлов\n"
        "/installed [node] — установленные модели\n"
        "/tasks [stuck] — реестр задач\n"
        "/incidents [N] [svc] — последние инциденты\n\n"
        "<b>Контейнеры</b>\n"
        "/restart &lt;name&gt; — перезапустить контейнер (без пересборки)\n"
        "/rebuild &lt;name&gt; [no_cache] — пересобрать образ + запустить\n"
        "/stop &lt;name&gt; — остановить контейнер\n"
        "/up &lt;name&gt; — запустить контейнер\n"
        "/logs &lt;name&gt; [N] — последние N строк лога\n\n"
        "<b>Модели Ollama</b>\n"
        "/load &lt;model&gt; [node] — загрузить в VRAM\n"
        "/unload &lt;model&gt; [node] — выгрузить из VRAM\n"
        "/pull &lt;model&gt; [node] — скачать модель\n"
        "/delete &lt;model&gt; [node] — удалить с диска узла\n\n"
        "<b>FT (fine-tuning)</b>\n"
        "/ft &lt;14|32|70|72&gt; — проверить готовность тюнинга и ночной шаг\n"
        "/ft &lt;14|32|70|72&gt; run — запустить сейчас (после подтверждения кнопкой)\n"
        "/ft log [14|70|72|qwen3] — хвост лога тренировки\n"
        "/ft download — прогресс загрузок HF-моделей\n\n"
        "<b>Eval и деплой</b>\n"
        "/eval &lt;candidate&gt; [baseline] — A/B сравнение по golden_v2 suite\n"
        "/deploy &lt;model&gt; [andrei] — перенести модель с DGX на PC Andrei\n\n"
        "<b>Контроль кода</b>\n"
        "/code status — git статус + последние коммиты\n"
        "/code review [diff_chars] — AI review текущего diff\n\n"
        "/code ask &lt;запрос&gt; — Claude Code read-only (план/анализ)\n"
        "/code run &lt;запрос&gt; — Claude Code с правом изменений (только owner)\n\n"
        "<b>Разговорный режим</b>\n"
        "Пиши Argus обычным текстом в личке.\n"
        "В группе: префикс <code>argus ...</code> или упоминание бота.\n\n"
        "<b>Диагностика</b>\n"
        "/diagnose &lt;svc&gt; — AI-анализ последних ошибок\n"
        "/test [svc] — smoke в контейнере (дефолт omi-bot); в конце вывода строка ARGUS_SUMMARY\n"
        "/plan run smoke_night_now — тот же smoke через план (скрипт compose exec)\n"
        "/plan run ft_status_snapshot — артефакты ops/ft/output без GPU\n\n"
        "/plan run weekly_model_upgrade — принудительный недельный апгрейд FT-моделей\n\n"
        "/plan run weekly_model_consistency_check — сверка DGX vs PC по FT-тегам\n\n"
        "<b>Keepalive (контейнеры по требованию)</b>\n"
        "/keepalive — статус управляемых контейнеров\n"
        "/wake &lt;name&gt; — запустить контейнер (сбросить таймер)\n"
        "/sleep &lt;name&gt; — остановить вручную\n\n"
        "<b>Конфигурация</b>\n"
        "/env &lt;svc&gt; — переменные окружения сервиса\n"
        "/set &lt;svc&gt; KEY=value — изменить .env + рестарт\n"
        "/silence &lt;svc&gt; [мин] — заглушить алерты\n"
        "/unsilence &lt;svc&gt; — снять заглушку\n"
        "/silences — список активных заглушек"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    statuses = await asyncio.to_thread(docker_mgr.get_status)
    text = (
        f"<b>Статус контейнеров</b> ({datetime.now().strftime('%H:%M:%S')})\n\n"
        f"{_fmt_status(statuses)}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_models(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    node = ctx.args[0].upper() if ctx.args else None
    if node:
        url = ollama_mgr.node_url(node)
        if not url:
            await update.message.reply_text(f"Узел <b>{_h(node)}</b> не настроен", parse_mode=ParseMode.HTML)
            return
        # Single-node full status
        tmp_mgr = OllamaManager()
        tmp_mgr._urls = {node: url}
        text = await asyncio.to_thread(tmp_mgr.full_status_summary)
    else:
        text = await asyncio.to_thread(ollama_mgr.full_status_summary)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_installed(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    node = ctx.args[0].upper() if ctx.args else None
    text = await asyncio.to_thread(ollama_mgr.installed_summary, node)
    await update.message.reply_text(
        f"<b>Установленные модели</b>\n\n{_h(text)}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /logs &lt;service&gt; [N]", parse_mode=ParseMode.HTML)
        return
    svc = ctx.args[0]
    n   = min(int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 80, 300)
    await update.message.chat.send_action(ChatAction.TYPING)
    logs = await asyncio.to_thread(docker_mgr.get_logs, svc, n)
    if not logs:
        await update.message.reply_text(f"Нет логов для <code>{_h(svc)}</code>", parse_mode=ParseMode.HTML)
        return
    chunk = logs[-3500:]
    await update.message.reply_text(f"<b>Логи {_h(svc)}</b>\n<pre>{_h(chunk)}</pre>", parse_mode=ParseMode.HTML)


async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /restart &lt;service&gt;", parse_mode=ParseMode.HTML)
        return
    svc = ctx.args[0]
    await update.message.chat.send_action(ChatAction.TYPING)
    ok, msg = await asyncio.to_thread(docker_mgr.restart, svc)
    await asyncio.to_thread(storage.log_action, svc, "restart", "ok" if ok else msg[:100])
    icon = "✅" if ok else "❌"
    await update.message.reply_text(
        f"{icon} restart <code>{_h(svc)}</code>\n<pre>{_h(msg[:600])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_rebuild(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /rebuild &lt;service&gt; [no_cache]", parse_mode=ParseMode.HTML)
        return
    svc      = ctx.args[0]
    no_cache = "no_cache" in (ctx.args[1:] or [])
    await update.message.reply_text(
        f"🔨 Пересборка <code>{_h(svc)}</code>… (до 10 мин)",
        parse_mode=ParseMode.HTML,
    )
    ok, msg = await asyncio.to_thread(docker_mgr.rebuild, svc, no_cache)
    await asyncio.to_thread(storage.log_action, svc, "rebuild", "ok" if ok else msg[:100])
    icon = "✅" if ok else "❌"
    await update.message.reply_text(
        f"{icon} rebuild <code>{_h(svc)}</code>\n<pre>{_h(msg[-800:])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Использование: /stop &lt;service&gt;\n"
            "Для выгрузки модели из VRAM: /stop &lt;node&gt; [model]  или  /unload &lt;model&gt; [node]\n"
            "Примеры: <code>/stop PC_ANDREI</code>  <code>/stop DGX 72b</code>  <code>/unload small</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # If first arg is a known Ollama node name → route to unload, not docker stop
    first = ctx.args[0].rstrip(":").upper()
    if first in _KNOWN_NODES:
        model, node = _parse_model_node(ctx.args)
        node = node or first
        # If no model specified, unload ALL loaded models on that node
        if not model:
            url = ollama_mgr.node_url(node)
            if not url:
                await update.message.reply_text(f"❌ Узел <code>{_h(node)}</code> недоступен", parse_mode=ParseMode.HTML)
                return
            loaded = await asyncio.to_thread(ollama_mgr.get_ps, url)
            if not loaded:
                await update.message.reply_text(f"⚪ <code>{_h(node)}</code>: VRAM уже свободен", parse_mode=ParseMode.HTML)
                return
            await update.message.chat.send_action(ChatAction.TYPING)
            results = []
            for m in loaded:
                mname = m.get("name", "")
                ok, msg = await asyncio.to_thread(ollama_mgr.unload_model, mname, node)
                results.append(f"{'✅' if ok else '❌'} {_h(mname)}: {_h(msg)}")
            await update.message.reply_text(
                f"🔻 Выгрузка с <code>{_h(node)}</code>:\n" + "\n".join(results),
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.chat.send_action(ChatAction.TYPING)
            ok, msg = await asyncio.to_thread(ollama_mgr.unload_model, model, node)
            icon = "✅" if ok else "❌"
            await update.message.reply_text(f"{icon} {_h(msg)}", parse_mode=ParseMode.HTML)
        return

    # Default: Docker container stop
    svc = ctx.args[0]
    await update.message.chat.send_action(ChatAction.TYPING)
    ok, msg = await asyncio.to_thread(docker_mgr.stop, svc)
    icon = "✅" if ok else "❌"
    await update.message.reply_text(
        f"{icon} stop <code>{_h(svc)}</code>\n<pre>{_h(msg[:400])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_up(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /up &lt;service&gt;", parse_mode=ParseMode.HTML)
        return
    svc = ctx.args[0]
    await update.message.chat.send_action(ChatAction.TYPING)
    ok, msg = await asyncio.to_thread(docker_mgr.start, svc)
    icon = "✅" if ok else "❌"
    await update.message.reply_text(
        f"{icon} up <code>{_h(svc)}</code>\n<pre>{_h(msg[:400])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_load(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Использование: /load &lt;model&gt; [node]\nnode: DGX | SPARK | PC_ANDREI",
            parse_mode=ParseMode.HTML,
        )
        return
    model, node = _parse_model_node(ctx.args)
    if not model:
        await update.message.reply_text(
            "Использование: /load &lt;model&gt; [node]\n"
            "Примеры: <code>/load small</code>  <code>/load qwen DGX</code>  <code>/load PC_ANDREI: small</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    node_label = f" → {node}" if node else ""
    await update.message.reply_text(f"⏳ Загружаю <code>{_h(model)}</code>{_h(node_label)}…", parse_mode=ParseMode.HTML)
    ok, msg = await asyncio.to_thread(ollama_mgr.load_model, model, node)
    icon = "✅" if ok else "❌"
    await update.message.reply_text(f"{icon} {_h(msg)}", parse_mode=ParseMode.HTML)


async def cmd_unload(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Использование: /unload &lt;model&gt; [node]",
            parse_mode=ParseMode.HTML,
        )
        return
    model, node = _parse_model_node(ctx.args)
    if not model:
        await update.message.reply_text(
            "Использование: /unload &lt;model&gt; [node]\n"
            "Примеры: <code>/unload small</code>  <code>/unload 72b DGX</code>  <code>/unload PC_ANDREI small</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    node_label = f" ({node})" if node else ""
    await update.message.chat.send_action(ChatAction.TYPING)
    ok, msg = await asyncio.to_thread(ollama_mgr.unload_model, model, node)
    icon = "✅" if ok else "❌"
    await update.message.reply_text(f"{icon} {_h(msg)}", parse_mode=ParseMode.HTML)


async def cmd_pull(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Использование: /pull &lt;model&gt; [node]",
            parse_mode=ParseMode.HTML,
        )
        return
    model, node = _parse_model_node(ctx.args)
    if not model:
        await update.message.reply_text(
            "Использование: /pull &lt;model&gt; [node]",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        f"⬇️ Скачиваю <code>{_h(model)}</code>… (до 10 мин)",
        parse_mode=ParseMode.HTML,
    )
    ok, msg = await asyncio.to_thread(ollama_mgr.pull_model, model, node)
    icon = "✅" if ok else "❌"
    await update.message.reply_text(
        f"{icon} pull <code>{_h(model)}</code>\n<pre>{_h(msg[:500])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a model from disk on the specified node."""
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Использование: /delete &lt;model&gt; [node]\n"
            "Пример: /delete qwen2.5:72b-instruct-q4_K_M PC_ANDREI",
            parse_mode=ParseMode.HTML,
        )
        return
    model, node = _parse_model_node(ctx.args)
    if not model:
        await update.message.reply_text(
            "Использование: /delete &lt;model&gt; [node]",
            parse_mode=ParseMode.HTML,
        )
        return

    node_label = f" на {node}" if node else ""
    await update.message.reply_text(
        f"🗑 Удаляю <code>{_h(model)}</code>{node_label}…",
        parse_mode=ParseMode.HTML,
    )
    await update.message.chat.send_action(ChatAction.TYPING)
    ok, msg = await asyncio.to_thread(ollama_mgr.delete_model, model, node)
    icon = "✅" if ok else "❌"
    await update.message.reply_text(f"{icon} {_h(msg)}", parse_mode=ParseMode.HTML)


async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    stuck_only = bool(ctx.args and ctx.args[0] == "stuck")
    rows = await asyncio.to_thread(_tasks_fetch, stuck_only)
    text = _fmt_tasks(rows, stuck_only)
    header = "⏳ Зависшие задачи" if stuck_only else "📋 Реестр задач (последние 25)"
    await update.message.reply_text(
        f"<b>{header}</b>\n<pre>{_h(text)}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_incidents(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    limit = 10
    svc   = None
    for arg in (ctx.args or []):
        if arg.isdigit():
            limit = min(int(arg), 50)
        else:
            svc = arg
    rows = await asyncio.to_thread(storage.get_recent, limit, svc)
    if not rows:
        await update.message.reply_text("Нет инцидентов ✅")
        return
    lines = []
    for r in rows:
        ts   = datetime.fromtimestamp(r["created_at"]).strftime("%m-%d %H:%M")
        icon = "✅" if r["resolved"] else "🔴"
        lines.append(f"{icon} #{r['id']} {r['service']} [{r['inc_type']}] {r['message'][:60]} ({ts})")
    await update.message.reply_text(
        "<b>Инциденты</b>\n<pre>" + _h("\n".join(lines)) + "</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_diagnose(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /diagnose &lt;service&gt;", parse_mode=ParseMode.HTML)
        return
    svc = ctx.args[0]
    await update.message.reply_text(f"🔍 Анализирую <code>{_h(svc)}</code>…", parse_mode=ParseMode.HTML)
    await update.message.chat.send_action(ChatAction.TYPING)

    logs    = await asyncio.to_thread(docker_mgr.get_logs, svc, 150)
    recent  = await asyncio.to_thread(storage.get_recent, 5, svc)
    context = "; ".join(r["message"] for r in recent[:3]) if recent else ""

    ollama_url, ollama_node = await asyncio.to_thread(ollama_mgr.pick_small_model_url)
    diag_text, backend = await asyncio.to_thread(
        _diag.diagnose,
        svc,
        "manual_request",
        logs,
        context,
        ollama_url,
        os.environ.get("ARGUS_LOCAL_DIAG_MODEL", ""),
    )
    text = (
        f"🔍 <b>Диагноз: {_h(svc)}</b>\n"
        f"<i>Бэкенд: {_h(backend)}</i>\n\n"
        f"{_h(diag_text)}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    svc = ctx.args[0] if ctx.args else "omi-bot"
    await update.message.reply_text(f"🧪 Запускаю smoke-тест для <code>{_h(svc)}</code>…", parse_mode=ParseMode.HTML)
    await update.message.chat.send_action(ChatAction.TYPING)

    import subprocess
    def _run_test():
        r = subprocess.run(
            [
                "docker", "compose",
                "-f", os.environ.get("ARGUS_COMPOSE_FILE", "/workspace/docker-compose.yml"),
                "-p", os.environ.get("ARGUS_COMPOSE_PROJECT", "axiomsphere"),
                "exec", "-T", svc,
                "python", "/omi_telegram/omi_night_smoke.py",
            ],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode, (r.stdout + r.stderr)[-2800:]

    rc, out = await asyncio.to_thread(_run_test)
    icon = "✅" if rc == 0 else "❌"
    await update.message.reply_text(
        f"{icon} smoke test <code>{_h(svc)}</code>\n<pre>{_h(out)}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_env(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /env &lt;service&gt;", parse_mode=ParseMode.HTML)
        return
    svc      = ctx.args[0]
    env_text = await asyncio.to_thread(docker_mgr.show_env, svc)
    await update.message.reply_text(
        f"<b>ENV {_h(svc)}</b>\n<pre>{_h(env_text[:2000])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text("Использование: /set &lt;service&gt; KEY=value", parse_mode=ParseMode.HTML)
        return
    svc = ctx.args[0]
    kv  = " ".join(ctx.args[1:])
    if "=" not in kv:
        await update.message.reply_text("Формат: KEY=value")
        return
    key, _, value = kv.partition("=")
    env_file      = os.environ.get("ARGUS_ENV_FILE", "/workspace/.env")
    await update.message.chat.send_action(ChatAction.TYPING)
    ok, msg = await asyncio.to_thread(
        docker_mgr.set_env_and_restart, svc, env_file, key.strip(), value.strip()
    )
    icon = "✅" if ok else "❌"
    await update.message.reply_text(
        f"{icon} <code>{_h(kv)}</code>\n<pre>{_h(msg[:500])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_silence(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /silence &lt;service&gt; [minutes]", parse_mode=ParseMode.HTML)
        return
    svc  = ctx.args[0]
    mins = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 30
    await asyncio.to_thread(storage.silence, svc, mins)
    await update.message.reply_text(
        f"🔇 Алерты для <code>{_h(svc)}</code> заглушены на {mins} мин",
        parse_mode=ParseMode.HTML,
    )


async def cmd_unsilence(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /unsilence &lt;service&gt;", parse_mode=ParseMode.HTML)
        return
    await asyncio.to_thread(storage.unsilence, ctx.args[0])
    await update.message.reply_text(
        f"🔔 Алерты для <code>{_h(ctx.args[0])}</code> восстановлены",
        parse_mode=ParseMode.HTML,
    )


async def cmd_silences(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    rows = await asyncio.to_thread(storage.list_silences)
    if not rows:
        await update.message.reply_text("Нет активных заглушек ✅")
        return
    lines = [
        f"🔇 {r['service']} до {datetime.fromtimestamp(r['until_ts']).strftime('%H:%M')}"
        for r in rows
    ]
    await update.message.reply_text("\n".join(lines))


# ── Keepalive commands ─────────────────────────────────────────────────────────

async def cmd_wake(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        managed = sorted(ka_mgr.managed)
        await update.message.reply_text(
            "<b>/wake — управляемые контейнеры</b>\n\n"
            "Использование: /wake &lt;name&gt;\n\n"
            "Управляемые (keepalive):\n" +
            "\n".join(f"  • {s}" for s in managed) +
            f"\n\nTTL: {int(os.environ.get('ARGUS_KEEPALIVE_TTL_SEC', 3600)) // 60} мин",
            parse_mode=ParseMode.HTML,
        )
        return
    svc = ctx.args[0]
    await update.message.chat.send_action(ChatAction.TYPING)
    started, msg = await asyncio.to_thread(ka_mgr.ping, svc)
    icon = "▶️" if started else "✅"
    await update.message.reply_text(f"{icon} {_h(msg)}", parse_mode=ParseMode.HTML)


async def cmd_sleep(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Использование: /sleep &lt;name&gt; — остановить контейнер вручную",
            parse_mode=ParseMode.HTML,
        )
        return
    svc = ctx.args[0]
    await update.message.chat.send_action(ChatAction.TYPING)
    ok, msg = await asyncio.to_thread(docker_mgr.stop, svc)
    icon = "⏹" if ok else "❌"
    await update.message.reply_text(
        f"{icon} stop <code>{_h(svc)}</code>\n<pre>{_h(msg[:300])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_keepalive(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    rows = await asyncio.to_thread(ka_mgr.get_status)

    # get current running status for each managed container
    try:
        all_s = await asyncio.to_thread(docker_mgr.get_status)
    except Exception:
        all_s = {}

    lines = []
    for r in rows:
        svc    = r["service"]
        status = all_s.get(svc, {}).get("status", "?")
        icon   = "🟢" if status == "running" else "⚫"
        if r["idle_sec"] is not None:
            lines.append(f"{icon} <code>{_h(svc)}</code> — {r['expires_in']} до стопа")
        else:
            lines.append(f"{icon} <code>{_h(svc)}</code> — ожидает вызова")

    ttl_min = int(os.environ.get("ARGUS_KEEPALIVE_TTL_SEC", 3600)) // 60
    text = (
        f"<b>Keepalive-контейнеры</b> (TTL {ttl_min} мин)\n\n" +
        ("\n".join(lines) or "Нет управляемых контейнеров") +
        "\n\n/wake &lt;name&gt; — запустить   /sleep &lt;name&gt; — остановить"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── Orchestrator commands ──────────────────────────────────────────────────────

async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /plan            — show loaded steps and last-run times
    /plan reload     — reload plan YAML files from disk
    /plan run <id>   — manually fire a step by id
    /plan digest     — send morning digest now
    """
    if not _allowed(update):
        return
    args = ctx.args or []

    if not args:
        text = await asyncio.to_thread(orchestrator.status_text)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    sub = args[0].lower()

    if sub == "reload":
        n = await asyncio.to_thread(orchestrator.reload_plans)
        await update.message.reply_text(f"✅ Планы перезагружены: {n} шагов")
        return

    if sub == "digest":
        text = await asyncio.to_thread(orchestrator.send_digest_now)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    if sub == "run" and len(args) >= 2:
        step_id = args[1]
        try:
            await update.message.reply_text(
                f"▶️ Запускаю <code>{_h(step_id)}</code>…",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            # Telegram network glitches should not block actual step execution.
            log.warning("cmd_plan pre-reply failed for step %s: %s", step_id, e)
        result = await asyncio.to_thread(orchestrator.run_step_now, step_id)
        try:
            await update.message.reply_text(result, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("cmd_plan result reply failed for step %s: %s", step_id, e)
        return

    await update.message.reply_text(
        "Использование:\n"
        "/plan — статус\n"
        "/plan reload — перезагрузить планы\n"
        "/plan run &lt;step_id&gt; — запустить вручную\n"
        "/plan digest — дайджест прямо сейчас",
        parse_mode=ParseMode.HTML,
    )


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/digest — send morning digest immediately."""
    if not _allowed(update):
        return
    text = await asyncio.to_thread(orchestrator.send_digest_now)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_train(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/train — training management menu.

    /train          — show dataset status + launch buttons
    /train status   — dataset counts only (no buttons)
    /train v7       — start v7 routing fine-tune (requires approval)
    /train gen      — start gen-v1 72B fine-tune (requires approval)
    /train night    — run tonight's training pipeline right now
    """
    if not _allowed(update):
        return

    args = ctx.args or []
    sub = args[0].lower() if args else ""

    # ── Dataset status (shared) ────────────────────────────────────
    def _read_dataset_status() -> dict:
        import json
        result = {"v7": 0, "gen_v1": 0, "docs_total": 0, "last_ingest": "—"}
        ws = os.environ.get("AIMS_WORKSPACE", "/workspace")
        for key, path in (
            ("v7",     f"{ws}/data/training/v7_routing_pairs.jsonl"),
            ("gen_v1", f"{ws}/data/training/gen_v1_pairs.jsonl"),
        ):
            try:
                with open(path) as f:
                    result[key] = sum(1 for line in f if line.strip())
            except FileNotFoundError:
                pass
        try:
            import sqlite3
            db = os.environ.get("OMI_DB_PATH", f"{ws}/aims_registry.db")
            conn = sqlite3.connect(db, timeout=5)
            row = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE is_training_example=1"
            ).fetchone()
            result["docs_total"] = row[0] if row else 0
            row2 = conn.execute(
                "SELECT MAX(date_added) FROM documents WHERE is_training_example=1"
            ).fetchone()
            if row2 and row2[0]:
                result["last_ingest"] = str(row2[0])[:16]
            conn.close()
        except Exception:
            pass
        return result

    st = await asyncio.to_thread(_read_dataset_status)

    v7_ready  = st["v7"] >= 200
    gen_ready = st["gen_v1"] >= 100
    v7_icon   = "✅" if v7_ready  else f"⏳ {st['v7']}/200"
    gen_icon  = "✅" if gen_ready else f"⏳ {st['gen_v1']}/100"

    status_text = (
        f"🧠 <b>Training Dashboard</b>\n\n"
        f"📚 Обучающих документов в БД: <b>{st['docs_total']}</b>\n"
        f"   Последний инжест: {st['last_ingest']}\n\n"
        f"<b>Датасеты:</b>\n"
        f"  v7 routing pairs:   {v7_icon}\n"
        f"  gen-v1 pairs (72B): {gen_icon}\n\n"
        f"<b>Как добавлять документы:</b>\n"
        f"  Клади файлы в <code>inbox/training/</code>\n"
        f"  Ночью (00:01) Omi обработает автоматически"
    )

    if sub == "status":
        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)
        return

    if sub == "v7":
        step = next((s for s in orchestrator._steps if s.id == "ft_v7_routing"), None)
        if step is None:
            await update.message.reply_text("❌ Шаг ft_v7_routing не найден в плане")
            return
        if st["v7"] < 50:
            await update.message.reply_text(
                f"⚠️ Мало данных для обучения: {st['v7']} пар (нужно мин. 50).\n"
                f"Продолжить всё равно? /plan run ft_v7_routing",
                parse_mode=ParseMode.HTML,
            )
            return
        await asyncio.to_thread(orchestrator._request_approval, step)
        await update.message.reply_text("🔐 Запрос на запуск v7 отправлен — подтверди кнопкой выше")
        return

    if sub == "gen":
        await update.message.reply_text(
            f"⚠️ gen-v1 (72B) обучение доступно когда:\n"
            f"  • Qwen2.5-72B скачан и запущен\n"
            f"  • Накоплено ≥100 пар (сейчас: {st['gen_v1']})\n\n"
            f"Статус 72B: /models\n"
            f"Когда будет готово — используй: /train gen",
            parse_mode=ParseMode.HTML,
        )
        return

    if sub == "night":
        # Trigger tonight's training pipeline immediately
        steps_to_run = ["training_ingest_new_docs", "training_generate_pairs", "training_dataset_status"]
        fired = []
        for sid in steps_to_run:
            step = next((s for s in orchestrator._steps if s.id == sid), None)
            if step:
                ok, detail = await asyncio.to_thread(orchestrator._execute_action, step)
                fired.append(f"{'✅' if ok else '❌'} {sid}")
        result = "\n".join(fired) or "Шаги не найдены"
        await update.message.reply_text(
            f"▶️ <b>Ночной pipeline запущен сейчас</b>\n\n{result}",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── Default: status + action buttons ──────────────────────────
    buttons = []
    if v7_ready:
        buttons.append(InlineKeyboardButton("🚀 Обучить v7 routing", callback_data="train_v7"))
    if gen_ready:
        buttons.append(InlineKeyboardButton("🚀 Обучить gen-v1 (72B)", callback_data="train_gen"))
    buttons.append(InlineKeyboardButton("▶️ Запустить pipeline сейчас", callback_data="train_night"))
    buttons.append(InlineKeyboardButton("📊 Только статус", callback_data="train_status"))

    keyboard = InlineKeyboardMarkup([buttons[:2], buttons[2:]])
    await update.message.reply_text(status_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def cmd_ft(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/ft <14|32|70|72> [run] — FT aliases with readiness check and optional launch."""
    if not _allowed(update):
        return

    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Использование:\n"
            "  /ft <14|32|70|72> [run]    — проверка/запуск тюнинга\n"
            "  /ft log [14|70|72|qwen3]  — хвост лога тренировки\n"
            "  /ft download              — прогресс загрузок HF",
            parse_mode=ParseMode.HTML,
        )
        return

    alias = args[0].strip().lower()

    if alias == "log":
        await cmd_ft_log(update, ctx)
        return

    if alias == "download":
        await cmd_ft_download(update, ctx)
        return

    if alias not in {"14", "32", "70", "72"}:
        await update.message.reply_text("❌ Допустимые клички моделей: 14, 32, 70, 72")
        return

    run_now = len(args) > 1 and args[1].strip().lower() == "run"
    if run_now:
        blocked, reason, snap = await asyncio.to_thread(_thermal_preflight_status)
        if blocked:
            chat_id = update.effective_chat.id if update.effective_chat else 0
            _queue_ft_launch(alias, chat_id, run_now=True)
            await update.message.reply_text(
                "⏸ DGX перегружен, запуск поставлен в очередь до охлаждения.\n"
                f"Причина: <code>{_h(reason)}</code>\n"
                f"CPU: <b>{snap.get('cpu_temp', 0):.1f}°C</b> / load <b>{snap.get('cpu_util', 0):.1f}%</b>\n"
                f"Автовозобновление: ≤{THERMAL_CPU_TEMP_RESUME_C:.0f}°C и ≤{THERMAL_CPU_UTIL_RESUME_PCT:.0f}% "
                f"в течение {THERMAL_RESUME_STABLE_SEC}с.",
                parse_mode=ParseMode.HTML,
            )
            return
    cmd = ["python3", "ops/scripts/argus_ft_skill.py", "--model", alias]
    if run_now:
        cmd.append("--run")

    await update.message.chat.send_action(ChatAction.TYPING)

    def _exec_skill() -> tuple[bool, str]:
        p = subprocess.run(cmd, cwd="/workspace", check=False, capture_output=True, text=True)
        body = (p.stdout or "").strip()
        if p.stderr:
            body = f"{body}\n{p.stderr.strip()}".strip()
        pid = _parse_local_nohup_pid(body)
        if pid:
            global _last_ft_launch_pid, _last_ft_launch_meta
            _last_ft_launch_pid = pid
            _last_ft_launch_meta = {"family": alias, "version": ""}
        return p.returncode == 0, body or "(no output)"

    ok, body = await asyncio.to_thread(_exec_skill)
    if run_now:
        icon = "✅" if ok else "❌"
        await update.message.reply_text(
            f"{icon} <b>FT run now ({_h(alias)})</b>\n<pre>{_h(body[:1800])}</pre>",
            parse_mode=ParseMode.HTML,
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("▶️ Запустить сейчас", callback_data=f"ft_run:{alias}"),
        InlineKeyboardButton("🕒 Только ночью", callback_data=f"ft_night:{alias}"),
    ]])
    icon = "✅" if ok else "⚠️"
    await update.message.reply_text(
        f"{icon} <b>FT check ({_h(alias)})</b>\n<pre>{_h(body[:1800])}</pre>\n"
        f"Запустить этот тюнинг сейчас?",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ── /ft log ───────────────────────────────────────────────────────────────────

_FT_LOG_MAP: dict[str, str] = {
    "14":    "/workspace/ops/ft/logs/train_v7_local_argus.log",
    "70":    "/workspace/ops/ft/logs/train_70_local_argus.log",
    "72":    "/workspace/ops/ft/logs/train_72_local_argus.log",
    "qwen3": "/workspace/ops/ft/logs/train_qwen3_8b_v1.log",
}


async def cmd_ft_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/ft log [14|70|72|qwen3]  — последние 40 строк лога тренировки."""
    if not _allowed(update):
        return

    args = ctx.args or []
    # Called via /ft log qwen3 → args=["log","qwen3"]
    # Called via intent router  → args=["qwen3"] (no "log" prefix)
    if args and args[0].lower() == "log":
        target = args[1].strip().lower() if len(args) > 1 else "qwen3"
    else:
        target = args[0].strip().lower() if args else "qwen3"
    if target not in _FT_LOG_MAP:
        valid = ", ".join(_FT_LOG_MAP)
        await update.message.reply_text(
            f"❌ Неизвестная модель: <code>{_h(target)}</code>. Допустимые: {valid}",
            parse_mode=ParseMode.HTML,
        )
        return

    log_path = _FT_LOG_MAP[target]

    def _read_log() -> tuple[bool, str]:
        import subprocess as sp
        try:
            r = sp.run(["tail", "-n", "40", log_path], capture_output=True, text=True, check=False)
            body = (r.stdout or "").strip()
            if not body:
                return False, f"Лог пустой или не существует: {log_path}"
            return True, body
        except Exception as exc:
            return False, str(exc)

    await update.message.chat.send_action(ChatAction.TYPING)
    ok, body = await asyncio.to_thread(_read_log)
    icon = "📋" if ok else "❌"
    await update.message.reply_text(
        f"{icon} <b>FT log: {_h(target)}</b>\n<pre>{_h(body[-3000:])}</pre>",
        parse_mode=ParseMode.HTML,
    )


# ── /ft download ──────────────────────────────────────────────────────────────

async def cmd_ft_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/ft download  — прогресс загрузок HF-моделей (.incomplete файлы в кэше)."""
    if not _allowed(update):
        return

    def _hf_progress() -> str:
        import glob
        cache = os.path.expanduser("~/.cache/huggingface/hub")
        pattern = os.path.join(cache, "**", "*.incomplete")
        files = glob.glob(pattern, recursive=True)
        if not files:
            return "Нет активных загрузок HF (нет .incomplete файлов в кэше)."
        lines = []
        for f in sorted(files):
            try:
                size_mb = os.path.getsize(f) / 1_048_576
                rel = f.replace(cache + "/", "")
                # Имя оригинального файла — убираем суффикс .incomplete
                orig = rel.replace(".incomplete", "")
                lines.append(f"  {size_mb:>8.1f} MB  {orig}")
            except OSError:
                pass
        return "Загружается:\n" + "\n".join(lines)

    await update.message.chat.send_action(ChatAction.TYPING)
    text = await asyncio.to_thread(_hf_progress)
    await update.message.reply_text(
        f"⬇️ <b>HF Download progress</b>\n<pre>{_h(text)}</pre>",
        parse_mode=ParseMode.HTML,
    )


# ── /eval ─────────────────────────────────────────────────────────────────────

_DEFAULT_EVAL_SUITE = "/workspace/ops/ft/eval/golden_v2.json"
_DEFAULT_EVAL_BASELINE = "qwen2.5-aims-ft-v6"


async def cmd_eval(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/eval <candidate> [baseline]  — A/B сравнение моделей по golden_v2 suite."""
    if not _allowed(update):
        return

    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Использование: /eval <candidate> [baseline]\n"
            f"По умолчанию baseline: {_DEFAULT_EVAL_BASELINE}\n"
            "Пример: /eval qwen3-aims-ft-v1\n"
            "Пример: /eval qwen3-aims-ft-v1 qwen2.5-aims-ft-v6",
            parse_mode=ParseMode.HTML,
        )
        return

    candidate = args[0].strip()
    baseline = args[1].strip() if len(args) > 1 else _DEFAULT_EVAL_BASELINE
    ollama_url = os.environ.get("OLLAMA_LOCAL_URL",
                                os.environ.get("DGX_OLLAMA_URL", "http://127.0.0.1:11434"))
    out_path = f"/workspace/ops/ft/logs/eval_adhoc_{candidate.replace('/', '_')}.json"

    await update.message.reply_text(
        f"⏳ Запускаю eval: <b>{_h(candidate)}</b> vs <b>{_h(baseline)}</b>\n"
        f"Suite: golden_v2 | Это займёт несколько минут…",
        parse_mode=ParseMode.HTML,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    def _run() -> tuple[int, str]:
        import subprocess as sp
        r = sp.run(
            [
                "python3", "ops/ft/scripts/run_eval.py",
                "--ollama-url", ollama_url,
                "--baseline-model", baseline,
                "--candidate-model", candidate,
                "--suite", _DEFAULT_EVAL_SUITE,
                "--out", out_path,
            ],
            cwd="/workspace",
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        stdout = (r.stdout or "").strip()
        stderr = (r.stderr or "").strip()
        combined = "\n".join(filter(None, [stdout, stderr]))
        return r.returncode, combined

    def _summarise(out_file: str) -> str:
        import json as _json
        try:
            data = _json.loads(open(out_file, encoding="utf-8").read())
        except Exception:
            return "(результат не распарсить)"
        cases = data.get("cases", [])
        total = len(cases)
        errors_b = sum(1 for c in cases if (c.get("baseline") or {}).get("raw_error"))
        errors_c = sum(1 for c in cases if (c.get("candidate") or {}).get("raw_error"))
        lat_b = [c["baseline"]["latency_sec"] for c in cases
                 if (c.get("baseline") or {}).get("latency_sec") is not None]
        lat_c = [c["candidate"]["latency_sec"] for c in cases
                 if (c.get("candidate") or {}).get("latency_sec") is not None]
        avg_b = sum(lat_b) / len(lat_b) if lat_b else 0
        avg_c = sum(lat_c) / len(lat_c) if lat_c else 0
        lines = [
            f"Кейсов: {total}",
            f"Baseline  ошибки: {errors_b}  avg_lat: {avg_b:.1f}s",
            f"Candidate ошибки: {errors_c}  avg_lat: {avg_c:.1f}s",
            f"Результат: {out_file}",
        ]
        return "\n".join(lines)

    rc, log = await asyncio.to_thread(_run)
    icon = "✅" if rc == 0 else "❌"
    summary = await asyncio.to_thread(_summarise, out_path) if rc == 0 else ""
    body = f"{icon} <b>Eval завершён</b>\n"
    if summary:
        body += f"<pre>{_h(summary)}</pre>\n"
    if log:
        body += f"<pre>{_h(log[-1500:])}</pre>"
    await update.message.reply_text(body, parse_mode=ParseMode.HTML)


# ── /deploy ───────────────────────────────────────────────────────────────────

async def cmd_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/deploy <model> [andrei]  — перенести модель с DGX Ollama на PC Andrei."""
    if not _allowed(update):
        return

    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Использование: /deploy <model> [andrei]\n"
            "Пример: /deploy qwen3-aims-ft-v1\n"
            "Сейчас поддерживается только узел: andrei (10.77.77.2:11434)",
            parse_mode=ParseMode.HTML,
        )
        return

    model = args[0].strip()
    node = args[1].strip().lower() if len(args) > 1 else "andrei"
    if node not in {"andrei", "pc", "pc_andrei"}:
        await update.message.reply_text(
            f"❌ Неизвестный узел: <code>{_h(node)}</code>. Используй: andrei",
            parse_mode=ParseMode.HTML,
        )
        return

    dgx_url = os.environ.get("DGX_OLLAMA_URL", "http://192.168.72.225:11434").rstrip("/")
    pc_url  = os.environ.get("PC_ANDREY_OLLAMA_URL", "http://10.77.77.2:11434").rstrip("/")

    await update.message.reply_text(
        f"⬆️ Деплой <b>{_h(model)}</b> → PC Andrei…\n"
        f"DGX: {dgx_url} → PC: {pc_url}\n"
        f"Передача блобов по 10Gbps, подождите…",
        parse_mode=ParseMode.HTML,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    def _do_deploy() -> tuple[bool, str]:
        import sys as _sys
        _sys.path.insert(0, "/workspace/ops/scripts")
        try:
            from daily_deploy_14b_to_andrei import (
                _tags, _show_modelfile, _blob_exists, _transfer_blob,
                _create_model, _warm, BLOB_DIGEST_RE,
            )
        except ImportError as exc:
            return False, f"import error: {exc}"

        # Check model exists on DGX
        tags = _tags(dgx_url)
        # match exact name or with :latest suffix
        found = model if model in tags else (f"{model}:latest" if f"{model}:latest" in tags else None)
        if not found:
            return False, (
                f"Модель {model} не найдена на DGX.\n"
                f"Доступно: {', '.join(t for t in tags if 'aims' in t or 'qwen' in t.lower())[:300]}"
            )

        modelfile = _show_modelfile(dgx_url, found)
        if not modelfile:
            return False, f"Не удалось получить modelfile для {found}"

        digests = BLOB_DIGEST_RE.findall(modelfile)
        if not digests:
            return False, "Нет sha256-блобов в modelfile"

        log_lines = [f"Блобов: {len(digests)}"]
        for digest in digests:
            if _blob_exists(pc_url, digest):
                log_lines.append(f"  {digest[:16]}… уже есть на PC")
                continue
            log_lines.append(f"  {digest[:16]}… передаём…")
            ok = _transfer_blob(dgx_url, pc_url, digest)
            if not ok:
                return False, f"Ошибка передачи блоба {digest[:20]}"
            log_lines.append(f"  {digest[:16]}… ОК")

        state = _create_model(pc_url, found, modelfile)
        log_lines.append(f"create_model: {state}")
        if not state.startswith("ok"):
            return False, "\n".join(log_lines)

        warm = _warm(pc_url, found)
        log_lines.append(f"warm: {warm}")
        return True, "\n".join(log_lines)

    ok, detail = await asyncio.to_thread(_do_deploy)
    icon = "✅" if ok else "❌"
    status = "Готово" if ok else "Ошибка"
    await update.message.reply_text(
        f"{icon} <b>Deploy {_h(model)} → andrei: {status}</b>\n<pre>{_h(detail[:2000])}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /code status            — git status + short context
    /code review            — AI review of current git diff
    /code review <chars>    — AI review with custom diff char limit
    /code ask <prompt>      — Claude Code read-only
    /code run <prompt>      — Claude Code with write permissions (owner only)
    """
    if not _allowed(update):
        return

    args = ctx.args or []
    sub = args[0].lower() if args else "status"
    diff_chars = 12000
    if len(args) > 1 and args[1].isdigit():
        diff_chars = max(2000, min(int(args[1]), 24000))

    await update.message.chat.send_action(ChatAction.TYPING)
    code_ctx = await asyncio.to_thread(collect_code_context, CODE_REPO_PATH, diff_chars)

    if sub == "status":
        text = (
            "🧾 <b>Code status</b>\n"
            f"<i>repo: {_h(CODE_REPO_PATH)}</i>\n\n"
            f"<b>git status</b>\n<pre>{_h(code_ctx.status[:1700])}</pre>\n"
            f"<b>recent commits</b>\n<pre>{_h(code_ctx.commits[:1200])}</pre>"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    if sub not in {"review", "ask", "run"}:
        await update.message.reply_text(
            "Usage:\n"
            "/code status\n"
            "/code review [diff_chars]\n"
            "/code ask <request>\n"
            "/code run <request>",
            parse_mode=ParseMode.HTML,
        )
        return

    dgx_url = ollama_mgr.node_url("DGX") or ollama_mgr.node_url("DGX_WIFI") or ollama_mgr.node_url("SPARK")
    if not dgx_url:
        await update.message.reply_text("❌ No available Ollama URL for code review")
        return

    if sub == "review":
        await update.message.reply_text(
            f"🔍 Запускаю code review...\n"
            f"<i>{_h(code_backend_summary(dgx_url, CODE_MODEL))} | backend={_h(LLM_BACKEND)}</i>",
            parse_mode=ParseMode.HTML,
        )
        try:
            prompt = review_prompt(code_ctx)
            review = await asyncio.to_thread(_ask_llm, prompt, CODE_MODEL, dgx_url, 120)
        except Exception as exc:
            await update.message.reply_text(f"❌ Code review failed: {_h(str(exc))}", parse_mode=ParseMode.HTML)
            return

        body = review[:3400]
        await update.message.reply_text(
            f"🧠 <b>Code review</b>\n<pre>{_h(body)}</pre>",
            parse_mode=ParseMode.HTML,
        )
        return

    prompt_text = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if not prompt_text:
        await update.message.reply_text(
            "Provide a request: /code ask <text> or /code run <text>",
            parse_mode=ParseMode.HTML,
        )
        return
    knomi_ctx = _knomi_prefetch_context(prompt_text)
    if knomi_ctx:
        prompt_text = f"{prompt_text}\n\n{knomi_ctx}"

    if LLM_BACKEND != "claude_code":
        await update.message.reply_text(
            "❌ This mode requires ARGUS_LLM_BACKEND=claude_code",
            parse_mode=ParseMode.HTML,
        )
        return

    model = resolve_model_name(CODE_MODEL) if CODE_MODEL else ""
    if not model:
        await update.message.reply_text("❌ ARGUS_CODE_MODEL is not set", parse_mode=ParseMode.HTML)
        return

    if sub == "run" and not _is_owner(update):
        await update.message.reply_text("❌ /code run is owner-only", parse_mode=ParseMode.HTML)
        return

    if sub == "run":
        await update.message.reply_text(
            "🧭 Running pre-change compatibility and risk analysis…",
            parse_mode=ParseMode.HTML,
        )
        analysis_prompt = _build_change_analysis_prompt(prompt_text)
        candidate_models = [
            resolve_model_name(ANALYSIS_MODEL) if ANALYSIS_MODEL else "",
            resolve_model_name(CODE_MODEL) if CODE_MODEL else "",
            resolve_model_name(MEDIUM_MODEL) if MEDIUM_MODEL else "",
            resolve_model_name(CHAT_MODEL) if CHAT_MODEL else "",
        ]
        tried_models: list[str] = []
        analysis = ""
        last_exc: Exception | None = None
        for model_name in candidate_models:
            if not model_name or model_name in tried_models:
                continue
            tried_models.append(model_name)
            try:
                analysis = await asyncio.to_thread(
                    ask_claude_code_headless,
                    dgx_url,
                    model_name,
                    analysis_prompt,
                    CLAUDE_ANALYSIS_TIMEOUT_SEC,
                    "plan",
                    False,
                    None,
                    CLAUDE_CODE_ADD_DIRS,
                )
                model = model_name
                break
            except Exception as exc:
                last_exc = exc
                continue
        if not analysis:
            err_text = str(last_exc) if last_exc else "analysis unavailable"
            await update.message.reply_text(f"❌ Analysis failed: {_h(err_text[:900])}", parse_mode=ParseMode.HTML)
            _knomi_log_event(
                "argus.claude.analysis_error",
                {
                    "mode": sub,
                    "model": model,
                    "error": err_text[:1000],
                    "query": prompt_text[:1000],
                    "candidate_models": tried_models,
                },
            )
            return
        apply_prompt = _build_change_apply_prompt(prompt_text, analysis)
        summary = _approval_summary(prompt_text, model)
        chat_id = update.effective_chat.id if update.effective_chat else 0
        user_id = update.effective_user.id if update.effective_user else 0
        req_id = _put_cc_approval(chat_id, user_id, apply_prompt, model, dgx_url, summary=summary)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"cc_approve:{req_id}"),
                    InlineKeyboardButton("❌ Decline", callback_data=f"cc_deny:{req_id}"),
            ]
        ])
        await update.message.reply_text(
            "✅ Solution prepared.\n"
            "🔐 Approve implementation.\n"
            f"Approval scope: <code>{_h(summary)}</code>\n"
            f"<b>Proposed plan:</b>\n<pre>{_h(_sanitize_chat_answer(analysis)[:2200])}</pre>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        _knomi_log_event(
            "argus.claude.approval_requested",
            {"request_id": req_id, "summary": summary, "query": prompt_text[:1000], "model": model, "analysis": analysis[:2000]},
        )
        return

    permission_mode = "plan"
    dangerously = False
    run_label = "read-only"
    await update.message.reply_text(
        f"🤖 Claude Code: running {run_label} with model <code>{_h(model)}</code>…",
        parse_mode=ParseMode.HTML,
    )
    try:
        out = await asyncio.to_thread(
            ask_claude_code_headless,
            dgx_url,
            model,
            prompt_text,
            240,
            permission_mode,
            dangerously,
            None,
            CLAUDE_CODE_ADD_DIRS,
        )
    except Exception as exc:
        msg = str(exc)
        if sub == "ask" and ("permission" in msg.lower() or "requires approval" in msg.lower()):
            chat_id = update.effective_chat.id if update.effective_chat else 0
            user_id = update.effective_user.id if update.effective_user else 0
            summary = _approval_summary(prompt_text, model)
            req_id = _put_cc_approval(chat_id, user_id, prompt_text, model, dgx_url, summary=summary)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"cc_approve:{req_id}"),
                    InlineKeyboardButton("❌ Decline", callback_data=f"cc_deny:{req_id}"),
                ]
            ])
            await update.message.reply_text(
                "🔐 Claude Code requested write permissions.\n"
                f"Approval scope: <code>{_h(summary)}</code>\n"
                f"Request <code>{_h(req_id)}</code> expires in {CLAUDE_CODE_APPROVAL_TTL_SEC // 60} min.",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            _knomi_log_event(
                "argus.claude.approval_requested",
                {"request_id": req_id, "summary": summary, "query": prompt_text[:1000], "model": model},
            )
            return
        await update.message.reply_text(f"❌ Claude Code error: {_h(msg[:800])}", parse_mode=ParseMode.HTML)
        _knomi_log_event(
            "argus.claude.error",
            {"mode": sub, "model": model, "error": msg[:1000], "query": prompt_text[:1000]},
        )
        return

    clean_out = _sanitize_chat_answer(out)
    await update.message.reply_text(
        f"🧠 <b>Claude Code</b>\n<pre>{_h(clean_out[:3400])}</pre>",
        parse_mode=ParseMode.HTML,
    )
    omi_req = _extract_omi_request(out)
    if omi_req:
        _register_omi_request(f"code.{sub}", prompt_text, omi_req)
        await update.message.reply_text(
                f"📨 Omi request queued:\n<code>{_h(omi_req)}</code>",
            parse_mode=ParseMode.HTML,
        )
    _knomi_log_event(
        "argus.claude.success",
        {"mode": sub, "model": model, "query": prompt_text[:1000], "answer": out[:2000]},
    )


def _chat_prompt(user_text: str, repo_path: str) -> str:
    return (
        "You are Argus, infrastructure and code assistant for the AIMS project.\n"
        "Reply in concise, practical English.\n"
        "For operations/diagnostics, propose safe next actions.\n"
        "If bot commands are useful, mention /status, /models, /plan, /code.\n"
        "You can inspect project system files via add_dirs (/workspace,/ops,/argus).\n"
        "Do not directly operate on Omi/registry SQLite DB files. If Omi action is needed "
        "(tests, tuning, stats, results), output: OMI_REQUEST: <requested operation>.\n"
        "Do not invent facts; if data is missing, state what to verify.\n\n"
        f"Repository context: {repo_path}\n"
        f"User request: {user_text}"
    )


def _chat_context_get(chat_id: int) -> deque[tuple[str, str]]:
    with _chat_ctx_lock:
        d = _chat_context.get(chat_id)
        if d is None:
            d = deque(maxlen=CHAT_CONTEXT_TURNS * 2)
            _chat_context[chat_id] = d
        return d


def _chat_context_clear(chat_id: int) -> None:
    with _chat_ctx_lock:
        _chat_context.pop(chat_id, None)


def _chat_context_add(chat_id: int, role: str, text: str) -> None:
    role_norm = "assistant" if role == "assistant" else "user"
    body = (text or "").strip()
    if not body:
        return
    d = _chat_context_get(chat_id)
    d.append((role_norm, body[:1600]))


def _chat_prompt_with_context(chat_id: int, user_text: str, repo_path: str) -> str:
    base = _chat_prompt(user_text, repo_path)
    d = _chat_context_get(chat_id)
    if not d:
        return base
    hist = []
    for role, body in d:
        hist.append(f"{role}: {body}")
    return (
        base
        + "\n\nКонтекст диалога (последние сообщения):\n"
        + "\n".join(hist[-CHAT_CONTEXT_TURNS * 2 :])
    )


def _should_reply_in_group(update: Update, text: str) -> bool:
    chat = update.effective_chat
    if not chat:
        return False
    if chat.type == "private":
        return True
    t = text.lower().strip()
    if t.startswith("argus ") or t.startswith("аргус "):
        return True
    if t.startswith("claude ") or t.startswith("клод "):
        return True
    if BOT_USERNAME and f"@{BOT_USERNAME.lower()}" in t:
        return True
    return False


def _route_mode(text: str) -> tuple[str, str]:
    """
    Route message intent by explicit prefix.
    Returns (mode, normalized_text):
      - mode: "claude_direct" | "argus"
    """
    raw = (text or "").strip()
    low = raw.lower()
    if low.startswith("claude "):
        return "claude_direct", raw[7:].strip()
    if low.startswith("клод "):
        return "claude_direct", raw[5:].strip()
    if low.startswith("argus "):
        return "argus", raw[6:].strip()
    if low.startswith("аргус "):
        return "argus", raw[6:].strip()
    return "argus", raw


def _chat_candidate_urls() -> list[str]:
    """Ordered candidate Ollama URLs for conversational replies."""
    urls: list[str] = []
    for node in ("DGX", "DGX_WIFI", "SPARK", "PC_ANDREI"):
        u = ollama_mgr.node_url(node)
        if u and u not in urls:
            urls.append(u)
    return urls


def _prefer_loaded_urls(model: str, urls: list[str]) -> list[str]:
    """
    Reorder candidate URLs so nodes with model already loaded are tried first.
    """
    resolved = resolve_model_name(model) if model else ""
    if not resolved:
        return urls
    loaded_first: list[str] = []
    other: list[str] = []
    for u in urls:
        try:
            if ollama_mgr.is_model_loaded(resolved, u):
                loaded_first.append(u)
            else:
                other.append(u)
        except Exception:
            other.append(u)
    return loaded_first + other


def _ask_llm(
    prompt: str,
    model: str,
    url: str,
    timeout_sec: int = 25,
    claude_permission_mode: str = "default",
) -> str:
    """
    Unified LLM call.
    - ollama_api: direct Ollama /api/chat
    - claude_code: Claude Code headless CLI routed to local Ollama endpoint
    """
    requested_model = (model or "").strip()
    model_l = requested_model.lower()
    # Safety rail: keep Argus/Claude runtime on approved model set (32b by default).
    if model_l in RUNTIME_MODEL_BLOCKLIST and MEDIUM_MODEL:
        model = resolve_model_name(MEDIUM_MODEL)
        model_l = model.strip().lower()
    elif model_l in RUNTIME_MODEL_BLOCKLIST and CHAT_MODEL:
        model = resolve_model_name(CHAT_MODEL)
        model_l = model.strip().lower()
    # FT/small conversational models are better via direct Ollama API.
    if "aims-ft" in model_l:
        return ask_local_model(url, model, prompt, timeout_sec=timeout_sec)
    if LLM_BACKEND == "claude_code":
        # Known non-tool models should skip Claude Code path to avoid long waits.
        if model_l in CLAUDE_CODE_UNSUPPORTED_MODELS:
            return ask_local_model(url, model, prompt, timeout_sec=timeout_sec)
        try:
            # Claude Code over local Ollama may need noticeably longer first-token latency.
            return ask_claude_code_headless(
                url,
                model,
                prompt,
                timeout_sec=max(timeout_sec, 240),
                permission_mode=claude_permission_mode,
                add_dirs=CLAUDE_CODE_ADD_DIRS,
            )
        except Exception as exc:
            # Some Ollama models (e.g. deepseek-r1:70b) may not support tool mode
            # required by Claude Code. Fall back to direct /api/chat to keep Argus responsive.
            msg = str(exc)
            if "does not support tools" in msg.lower():
                log.warning("claude_code backend unsupported for model %s, fallback to ollama_api", model)
                return ask_local_model(url, model, prompt, timeout_sec=timeout_sec)
            raise
    return ask_local_model(url, model, prompt, timeout_sec=timeout_sec)


def _ask_chat_with_fallback(
    prompt: str,
    model: str,
    claude_permission_mode: str = "default",
) -> tuple[str | None, str | None]:
    """
    Try chat backend on multiple nodes with short timeout.
    Returns (answer, backend_url) on success, else (None, None).
    """
    # Shared routing parity with Axi/Omi for small model (DGX slot-limit -> PC fallback).
    shared = _import_shared_ollama_resolve()
    if shared is not None:
        try:
            small_model = (shared.small_qwen_model_name() or "").strip().lower()
            req_model = resolve_model_name(model).strip().lower()
            # Route through shared "small model" policy only on exact model match.
            # Prefix match (e.g. qwen2.5) incorrectly catches heavy 72B variants.
            if small_model and req_model and req_model == small_model:
                url, release = shared.small_qwen_ollama_base_url_for_request_with_dgx_concurrency()
                try:
                    ans = _ask_llm(prompt, model, url, timeout_sec=12, claude_permission_mode=claude_permission_mode)
                    if ans:
                        return ans, url
                finally:
                    try:
                        release()
                    except Exception:
                        pass
        except Exception:
            pass

    for url in _prefer_loaded_urls(model, _chat_candidate_urls()):
        try:
            ans = _ask_llm(prompt, model, url, timeout_sec=45, claude_permission_mode=claude_permission_mode)
            if ans:
                return ans, url
        except Exception as exc:
            log.warning("chat backend failed on %s: %s", url, exc)
            continue
    return None, None


def _chat_preflight_hook() -> bool:
    """
    Hook: lightweight pre-check before conversational LLM call.
    Returns True when at least one backend URL is configured.
    """
    return bool(_chat_candidate_urls())


def _chat_answer_skill(
    prompt: str,
    model: str,
    claude_permission_mode: str = "default",
) -> tuple[str | None, str | None]:
    """
    Skill: single reusable entry-point for conversational answer generation.
    """
    if not _chat_preflight_hook():
        return None, None
    return _ask_chat_with_fallback(prompt, model, claude_permission_mode)


def _is_thermal_paused() -> bool:
    with _thermal_state_lock:
        return bool(_thermal_paused)


def _queue_chat_retry(chat_id: int, text: str, route_mode: str, retries: int = 0) -> None:
    _pending_chat_retry_queue.append(
        {
            "chat_id": int(chat_id),
            "text": str(text),
            "route_mode": str(route_mode or "argus"),
            "queued_at": time.time(),
            "retries": int(retries),
        }
    )
    _persist_pending_queues()


async def _resume_queued_chat(chat_id: int, text: str, route_mode: str, retries: int = 0) -> None:
    if _app is None:
        return
    try:
        await _app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass
    model = resolve_model_name(MEDIUM_MODEL or CHAT_MODEL) if (MEDIUM_MODEL or CHAT_MODEL) else ""
    if not model:
        if _app is not None:
            await _app.bot.send_message(chat_id, "❌ Direct model is not configured")
        return
    if route_mode == "claude_direct":
        prompt = (
            "Direct Claude mode. Reply with a direct answer only.\n"
            "Do NOT output pseudo tool calls, code-runner wrappers, or Agent(...) blocks.\n"
            "Read-only by default. If code changes are requested, provide a plan and ask for governed lane approval.\n\n"
            f"Request: {text}"
        )
        knomi_ctx = _knomi_prefetch_context(text)
        if knomi_ctx:
            prompt = f"{prompt}\n\n{knomi_ctx}"
        ans, _ = await asyncio.to_thread(_chat_answer_skill, prompt, model, "plan")
        if not ans:
            if retries < 3:
                _queue_chat_retry(chat_id, text, route_mode, retries=retries + 1)
                await _app.bot.send_message(chat_id, f"⏳ Retry queued ({retries + 1}/3): backend still unavailable.")
            else:
                await _app.bot.send_message(chat_id, "❌ Backend still unavailable after auto-retries.")
            return
        ans = _sanitize_chat_answer(ans)
        _chat_context_add(chat_id, "user", text)
        _chat_context_add(chat_id, "assistant", ans)
        await _app.bot.send_message(chat_id, f"▶️ Resumed after cooldown.\n\n{ans[:3200]}")
        return
    prompt = _chat_prompt_with_context(chat_id, text, CODE_REPO_PATH)
    knomi_ctx = _knomi_prefetch_context(text)
    if knomi_ctx:
        prompt = f"{prompt}\n\n{knomi_ctx}"
    claude_mode = "plan" if LLM_BACKEND == "claude_code" else "default"
    ans, _ = await asyncio.to_thread(_chat_answer_skill, prompt, model, claude_mode)
    if not ans:
        if retries < 3:
            _queue_chat_retry(chat_id, text, route_mode, retries=retries + 1)
            await _app.bot.send_message(chat_id, f"⏳ Retry queued ({retries + 1}/3): backend still unavailable.")
        else:
            await _app.bot.send_message(chat_id, "❌ Backend still unavailable after auto-retries.")
        return
    ans = _sanitize_chat_answer(ans)
    _chat_context_add(chat_id, "user", text)
    _chat_context_add(chat_id, "assistant", ans)
    await _app.bot.send_message(chat_id, f"▶️ Resumed after cooldown.\n\n{ans[:3200]}")


def _sanitize_chat_answer(answer: str) -> str:
    """
    Guard against pseudo-tool-call dumps in user-facing chat replies.
    """
    text = (answer or "").strip()
    if not text:
        return text
    lowered = text.lower()
    suspicious = (
        "agent({",
        "read({",
        "read(",
        "edit(",
        "shell(",
        "let me read the file",
        "let me read the relevant files",
    )
    looks_like_tool_trace = any(token in lowered for token in suspicious)
    if not looks_like_tool_trace:
        # Also catch tool-like plain lines without parentheses, e.g. "Read /path/file".
        if re.search(r"(^|\n)\s*read\s+\/", lowered, flags=re.MULTILINE):
            looks_like_tool_trace = True
        elif re.search(r"(^|\n)\s*agent\s*\(", lowered, flags=re.MULTILINE):
            looks_like_tool_trace = True
    if looks_like_tool_trace:
        return (
            "I am ready to continue. "
            "Send the exact task in one sentence and I will answer directly "
            "without internal tool-call traces."
        )
    return text


def _detect_ft_status_alias(user_text: str) -> str | None:
    """
    Identify strict factual-status requests for FT model aliases.
    """
    t = (user_text or "").lower()
    if not re.search(r"(статус|status|провер|test|тест)", t):
        return None
    m = re.search(r"\b(14|70|72)\b", t)
    if not m:
        return None
    if not re.search(r"(модел|model|ft)", t):
        return None
    return m.group(1)


def _looks_like_write_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    patterns = (
        r"\b(измени|измени|исправь|поправь|обнови|добавь|удали|переименуй)\b",
        r"\b(create|update|edit|modify|delete|rename|refactor|fix)\b",
        r"\b(сделай коммит|закоммить|commit)\b",
        r"\b(примен[ий]|внес[ий])\b.*\b(правк|изменен)\b",
    )
    return any(re.search(p, t) for p in patterns)


def _semantic_intent_label(user_text: str) -> str:
    """
    Lightweight intent classification by semantic meaning (LLM-assisted).
    Returns one of: ft_start | ft_status | code_write | chat | unknown
    Uses the small model (PC_ANDREI) to avoid loading the 32B on DGX for a simple 5-label task.
    """
    text = (user_text or "").strip()
    if not text:
        return "unknown"
    # Small model for cheap classification — keeps DGX 32B free for actual answers
    model = resolve_model_name(SMALL_MODEL) if SMALL_MODEL else ""
    if not model:
        model = resolve_model_name(MEDIUM_MODEL or CODE_MODEL or CHAT_MODEL) if (MEDIUM_MODEL or CODE_MODEL or CHAT_MODEL) else ""
    if not model:
        return "unknown"
    prompt = (
        "Classify the user intent. Return ONLY one label:\n"
        "- ft_start : user wants to start/launch fine tuning (v7/v8/train/tuning)\n"
        "- ft_status: user asks about training status/readiness/results\n"
        "- code_write: user asks to modify files/code\n"
        "- chat: everything else\n\n"
        f"User text: {text}\n"
    )
    # ONLY use SMALL_NODE (PC_ANDREI). Never fall back to DGX — loading a model
    # there during training would spike GPU and trigger thermal guard.
    small_node_url = ollama_mgr.node_url(SMALL_NODE) if SMALL_NODE else None
    if not small_node_url:
        return "unknown"
    candidate_urls = [small_node_url]
    for url in candidate_urls:
        try:
            out = ask_local_model(url, model, prompt, timeout_sec=15).strip().lower()
        except Exception:
            continue
        if "ft_start" in out:
            return "ft_start"
        if "ft_status" in out:
            return "ft_status"
        if "code_write" in out:
            return "code_write"
        if "chat" in out:
            return "chat"
    return "unknown"


def _try_intent_route(text: str) -> tuple[str, list[str]] | None:
    """Classify free text as a known Argus command via local small model. Returns (cmd, args) or None."""
    for p in ("/ops", "/workspace/ops"):
        if p not in sys.path and os.path.isdir(p):
            sys.path.append(p)
    try:
        from chat_intent_router import classify, ARGUS_CMDS  # noqa: PLC0415
        return classify(text, ARGUS_CMDS)
    except Exception:
        return None


def _read_last_nonempty_line(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    for ln in reversed(lines):
        s = ln.strip()
        if s:
            return s
    return ""


def _fetch_dgx_metrics() -> dict[str, float]:
    import urllib.request

    dgx_host = os.environ.get("DGX_OLLAMA_URL", "http://192.168.72.225:11434")
    host = dgx_host.split("//")[-1].split(":")[0]

    def _parse_prometheus(text: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            parts = line.split(" ")
            if len(parts) >= 2:
                name = parts[0].split("{")[0]
                try:
                    out[name] = float(parts[-1])
                except ValueError:
                    pass
        return out

    # Port 9835 — custom exporter (CPU temp, CPU util, GPU fallback)
    metrics: dict[str, float] = {}
    try:
        with urllib.request.urlopen(f"http://{host}:9835/metrics", timeout=5) as r:
            metrics = _parse_prometheus(r.read().decode())
    except Exception:
        pass

    # Port 9400 — NVIDIA DCGM (authoritative GPU temperature)
    try:
        with urllib.request.urlopen(f"http://{host}:9400/metrics", timeout=5) as r:
            dcgm = _parse_prometheus(r.read().decode())
        if "DCGM_FI_DEV_GPU_TEMP" in dcgm:
            metrics["gpu_temperature_celsius"] = dcgm["DCGM_FI_DEV_GPU_TEMP"]
    except Exception:
        pass

    return metrics


def _thermal_preflight_status() -> tuple[bool, str, dict[str, float]]:
    """
    Returns (is_blocked, reason, snapshot) for launch preflight.
    """
    if not THERMAL_GUARD_ENABLED:
        return False, "", {}
    snap: dict[str, float] = {}
    try:
        m = _fetch_dgx_metrics()
    except Exception as exc:
        # Fail-open: don't block launch if telemetry endpoint is temporarily unavailable.
        return False, f"telemetry_unavailable:{type(exc).__name__}", {}
    cpu_temp = float(m.get("cpu_temperature_celsius", 0.0))
    cpu_util = float(m.get("cpu_utilization_percent", 0.0))
    gpu_temp = float(m.get("gpu_temperature_celsius", 0.0))
    snap = {"cpu_temp": cpu_temp, "cpu_util": cpu_util, "gpu_temp": gpu_temp}
    if gpu_temp >= THERMAL_GPU_TEMP_HOT_C:
        return True, f"gpu_hot:{gpu_temp:.0f}C", snap
    # Hot CPU while idle (load<10%) means the system is cooling down — do not block.
    # Block only when hot AND actively loaded, or when util alone is critically high.
    if cpu_temp >= THERMAL_CPU_TEMP_HOT_C and cpu_util >= 10.0:
        return True, f"cpu_hot_active:{cpu_temp:.0f}C/{cpu_util:.0f}%", snap
    if cpu_util >= THERMAL_CPU_UTIL_HIGH_PCT:
        return True, f"cpu_util_high:{cpu_util:.0f}%", snap
    if THERMAL_CPU_TEMP_WARM_C <= cpu_temp < THERMAL_CPU_TEMP_HOT_C and cpu_util >= 85.0:
        return True, "warm_and_busy", snap
    return False, "", snap


def _parse_local_nohup_pid(text: str) -> int | None:
    m = re.search(r"local_nohup pid=(\d+)", text or "", flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _ft_status_factual_reply(alias: str) -> str:
    """
    Produce grounded FT status only from files. No LLM involvement.
    """
    summary = ft_latest_version_summary(alias)
    active = str(summary.get("active_version") or "")
    latest = str(summary.get("latest_version") or "")
    track_type = str(summary.get("track_type") or "text")
    benchmark_profile = str(summary.get("benchmark_profile") or "gemini3_text")
    threshold_policy = summary.get("threshold_policy", {}) if isinstance(summary.get("threshold_policy"), dict) else {}
    decision_info = summary.get("active_decision") or summary.get("latest_decision") or {}
    metrics_info = summary.get("active_metrics") or summary.get("latest_metrics") or {}
    version = active or latest or "v1"
    cp = ft_collect_checkpoints(alias, version)
    paths = ft_version_paths(alias, version)
    log_path = paths["log"]
    log_exists = bool(cp.get("log_exists"))
    last_line = str(cp.get("last_log_line") or "")

    verdict = "нет подтверждённых данных"
    if "missing dependency" in last_line.lower():
        verdict = "ошибка окружения (зависимости не установлены)"
    elif cp.get("status") in {"trained", "evaluated", "approved", "promoted"}:
        verdict = "успешно"
    elif cp.get("status") in {"training", "created"}:
        verdict = "в процессе/запущено"
    elif cp.get("status") in {"failed", "error", "rejected"}:
        verdict = "ошибка"

    lines = [
        f"📌 Фактический статус FT-{alias} ({version}): {verdict}.",
        f"- track: {track_type}",
        f"- benchmark_profile: {benchmark_profile}",
        f"- registry.active_version: {active or '-'}",
        f"- registry.latest_version: {latest or '-'}",
        f"- status: {cp.get('status', 'unknown')}",
    ]
    if threshold_policy:
        lines.append(
            "- threshold_policy: "
            f"min_accept={threshold_policy.get('min_accept')} "
            f"target_similarity={threshold_policy.get('target_similarity_to_benchmark')} "
            f"regression_tolerance={threshold_policy.get('regression_tolerance')}"
        )
    if metrics_info:
        lines.append(
            "- metrics: "
            f"score={metrics_info.get('score', '-')} "
            f"similarity={metrics_info.get('similarity_to_benchmark', '-')}"
        )
    if decision_info:
        lines.append(
            "- decision: "
            f"{decision_info.get('decision', '-')}"
            f" ({decision_info.get('reason', 'no_reason')})"
        )
    if log_exists:
        lines.append(f"- log: {log_path}")
        if last_line:
            lines.append(f"- last_log_line: {last_line[:220]}")
    else:
        lines.append("- log: отсутствует")
    lines.append("Источник: локальные файлы статуса/логов, без генерации LLM.")
    return "\n".join(lines)


def _detect_ft_version_query(user_text: str) -> bool:
    """
    Detect requests about FT version status/readiness like v7/v8.
    """
    t = (user_text or "").lower()
    if not _extract_versions(t):
        return False
    if not re.search(r"(статус|готов|готовность|запуск|test|тест|провер)", t):
        return False
    if not re.search(r"(модел|model|ft|трен|train)", t):
        return False
    return True


def _detect_ft_family(user_text: str) -> str:
    """Best-effort family detection from free text; default 14."""
    t = (user_text or "").lower()
    if re.search(r"\b72\b|v72|модел[ьи]\s*72|model\s*72", t):
        return "72"
    if re.search(r"\b70\b|v70|модел[ьи]\s*70|model\s*70", t):
        return "70"
    if re.search(r"\b32\b|v32|модел[ьи]\s*32|model\s*32", t):
        return "32"
    if re.search(r"\b14\b|v14|модел[ьи]\s*14|model\s*14", t):
        return "14"
    return "14"


def _extract_versions(user_text: str) -> list[str]:
    """Extract version tags like v7, 7-я, version 7 from text."""
    t = (user_text or "").lower()
    hits: set[str] = set()
    for m in re.finditer(r"\bv[\s\-_:]*([0-9]{1,3})\b", t):
        hits.add(f"v{int(m.group(1))}")
    for m in re.finditer(r"\b([0-9]{1,3})[\-\s]?(й|я|ю|му|м)\b", t):
        hits.add(f"v{int(m.group(1))}")
    for m in re.finditer(r"(верси|version|тюнинг|ft).{0,10}\b([0-9]{1,3})\b", t):
        hits.add(f"v{int(m.group(2))}")
    return sorted(hits, key=lambda x: int(x[1:]))


def _extract_ft_family_explicit(user_text: str) -> str | None:
    t = (user_text or "").lower()
    if re.search(r"\b72\b|v72|модел[ьи]\s*72|model\s*72|qwen2\.5[-:\s]*72", t):
        return "72"
    if re.search(r"\b70\b|v70|модел[ьи]\s*70|model\s*70|deepseek[-:\s]*r1", t):
        return "70"
    if re.search(r"\b32\b|v32|модел[ьи]\s*32|model\s*32|qwen2\.5[-_\s]*coder", t):
        return "32"
    if re.search(r"\b14\b|v14|модел[ьи]\s*14|model\s*14|qwen2\.5[-:\s]*14", t):
        return "14"
    return None


def _parse_ft_start_intent(user_text: str) -> dict[str, object]:
    """
    Parse FT launch/build intent with confidence and normalized command text.
    """
    t = (user_text or "").strip()
    lower = t.lower()
    family_explicit = _extract_ft_family_explicit(lower)
    versions = _extract_versions(lower)
    has_ft_terms = re.search(r"(тюнинг|ft|train|трен|обуч|fine[\s\-]*tun)", lower) is not None
    has_start_terms = re.search(r"(созда|запуск|prepare|подготов|build|start|launch)", lower) is not None
    confidence = 0.35
    if has_ft_terms:
        confidence += 0.2
    if has_start_terms:
        confidence += 0.2
    if family_explicit:
        confidence += 0.2
    if versions:
        confidence += 0.1
    confidence = min(confidence, 0.98)
    if not (has_ft_terms and has_start_terms):
        return {"ok": False, "reason": "missing_action_terms", "confidence": confidence}
    if not family_explicit:
        return {"ok": False, "reason": "family_not_explicit", "confidence": confidence}

    family = family_explicit
    base = versions[0] if versions else (ft_resolve_active(family) or "v1")
    target = versions[1] if len(versions) >= 2 else (versions[0] if len(versions) == 1 else ft_next_version(family))
    normalized_text = f"создай и запусти ft для модели {family}: {base} -> {target}"
    summary = f"FT-{family}: base={base}, target={target}"
    return {
        "ok": True,
        "family": family,
        "base": base,
        "target": target,
        "normalized_text": normalized_text,
        "summary": summary,
        "confidence": confidence,
    }


def _ft_version_factual_reply(user_text: str) -> str:
    """
    Deterministic reply for v7/v8-style FT status requests.
    Uses only local files/artifacts, no LLM.
    """
    t = (user_text or "").lower()
    family = _detect_ft_family(t)
    versions = _extract_versions(t)
    if not versions:
        latest = ft_latest_version_summary(family).get("latest_version")
        if isinstance(latest, str):
            versions = [latest]
    lines: list[str] = []
    if not versions:
        lines.append(f"Нет подтверждённых данных по версиям FT-{family} в этом запросе.")
    for ver in versions:
        summary = ft_latest_version_summary(family)
        cp = ft_collect_checkpoints(family, ver)
        paths = ft_version_paths(family, ver)
        track_type = str(summary.get("track_type") or "text")
        benchmark_profile = str(summary.get("benchmark_profile") or "gemini3_text")
        threshold_policy = summary.get("threshold_policy", {}) if isinstance(summary.get("threshold_policy"), dict) else {}
        decision_info = summary.get("active_decision") if str(summary.get("active_version")) == ver else summary.get("latest_decision")
        metrics_info = summary.get("active_metrics") if str(summary.get("active_version")) == ver else summary.get("latest_metrics")
        lines.append(f"📌 {family}/{ver} (локальный факт-статус):")
        lines.append(f"- track: {track_type}")
        lines.append(f"- benchmark_profile: {benchmark_profile}")
        lines.append(f"- status: {cp.get('status', 'unknown')}")
        if threshold_policy:
            lines.append(
                "- threshold_policy: "
                f"min_accept={threshold_policy.get('min_accept')} "
                f"target_similarity={threshold_policy.get('target_similarity_to_benchmark')}"
            )
        if isinstance(metrics_info, dict) and metrics_info:
            lines.append(
                "- metrics: "
                f"score={metrics_info.get('score', '-')} "
                f"similarity={metrics_info.get('similarity_to_benchmark', '-')}"
            )
        if isinstance(decision_info, dict) and decision_info:
            lines.append(
                f"- decision: {decision_info.get('decision', '-')} "
                f"(reason={decision_info.get('reason', 'no_reason')})"
            )
        lines.append(f"- log: {paths['log']}")
        if cp.get("last_log_line"):
            lines.append(f"- last_log_line: {str(cp['last_log_line'])[:220]}")
        lines.append(
            "- artifacts: "
            f"adapter={'yes' if cp.get('adapter_exists') else 'no'}, "
            f"merged={'yes' if cp.get('merged_exists') else 'no'}, "
            f"gguf={'yes' if cp.get('gguf_exists') else 'no'}"
        )
    lines.append("Источник: локальные файлы/артефакты, без генерации LLM.")
    return "\n".join(lines)


def _detect_ft_v7_v8_workflow_request(user_text: str) -> bool:
    """
    Detect user intent:
      - gather v7 tuning data
      - verify result
      - create/launch FT v8
    """
    t = (user_text or "").lower()
    has_create = re.search(r"(собер|собрать|созда|запуск|run|новую верси|build)", t) is not None
    has_verify = re.search(r"(проверь|провер|результат|сравн|готовност|verify|compare)", t) is not None
    versions = _extract_versions(t)
    return (
        (has_create and (has_verify or len(versions) >= 2))
        and re.search(r"(тюнинг|ft|модел|model|train|трен)", t) is not None
    )


def _run_ft_skill_check(alias: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["python3", "ops/scripts/argus_ft_skill.py", "--model", alias],
        cwd="/workspace",
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    body = out if out else ""
    if err:
        body = f"{body}\n{err}".strip()
    return proc.returncode, body


def _queue_ft_launch(alias: str, chat_id: int, *, run_now: bool = True) -> None:
    cmd = ["python3", "ops/scripts/argus_ft_skill.py", "--model", str(alias)]
    if run_now:
        cmd.append("--run")
    _pending_ft_launch_queue.append(
        {
            "alias": str(alias),
            "chat_id": int(chat_id),
            "cmd": cmd,
            "queued_at": time.time(),
        }
    )
    _persist_pending_queues()


def _family_training_versions(family: str) -> list[str]:
    try:
        reg = ft_load_registry()
    except Exception:
        return []
    fam_node = ((reg or {}).get("families") or {}).get(str(family), {})
    versions = fam_node.get("versions") if isinstance(fam_node, dict) else []
    out: list[str] = []
    if isinstance(versions, list):
        for item in versions:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).lower() == "training":
                ver = str(item.get("version", "")).strip()
                if ver:
                    out.append(ver)
    return out


def _global_training_entries() -> list[tuple[str, str]]:
    try:
        reg = ft_load_registry()
    except Exception:
        return []
    fams = (reg or {}).get("families", {})
    out: list[tuple[str, str]] = []
    if not isinstance(fams, dict):
        return out
    for fam, node in fams.items():
        if not isinstance(node, dict):
            continue
        versions = node.get("versions")
        if not isinstance(versions, list):
            continue
        for item in versions:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).lower() == "training":
                ver = str(item.get("version", "")).strip()
                if ver:
                    out.append((str(fam), ver))
    return out


def _queue_ft_workflow(chat_id: int, user_text: str, family: str, target_version: str) -> None:
    _pending_ft_workflow_queue.append(
        {
            "chat_id": int(chat_id),
            "user_text": str(user_text),
            "family": str(family),
            "target_version": str(target_version),
            "queued_at": time.time(),
        }
    )
    _persist_pending_queues()


def _run_eval_vs_benchmark(family: str, version: str, track_type: str, benchmark_profile: str) -> tuple[int, dict[str, object]]:
    proc = subprocess.run(
        [
            "python3",
            "ops/ft/scripts/eval_vs_benchmark.py",
            "--family",
            str(family),
            "--version",
            str(version),
            "--track",
            str(track_type),
            "--benchmark-profile",
            str(benchmark_profile),
        ],
        cwd="/workspace",
        capture_output=True,
        text=True,
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return proc.returncode, {}
    if not raw:
        return 0, {}
    # Script writes one JSON object in stdout.
    try:
        payload = json.loads(raw.splitlines()[-1])
    except Exception:
        payload = {}
    return 0, payload if isinstance(payload, dict) else {}


def _launch_ft_once(family: str, version: str) -> tuple[int, str]:
    fam = str(family).strip()
    blocked, reason, snap = _thermal_preflight_status()
    if blocked:
        return (
            99,
            (
                f"paused_by_thermal_guard reason={reason} "
                f"cpu_temp={snap.get('cpu_temp', 0):.1f} "
                f"cpu_util={snap.get('cpu_util', 0):.1f}"
            ),
        )
    ver = ft_parse_version_token(version or "") or version
    paths = ft_version_paths(fam, ver)
    env = os.environ.copy()
    rel_cfg = str(paths["config"]).replace("/workspace/", "")
    env["ARGUS_FT_TRAIN_CONFIG"] = rel_cfg
    # Force concrete local action even if env previously disabled local nohup.
    env["ARGUS_FT_LOCAL_NOHUP"] = "1"
    env["ARGUS_FT_LOCAL_TRAIN_LOG"] = str(paths["log"])
    if fam == "70":
        env["ARGUS_FT70_LOCAL_NOHUP"] = "1"
        env["ARGUS_FT70_LAUNCH_CMD"] = f"bash ops/ft/scripts/train_70.sh {rel_cfg}"
    elif fam == "72":
        env["ARGUS_FT72_LOCAL_NOHUP"] = "1"
        env["ARGUS_FT72_LAUNCH_CMD"] = f"bash ops/ft/scripts/train_72.sh {rel_cfg}"
    launch_script = {
        "14": "ops/scripts/argus_launch_ft_v7.sh",
        "70": "ops/scripts/argus_launch_ft_70.sh",
        "72": "ops/scripts/argus_launch_ft_72.sh",
    }.get(fam)
    if not launch_script:
        return 2, f"unsupported_until_script family={fam}"
    proc = subprocess.run(
        ["bash", launch_script],
        cwd="/workspace",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    body = out if out else ""
    if err:
        body = f"{body}\n{err}".strip()
    pid = _parse_local_nohup_pid(body)
    if pid:
        global _last_ft_launch_pid, _last_ft_launch_meta
        _last_ft_launch_pid = pid
        _last_ft_launch_meta = {"family": fam, "version": str(ver)}
    return proc.returncode, body


def _ft_v7_v8_workflow_reply(user_text: str = "") -> str:
    """
    Execute factual workflow:
      1) collect v7 FT status data
      2) verify latest result from local logs/status
      3) create and launch FT v8 config
    """
    family = _detect_ft_family(user_text)
    summary = ft_latest_version_summary(family)
    track_type = str(summary.get("track_type") or "text")
    benchmark_profile = str(summary.get("benchmark_profile") or "gemini3_text")
    versions = _extract_versions(user_text)
    base_ver = versions[0] if versions else (ft_resolve_active(family) or "v1")
    target_ver = versions[1] if len(versions) > 1 else ft_next_version(family)
    lines: list[str] = [f"🛠 FT workflow ({family}: {base_ver} → {target_ver}):"]
    lines.append(f"track={track_type}, benchmark={benchmark_profile}")

    if family in {"14", "70", "72"}:
        rc, body = _run_ft_skill_check(family)
        lines.append(f"1) FT-{family} check rc={rc}")
        if body:
            lines.append(f"   {body.splitlines()[0][:240]}")
    else:
        lines.append("1) FT-32 check: unsupported_until_script")

    base_cp = ft_collect_checkpoints(family, base_ver)
    lines.append(f"2) verify {base_ver}: status={base_cp.get('status', 'unknown')}")
    if base_cp.get("last_log_line"):
        lines.append(f"   base last log: {str(base_cp['last_log_line'])[:220]}")

    training_versions = _family_training_versions(family)
    global_training = _global_training_entries()
    if global_training and not any(fam == family and ver == target_ver for fam, ver in global_training):
        lines.append("3) create config: blocked (another training is already running globally).")
        lines.append(
            f"   active training: {', '.join(f'{fam}:{ver}' for fam, ver in global_training)}; requested={family}:{target_ver}"
        )
        lines.append("   action: request queued in scheduler required.")
        lines.append("Источник: реальные subprocess + локальные файлы.")
        return "\n".join(lines)
    if training_versions and target_ver not in training_versions:
        lines.append(
            "3) create config: blocked (another training is already running for this family)."
        )
        lines.append(
            f"   active training: {', '.join(training_versions)}; requested target={target_ver}"
        )
        lines.append("Источник: реальные subprocess + локальные файлы.")
        return "\n".join(lines)
    if training_versions and target_ver in training_versions:
        lines.append(f"3) create config {target_ver}: skipped (already in training)")
        target_cp = ft_collect_checkpoints(family, target_ver)
        lines.append(
            "4) checkpoints: "
            f"log={'yes' if target_cp.get('log_exists') else 'no'}, "
            f"adapter={'yes' if target_cp.get('adapter_exists') else 'no'}, "
            f"merged={'yes' if target_cp.get('merged_exists') else 'no'}, "
            f"gguf={'yes' if target_cp.get('gguf_exists') else 'no'}"
        )
        if target_cp.get("last_log_line"):
            lines.append(f"   last log: {str(target_cp['last_log_line'])[:220]}")
        lines.append("Источник: реальные subprocess + локальные файлы.")
        return "\n".join(lines)

    ok_cfg, cfg_msg, created_ver, _ = ft_create_version_from(
        family,
        target_version=target_ver,
        parent_version=base_ver,
        data_snapshot=f"from_chat:{user_text[:200]}",
    )
    target_ver = created_ver or target_ver
    lines.append(f"3) create config {target_ver}: {'ok' if ok_cfg else 'failed'} ({cfg_msg})")

    if ok_cfg:
        if family == "32":
            ft_update_version_status(
                family,
                target_ver,
                status="rejected",
                decision={"reason": "unsupported_until_script"},
            )
            lines.append("4) launch: unsupported_until_script for family 32")
        else:
            rc_launch, launch_msg = _launch_ft_once(family, target_ver)
            lines.append(f"4) launch {target_ver} rc={rc_launch}")
            if launch_msg:
                lines.append(f"   {launch_msg.splitlines()[0][:240]}")
        target_cp = ft_collect_checkpoints(family, target_ver)
        lines.append(
            "5) checkpoints: "
            f"log={'yes' if target_cp.get('log_exists') else 'no'}, "
            f"adapter={'yes' if target_cp.get('adapter_exists') else 'no'}, "
            f"merged={'yes' if target_cp.get('merged_exists') else 'no'}, "
            f"gguf={'yes' if target_cp.get('gguf_exists') else 'no'}"
        )
        last = str(target_cp.get("last_log_line", "")).lower()
        if "missing dependency" in last:
            lines.append("   result: blocked (dependency issue in target log).")
        elif target_cp.get("adapter_exists") or target_cp.get("merged_exists") or target_cp.get("gguf_exists"):
            lines.append("   result: progressed (target artifacts detected).")
        elif target_cp.get("log_exists"):
            lines.append("   result: started (target log present, waiting for artifacts).")
        else:
            lines.append("   result: pending (no launch evidence yet).")

        rc_eval, eval_payload = _run_eval_vs_benchmark(family, target_ver, track_type, benchmark_profile)
        score = None
        similarity = None
        if rc_eval == 0 and eval_payload:
            score = eval_payload.get("score")
            similarity = eval_payload.get("similarity_to_benchmark")
            lines.append(
                "6) eval_vs_benchmark: "
                f"score={score} similarity={similarity} source={eval_payload.get('source', 'local_eval_reports')}"
            )
        # Fallback if no eval reports were available yet.
        if not isinstance(score, (float, int)) or not isinstance(similarity, (float, int)):
            score = 0.0
            similarity = 0.0
            if target_cp.get("adapter_exists") or target_cp.get("merged_exists") or target_cp.get("gguf_exists"):
                score = 0.8
                similarity = 0.85
            elif target_cp.get("log_exists"):
                score = 0.62
                similarity = 0.7
            lines.append("6) eval_vs_benchmark: fallback heuristic (no eval report)")
        benchmark_decision = ft_evaluate_benchmark_decision(
            track_type,
            score=score,
            similarity_to_benchmark=similarity,
            previous_score=None,
        )
        ft_update_version_status(
            family,
            target_ver,
            metrics={
                "score": benchmark_decision.get("score"),
                "similarity_to_benchmark": benchmark_decision.get("similarity_to_benchmark"),
                "benchmark_profile": benchmark_profile,
            },
            decision={
                "decision": benchmark_decision.get("decision"),
                "reason": benchmark_decision.get("reason"),
                "policy": benchmark_decision.get("policy"),
            },
        )
        lines.append(
            "6) benchmark decision: "
            f"{benchmark_decision.get('decision')} ({benchmark_decision.get('reason')}) "
            f"score={benchmark_decision.get('score')} "
            f"similarity={benchmark_decision.get('similarity_to_benchmark')}"
        )

    lines.append("Источник: реальные subprocess + локальные файлы.")
    return "\n".join(lines)


async def on_chat_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Conversational mode for plain text user messages."""
    if not CHAT_ENABLED:
        return
    if not _allowed(update):
        return
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    if not text:
        return
    chat_id = update.effective_chat.id if update.effective_chat else 0
    trace_id = f"chat:{chat_id}:{int(time.time() * 1000) % 10000000}"
    # Prevent parallel GPU saturation: if another request is already running, queue this one.
    _llm_lock = _get_chat_llm_lock()
    if _llm_lock.locked():
        if chat_id:
            _queue_chat_retry(chat_id, text, "argus", retries=0)
            await msg.reply_text("⏳ Предыдущий запрос ещё в обработке — поставил в очередь, отвечу как освобожусь.")
        return
    async with _llm_lock:
        await _on_chat_message_locked(update, ctx, msg, text, chat_id, trace_id)


async def _on_chat_message_locked(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    msg: object,
    text: str,
    chat_id: int,
    trace_id: str,
) -> None:
    """Heavy LLM portion of on_chat_message; runs under _chat_llm_lock."""
    # Thermal check is first — before ANY LLM call that could spike DGX GPU.
    _therm_blocked, _therm_reason, _therm_snap = await asyncio.to_thread(_thermal_preflight_status)
    _thermally_blocked = _therm_blocked or _is_thermal_paused()

    # Skip DGX-touching intent classification when GPU is already under load.
    if not _thermally_blocked:
        semantic_intent = await asyncio.to_thread(_semantic_intent_label, text)
    else:
        semantic_intent = "unknown"

    if text.lower() in {"reset context", "clear context"}:
        if chat_id:
            _chat_context_clear(chat_id)
        await msg.reply_text("🧹 Chat context cleared.")
        return
    if text in {"🚀 Start", "Start", "start"}:
        log.info("%s start-intent received", trace_id)
        try:
            loop = asyncio.get_running_loop()
            if MEDIUM_MODEL:
                loop.create_task(asyncio.to_thread(_warm_medium_model_now))
            log.info(
                "%s warm scheduled medium=%s",
                trace_id,
                resolve_model_name(MEDIUM_MODEL) if MEDIUM_MODEL else "",
            )
        except Exception:
            pass
        await msg.reply_text("⚙️ Argus model warm-up started (`qwen2.5-coder:32b`).")
        return
    if not _should_reply_in_group(update, text):
        return
    route_mode, text = _route_mode(text)
    if not text:
        await msg.reply_text("Please provide request text after the mode prefix.")
        return

    if route_mode == "claude_direct":
        blocked_now, _, _ = await asyncio.to_thread(_thermal_preflight_status)
        if (blocked_now or _is_thermal_paused()) and chat_id:
            _queue_chat_retry(chat_id, text, route_mode, retries=0)
            await msg.reply_text("⏸ Thermal pause is active. Request queued and will auto-resume after cooldown.")
            return
        await msg.chat.send_action(ChatAction.TYPING)
        if not _chat_preflight_hook():
            await msg.reply_text("❌ No available Ollama backend")
            return
        model = resolve_model_name(MEDIUM_MODEL or CHAT_MODEL) if (MEDIUM_MODEL or CHAT_MODEL) else ""
        if not model:
            await msg.reply_text("❌ Direct model is not configured")
            return
        prompt_direct = (
            "Direct Claude mode. Reply with a direct answer only.\n"
            "Do NOT output pseudo tool calls, code-runner wrappers, or Agent(...) blocks.\n"
            "Read-only by default. If code changes are requested, provide a plan and ask for governed lane approval.\n\n"
            f"Request: {text}"
        )
        knomi_ctx = _knomi_prefetch_context(text)
        if knomi_ctx:
            prompt_direct = f"{prompt_direct}\n\n{knomi_ctx}"
        try:
            ans, backend_url = await asyncio.to_thread(_chat_answer_skill, prompt_direct, model, "plan")
        except Exception as exc:
            await msg.reply_text(f"❌ Direct mode error: {_h(str(exc))}", parse_mode=ParseMode.HTML)
            return
        if not ans:
            if chat_id:
                _queue_chat_retry(chat_id, text, route_mode, retries=0)
                await msg.reply_text("⏳ Direct mode unavailable now. Request queued for automatic retry.")
                return
            await msg.reply_text("❌ Direct mode unavailable right now.")
            return
        ans = _sanitize_chat_answer(ans)
        await msg.reply_text(ans[:3400])
        if chat_id:
            _chat_context_add(chat_id, "user", text)
            _chat_context_add(chat_id, "assistant", ans)
        _knomi_log_event(
            "argus.chat.direct.success",
            {"model": model, "query": text[:1000], "answer": ans[:2000], "backend_url": backend_url or ""},
        )
        return
    ft_alias = _detect_ft_status_alias(text)
    if ft_alias:
        await msg.reply_text(_ft_status_factual_reply(ft_alias))
        return
    if semantic_intent == "ft_start" or _detect_ft_v7_v8_workflow_request(text):
        parsed = _parse_ft_start_intent(text)
        if not bool(parsed.get("ok")):
            await msg.reply_text(
                "Не уверен в параметрах запуска FT. Укажи явно: family (14/32/70/72) и версию.\n"
                "Пример: prepare tuning for model 72 from v1 to v2",
            )
            return
        req_id = _put_ft_confirm(
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else 0,
            normalized_text=str(parsed.get("normalized_text", text)),
            summary=str(parsed.get("summary", "")),
            confidence=float(parsed.get("confidence", 0.0)),
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm FT", callback_data=f"ft_confirm:{req_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"ft_cancel:{req_id}"),
        ]])
        await msg.reply_text(
            f"Подтверди запуск: {str(parsed.get('summary', ''))}\n"
            f"Confidence: {float(parsed.get('confidence', 0.0)):.2f}",
            reply_markup=kb,
        )
        return
    if _detect_ft_version_query(text):
        await msg.reply_text(_ft_version_factual_reply(text))
        return

    if LLM_BACKEND == "claude_code" and (_looks_like_write_request(text) or semantic_intent == "code_write"):
        if not _is_owner(update):
            await msg.reply_text("🔐 This looks like a code-change request. Owner permission is required.")
            return
        candidate_models = [
            resolve_model_name(ANALYSIS_MODEL) if ANALYSIS_MODEL else "",
            resolve_model_name(CODE_MODEL) if CODE_MODEL else "",
            resolve_model_name(CHAT_MODEL) if CHAT_MODEL else "",
        ]
        tried_models: list[str] = []
        owner_url = ollama_mgr.node_url("DGX") or ollama_mgr.node_url("DGX_WIFI") or ollama_mgr.node_url("SPARK")
        if owner_url:
            await msg.reply_text("🧭 Running pre-change compatibility and risk analysis…")
            analysis_prompt = _build_change_analysis_prompt(text)
            analysis = ""
            owner_model = ""
            last_exc: Exception | None = None
            for model_name in candidate_models:
                if not model_name or model_name in tried_models:
                    continue
                tried_models.append(model_name)
                try:
                    analysis = await asyncio.to_thread(
                        ask_claude_code_headless,
                        owner_url,
                        model_name,
                        analysis_prompt,
                        CLAUDE_ANALYSIS_TIMEOUT_SEC,
                        "plan",
                        False,
                        None,
                        CLAUDE_CODE_ADD_DIRS,
                    )
                    owner_model = model_name
                    break
                except Exception as exc:
                    last_exc = exc
                    continue
            if not analysis:
                err_text = str(last_exc) if last_exc else "analysis unavailable"
                await msg.reply_text(f"❌ Analysis failed: {_h(err_text[:900])}", parse_mode=ParseMode.HTML)
                _knomi_log_event(
                    "argus.chat.analysis_error",
                    {
                        "model": owner_model,
                        "query": text[:1000],
                        "error": err_text[:1000],
                        "candidate_models": tried_models,
                    },
                )
                return
            apply_prompt = _build_change_apply_prompt(text, analysis)
            summary = _approval_summary(text, owner_model)
            req_id = _put_cc_approval(
                chat_id,
                update.effective_user.id if update.effective_user else 0,
                apply_prompt,
                owner_model,
                owner_url,
                summary=summary,
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"cc_approve:{req_id}"),
                InlineKeyboardButton("❌ Decline", callback_data=f"cc_deny:{req_id}"),
            ]])
            await msg.reply_text(
                "✅ Solution prepared.\n"
                "🔐 Approve implementation.\n"
                f"Approval scope: <code>{_h(summary)}</code>\n"
                f"<b>Proposed plan:</b>\n<pre>{_h(_sanitize_chat_answer(analysis)[:2200])}</pre>\n"
                f"Request ID: <code>{_h(req_id)}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            _knomi_log_event(
                "argus.chat.approval_requested",
                {"request_id": req_id, "summary": summary, "query": text[:1000], "model": owner_model, "analysis": analysis[:2000]},
            )
            return

    # NLP intent routing — map free text to slash commands via local small model (PC_ANDREI only)
    _intent_routed = await asyncio.to_thread(_try_intent_route, text)
    if _intent_routed:
        _intent_cmd, _intent_args = _intent_routed
        _cmd_dispatch = {
            "status": cmd_status, "models": cmd_models, "installed": cmd_installed,
            "logs": cmd_logs, "restart": cmd_restart, "rebuild": cmd_rebuild,
            "stop": cmd_stop, "up": cmd_up, "load": cmd_load, "unload": cmd_unload,
            "tasks": cmd_tasks, "incidents": cmd_incidents, "diagnose": cmd_diagnose,
            "dgx": cmd_dgx, "wake": cmd_wake, "sleep": cmd_sleep,
            "digest": cmd_digest, "plan": cmd_plan,
            "ft_log": cmd_ft_log, "ft_download": cmd_ft_download,
            "eval": cmd_eval, "deploy": cmd_deploy,
        }
        _handler = _cmd_dispatch.get(_intent_cmd)
        if _handler:
            ctx.args = _intent_args
            await _handler(update, ctx)
            return

    # If thermal guard is active and no lightweight command matched — do NOT
    # fall through to the 32B DGX model. Queue and explain.
    if _thermally_blocked:
        if chat_id:
            _queue_chat_retry(chat_id, text, route_mode, retries=0)
        cpu_t = _therm_snap.get("cpu_temp", 0)
        await msg.reply_text(
            f"🧯 GPU занят (CPU {cpu_t:.0f}°C — {_therm_reason}).\n"
            f"Команды без GPU: /ft log · /ft download · /status · /dgx · /tasks\n"
            f"Запрос поставлен в очередь, отвечу после охлаждения.",
            parse_mode=ParseMode.HTML,
        )
        return

    await msg.chat.send_action(ChatAction.TYPING)
    if not _chat_preflight_hook():
        await msg.reply_text("❌ No available Ollama backend for chat")
        return

    try:
        prompt = _chat_prompt_with_context(chat_id, text, CODE_REPO_PATH)
        knomi_ctx = _knomi_prefetch_context(text)
        if knomi_ctx:
            prompt = f"{prompt}\n\n{knomi_ctx}"
        # code_write / ft_start → heavy CODE_MODEL (32B); conversational chat → lighter CHAT_MODEL (14B).
        # This prevents loading the 35 GB model just for simple questions.
        if semantic_intent in ("code_write", "ft_start"):
            _selected_model = MEDIUM_MODEL or CODE_MODEL or CHAT_MODEL
        else:
            _selected_model = MEDIUM_MODEL or CHAT_MODEL or CODE_MODEL
        chat_model = resolve_model_name(_selected_model) if _selected_model else ""
        heavy_model = chat_model
        answer: str | None = None
        backend_url: str | None = None
        log.info("%s chat route heavy_target=%s", trace_id, heavy_model)

        if not answer:
            claude_mode = "plan" if LLM_BACKEND == "claude_code" else "default"
            log.info("%s ask heavy model=%s claude_mode=%s", trace_id, chat_model, claude_mode)
            answer, backend_url = await asyncio.to_thread(_chat_answer_skill, prompt, chat_model, claude_mode)
    except Exception as exc:
        await msg.reply_text(f"❌ LLM chat error: {_h(str(exc))}", parse_mode=ParseMode.HTML)
        _knomi_log_event(
            "argus.chat.error",
            {"model": chat_model, "query": text[:1000], "error": str(exc)[:1000]},
        )
        return

    if not answer:
        if chat_id:
            _queue_chat_retry(chat_id, text, route_mode, retries=0)
            await msg.reply_text("⏳ Backend unavailable now. Request queued for automatic retry.")
            return
        await msg.reply_text(
            "❌ Temporarily unavailable: LLM backend is not reachable.\n"
            "Try /status or /models and retry."
        )
        return
    answer = _sanitize_chat_answer(answer)
    if chat_id:
        _chat_context_add(chat_id, "user", text)
        _chat_context_add(chat_id, "assistant", answer)
    await msg.reply_text(answer[:3400])
    omi_req = _extract_omi_request(answer)
    if omi_req:
        _register_omi_request("chat.auto", text, omi_req)
        await msg.reply_text(
            f"📨 Omi request queued:\n<code>{_h(omi_req)}</code>",
            parse_mode=ParseMode.HTML,
        )
    _knomi_log_event(
        "argus.chat.success",
        {"model": chat_model, "query": text[:1000], "answer": answer[:2000], "backend_url": backend_url or ""},
    )


# ── DGX hardware metrics ──────────────────────────────────────────────────────

async def cmd_dgx(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/dgx — DGX Spark hardware metrics via Prometheus exporter (port 9835)."""
    if not _allowed(update):
        return
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        m = await asyncio.to_thread(_fetch_dgx_metrics)
    except Exception as e:
        await update.message.reply_text(f"❌ DGX metrics unavailable: {e}")
        return

    gpu_temp  = m.get("gpu_temperature_celsius", 0)
    cpu_temp  = m.get("cpu_temperature_celsius", 0)
    gpu_util  = m.get("gpu_utilization_percent", 0)
    gpu_pow   = m.get("gpu_power_watts", 0)
    gpu_freq  = m.get("gpu_frequency_mhz", 0)
    mem_used  = m.get("memory_used_bytes", 0) / 1e9
    mem_total = m.get("memory_total_bytes", 1) / 1e9

    temp_icon = "✅" if gpu_temp < 70 else ("⚠️" if gpu_temp < 80 else "🔴")
    util_icon = "🟢" if gpu_util < 85 else ("🟡" if gpu_util < 95 else "🔴")
    mem_pct   = mem_used / mem_total * 100

    # VRAM from Ollama /api/ps
    try:
        import urllib.request as _ur, json as _json
        dgx_url = os.environ.get("DGX_OLLAMA_URL", "http://192.168.72.225:11434")
        with _ur.urlopen(f"{dgx_url}/api/ps", timeout=5) as r:
            ps = _json.loads(r.read())
        loaded = ps.get("models", [])
        vram_used = sum(mm.get("size_vram", 0) for mm in loaded) / 1e9
        vram_lines = "\n".join(
            f"  • {mm['name'].split(':')[0]}: {mm.get('size_vram',0)/1e9:.1f} GB"
            for mm in loaded
        ) or "  (none)"
    except Exception:
        vram_used = 0.0
        vram_lines = "  (unavailable)"

    vram_icon = "✅" if vram_used < 100 else "🔴"

    text = (
        f"<b>DGX Spark — Hardware Status</b>\n\n"
        f"{temp_icon} GPU temp:   <b>{gpu_temp:.0f}°C</b>   (CPU: {cpu_temp:.1f}°C)\n"
        f"{util_icon} GPU util:   <b>{gpu_util:.0f}%</b>\n"
        f"⚡ GPU power:  <b>{gpu_pow:.1f} W</b>   @ {gpu_freq:.0f} MHz\n"
        f"💾 RAM used:   <b>{mem_used:.1f} / {mem_total:.0f} GB</b>  ({mem_pct:.0f}%)\n"
        f"{vram_icon} VRAM loaded: <b>{vram_used:.1f} GB</b>\n"
        f"{vram_lines}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── Inline button callbacks ────────────────────────────────────────────────────

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "start_heavy":
        await query.edit_message_reply_markup(None)
        # Fire-and-forget warm-up for Argus primary model lane only.
        try:
            loop = asyncio.get_running_loop()
            if MEDIUM_MODEL:
                loop.create_task(asyncio.to_thread(_warm_medium_model_now))
        except Exception:
            pass
        await query.message.reply_text(
            "⚙️ Запускаю прогрев модели Argus."
        )
        return

    if data.startswith("ft_run:"):
        alias = data.split(":", 1)[1]
        await query.edit_message_reply_markup(None)
        blocked, reason, snap = await asyncio.to_thread(_thermal_preflight_status)
        if blocked:
            chat_id = query.effective_chat.id if query.effective_chat else 0
            _queue_ft_launch(alias, chat_id, run_now=True)
            await query.message.reply_text(
                "⏸ DGX перегружен: запуск поставлен в очередь.\n"
                f"Причина: <code>{_h(reason)}</code>\n"
                f"CPU: <b>{snap.get('cpu_temp', 0):.1f}°C</b> / load <b>{snap.get('cpu_util', 0):.1f}%</b>\n"
                f"Автовозобновление после стабилизации ≤{THERMAL_CPU_TEMP_RESUME_C:.0f}°C и "
                f"≤{THERMAL_CPU_UTIL_RESUME_PCT:.0f}% в течение {THERMAL_RESUME_STABLE_SEC}с.",
                parse_mode=ParseMode.HTML,
            )
            return

        def _exec_skill_run() -> tuple[bool, str]:
            p = subprocess.run(
                ["python3", "ops/scripts/argus_ft_skill.py", "--model", alias, "--run"],
                cwd="/workspace",
                check=False,
                capture_output=True,
                text=True,
            )
            body = (p.stdout or "").strip()
            if p.stderr:
                body = f"{body}\n{p.stderr.strip()}".strip()
            pid = _parse_local_nohup_pid(body)
            if pid:
                global _last_ft_launch_pid, _last_ft_launch_meta
                _last_ft_launch_pid = pid
                _last_ft_launch_meta = {"family": alias, "version": ""}
            return p.returncode == 0, body or "(no output)"

        ok, body = await asyncio.to_thread(_exec_skill_run)
        icon = "✅" if ok else "❌"
        await query.message.reply_text(
            f"{icon} <b>FT run now ({_h(alias)})</b>\n<pre>{_h(body[:1800])}</pre>",
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("ft_night:"):
        alias = data.split(":", 1)[1]
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(
            f"🕒 Ок, оставляем только ночной график для FT-{_h(alias)}.\n"
            f"Проверить можно командой: <code>/ft {_h(alias)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("ft_cancel:"):
        await query.edit_message_reply_markup(None)
        req_id = data.split(":", 1)[1]
        item = _pop_ft_confirm(req_id)
        if not item:
            await query.message.reply_text("⚠️ FT request expired or not found.")
            return
        await query.message.reply_text("❌ FT запуск отменен.")
        return

    if data.startswith("ft_confirm:"):
        await query.edit_message_reply_markup(None)
        req_id = data.split(":", 1)[1]
        item = _pop_ft_confirm(req_id)
        if not item:
            await query.message.reply_text("⚠️ FT request expired or not found.")
            return
        chat_id = int(item.get("chat_id", 0))
        if query.effective_chat and query.effective_chat.id != chat_id:
            await query.message.reply_text("❌ Invalid chat for this FT confirmation.")
            return
        normalized_text = str(item.get("normalized_text", "")).strip()
        parsed = _parse_ft_start_intent(normalized_text)
        family = str(parsed.get("family", _detect_ft_family(normalized_text)))
        target_version = str(parsed.get("target", ""))
        active = _global_training_entries()
        # Allow immediate run only if nothing else is training globally.
        if active and not any(fam == family and ver == target_version for fam, ver in active):
            _queue_ft_workflow(chat_id, normalized_text, family, target_version)
            await query.message.reply_text(
                f"🕒 Queued in scheduler: FT-{family} {target_version}.\n"
                f"Сейчас выполняется: {', '.join(f'{fam}:{ver}' for fam, ver in active)}"
            )
            return
        await query.message.reply_text("Accepted. Running factual FT workflow and checking files/logs…")
        result = await asyncio.to_thread(_ft_v7_v8_workflow_reply, normalized_text)
        await query.message.reply_text(_sanitize_chat_answer(result)[:3400])
        return

    if data.startswith("cc_deny:"):
        await query.edit_message_reply_markup(None)
        req_id = data.split(":", 1)[1]
        item = _pop_cc_approval(req_id)
        summary = str((item or {}).get("summary", "")).strip()
        _knomi_log_event(
            "argus.claude.approval_denied",
            {"request_id": req_id, "summary": summary, "query": str((item or {}).get("prompt", ""))[:1000]},
        )
        if summary:
            await query.message.reply_text(
                f"❌ Declined.\n<code>{_h(summary)}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.message.reply_text("❌ Change permission declined.", parse_mode=ParseMode.HTML)
        return

    if data.startswith("cc_approve:"):
        await query.edit_message_reply_markup(None)
        req_id = data.split(":", 1)[1]
        item = _pop_cc_approval(req_id)
        if not item:
            await query.message.reply_text("⚠️ Request expired or not found.", parse_mode=ParseMode.HTML)
            return
        summary = str(item.get("summary", "")).strip()
        chat_id = int(item.get("chat_id", 0))
        if query.effective_chat and query.effective_chat.id != chat_id:
            await query.message.reply_text("❌ Invalid chat for this approval.", parse_mode=ParseMode.HTML)
            return
        if summary:
            await query.message.reply_text(
                "✅ Approved. Implementation started.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.message.reply_text(
                "✅ Approved.\n"
                "🚀 Implementation started.",
                parse_mode=ParseMode.HTML,
            )
        _knomi_log_event(
            "argus.claude.approval_granted",
            {"request_id": req_id, "summary": summary, "query": str(item.get("prompt", ""))[:1000]},
        )
        out = ""
        last_err = ""
        base_prompt = str(item["prompt"])
        for attempt in range(1, CLAUDE_CHANGE_MAX_LOOPS + 1):
            prompt_to_run = base_prompt if attempt == 1 else _build_change_apply_prompt(
                "Повтори изменение и добейся PASS по тестам.",
                "Анализ уже выполнен, сфокусируйся на исправлении найденных проблем.",
                prev_feedback=(out or last_err)[:2500],
            )
            try:
                out = await asyncio.to_thread(
                    ask_claude_code_headless,
                    str(item["url"]),
                    str(item["model"]),
                    prompt_to_run,
                    420,
                    "acceptEdits",
                    False,
                    None,
                    CLAUDE_CODE_ADD_DIRS,
                )
            except Exception as exc:
                last_err = str(exc)
                if attempt >= CLAUDE_CHANGE_MAX_LOOPS:
                    await query.message.reply_text(
                        "⚙️ Auto-repair loop continues in background.",
                        parse_mode=ParseMode.HTML,
                    )
                    _knomi_log_event(
                        "argus.claude.run_after_approval_error",
                        {"request_id": req_id, "error": last_err[:1000], "query": str(item.get("prompt", ""))[:1000]},
                    )
                    return
                continue
            if "FINAL_STATUS: PASS" in out:
                break
            if attempt >= CLAUDE_CHANGE_MAX_LOOPS:
                await query.message.reply_text("⚙️ Auto-repair loop continues in background.", parse_mode=ParseMode.HTML)
                _knomi_log_event(
                    "argus.claude.run_after_approval_fail",
                    {"request_id": req_id, "query": str(item.get("prompt", ""))[:1000], "answer": out[:2000]},
                )
                return
        await query.message.reply_text(
            f"✅ PASSED.\n"
            f"🧠 <b>Implementation result</b>\n<pre>{_h(_sanitize_chat_answer(out)[:3400])}</pre>",
            parse_mode=ParseMode.HTML,
        )
        omi_req = _extract_omi_request(out)
        if omi_req:
            _register_omi_request("code.approved", str(item.get("prompt", "")), omi_req)
            await query.message.reply_text(
                f"📨 Omi request queued:\n<code>{_h(omi_req)}</code>",
                parse_mode=ParseMode.HTML,
            )
        _knomi_log_event(
            "argus.claude.run_after_approval_success",
            {"request_id": req_id, "query": str(item.get("prompt", ""))[:1000], "answer": out[:2000]},
        )
        return

    # ── Orchestrator approval buttons ────────────────────────────────────────
    # ── /train button callbacks ──────────────────────────────────────────────
    if data == "train_v7":
        await query.edit_message_reply_markup(None)
        step = next((s for s in orchestrator._steps if s.id == "ft_v7_routing"), None)
        if step:
            await asyncio.to_thread(orchestrator._request_approval, step)
            await query.message.reply_text("🔐 Запрос на обучение v7 отправлен")
        return

    if data == "train_gen":
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("⏳ gen-v1 обучение — используй /train gen для деталей")
        return

    if data == "train_night":
        await query.edit_message_reply_markup(None)
        steps_to_run = ["training_ingest_new_docs", "training_generate_pairs", "training_dataset_status"]
        fired = []
        for sid in steps_to_run:
            step = next((s for s in orchestrator._steps if s.id == sid), None)
            if step:
                ok, detail = await asyncio.to_thread(orchestrator._execute_action, step)
                fired.append(f"{'✅' if ok else '❌'} {sid}")
        await query.message.reply_text(
            f"▶️ <b>Pipeline запущен</b>\n\n" + "\n".join(fired),
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "train_status":
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("Используй /train status", parse_mode=ParseMode.HTML)
        return

    if data.startswith("plan_approve:"):
        step_id = data.split(":", 1)[1]
        await query.edit_message_reply_markup(None)
        result = await asyncio.to_thread(orchestrator.approve, step_id)
        await query.message.reply_text(result, parse_mode=ParseMode.HTML)
        return

    if data.startswith("plan_defer:"):
        step_id = data.split(":", 1)[1]
        await query.edit_message_reply_markup(None)
        result = await asyncio.to_thread(orchestrator.defer, step_id)
        await query.message.reply_text(result, parse_mode=ParseMode.HTML)
        return

    if data.startswith("plan_cancel:"):
        step_id = data.split(":", 1)[1]
        await query.edit_message_reply_markup(None)
        result = await asyncio.to_thread(orchestrator.cancel, step_id)
        await query.message.reply_text(result, parse_mode=ParseMode.HTML)
        return

    if data.startswith("restart:"):
        svc = data.split(":", 1)[1]
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"🔄 Перезапускаю <code>{_h(svc)}</code>…", parse_mode=ParseMode.HTML)
        ok, msg = await asyncio.to_thread(docker_mgr.restart, svc)
        await asyncio.to_thread(storage.log_action, svc, "restart", "ok" if ok else msg[:80])
        icon = "✅" if ok else "❌"
        await query.message.reply_text(
            f"{icon} restart <code>{_h(svc)}</code>\n<pre>{_h(msg[:400])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("diagnose:"):
        parts  = data.split(":")
        svc    = parts[1]
        inc_id = int(parts[2]) if len(parts) > 2 else 0
        await query.message.reply_text(f"🔍 Диагностика <code>{_h(svc)}</code>…", parse_mode=ParseMode.HTML)
        logs   = await asyncio.to_thread(docker_mgr.get_logs, svc, 120)
        ollama_url, _ = await asyncio.to_thread(ollama_mgr.pick_small_model_url)
        diag_text, backend = await asyncio.to_thread(
            _diag.diagnose,
            svc, "alert_button", logs,
            "",
            ollama_url,
            os.environ.get("ARGUS_LOCAL_DIAG_MODEL", ""),
        )
        if inc_id:
            await asyncio.to_thread(storage.update_diagnosis, inc_id, diag_text)
        await query.message.reply_text(
            f"🔍 <b>{_h(svc)}</b> (<i>{_h(backend)}</i>)\n\n{_h(diag_text)}",
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("silence:"):
        parts = data.split(":")
        svc   = parts[1]
        mins  = int(parts[2]) if len(parts) > 2 else 30
        await asyncio.to_thread(storage.silence, svc, mins)
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(
            f"🔇 <code>{_h(svc)}</code> заглушен на {mins} мин",
            parse_mode=ParseMode.HTML,
        )


# ── Startup / main ─────────────────────────────────────────────────────────────

async def _post_init(app: Application) -> None:
    global _app
    _app = app
    try:
        await asyncio.to_thread(ft_load_registry)
    except Exception as exc:
        log.warning("ft registry bootstrap failed: %s", exc)
    asyncio.create_task(_alert_consumer(app))
    asyncio.create_task(_small_model_keeper_loop())
    asyncio.create_task(_thermal_guard_loop())
    asyncio.create_task(_ft_process_watcher_loop())
    monitor.start()
    ka_mgr.start()
    orchestrator.start()
    await app.bot.set_my_commands([
        BotCommand("status",    "Статус контейнеров"),
        BotCommand("models",    "VRAM Ollama"),
        BotCommand("installed", "Установленные модели"),
        BotCommand("logs",      "Логи сервиса"),
        BotCommand("restart",   "Перезапустить контейнер"),
        BotCommand("rebuild",   "Пересобрать и запустить контейнер"),
        BotCommand("stop",      "Остановить контейнер"),
        BotCommand("up",        "Запустить контейнер"),
        BotCommand("load",      "Загрузить модель в VRAM"),
        BotCommand("unload",    "Выгрузить модель из VRAM"),
        BotCommand("pull",      "Скачать модель Ollama"),
        BotCommand("tasks",     "Реестр задач"),
        BotCommand("incidents", "История инцидентов"),
        BotCommand("diagnose",  "AI-диагностика сервиса"),
        BotCommand("test",      "Smoke-тест сервиса"),
        BotCommand("env",       "ENV переменные сервиса"),
        BotCommand("set",       "Изменить .env + рестарт"),
        BotCommand("wake",      "Разбудить контейнер (keepalive)"),
        BotCommand("sleep",     "Остановить контейнер"),
        BotCommand("keepalive", "Статус keepalive-контейнеров"),
        BotCommand("silence",   "Заглушить алерты"),
        BotCommand("unsilence", "Снять заглушку"),
        BotCommand("silences",  "Список заглушек"),
        BotCommand("plan",      "Планировщик: статус / reload / run / digest"),
        BotCommand("dgx",       "DGX Spark: температура, GPU, RAM"),
        BotCommand("digest",    "Утренний дайджест прямо сейчас"),
        BotCommand("train",     "Обучение моделей: статус датасета / запуск"),
        BotCommand("ft",        "FT skill: 14/32/70/72 (check + run now)"),
        BotCommand("code",      "Контроль кода: status/review"),
        BotCommand("help",      "Справка"),
    ])
    log.info("Argus bot started. OWNER_CHAT_IDS=%s ALLOWED_IDS=%s", OWNER_CHAT_IDS, ALLOWED_IDS)
    for cid in OWNER_CHAT_IDS:
        try:
            await app.bot.send_message(
                cid,
                "👁 <b>Argus</b> запущен и ведёт наблюдение.\n"
                f"<i>Разрешённые ID: {sorted(ALLOWED_IDS)}</i>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("ARGUS_BOT_TOKEN не задан")
    _load_pending_queues()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("models",    cmd_models))
    app.add_handler(CommandHandler("installed", cmd_installed))
    app.add_handler(CommandHandler("logs",      cmd_logs))
    app.add_handler(CommandHandler("restart",   cmd_restart))
    app.add_handler(CommandHandler("rebuild",   cmd_rebuild))
    app.add_handler(CommandHandler("stop",      cmd_stop))
    app.add_handler(CommandHandler("up",        cmd_up))
    app.add_handler(CommandHandler("load",      cmd_load))
    app.add_handler(CommandHandler("unload",    cmd_unload))
    app.add_handler(CommandHandler("pull",      cmd_pull))
    app.add_handler(CommandHandler("delete",    cmd_delete))
    app.add_handler(CommandHandler("tasks",     cmd_tasks))
    app.add_handler(CommandHandler("incidents", cmd_incidents))
    app.add_handler(CommandHandler("diagnose",  cmd_diagnose))
    app.add_handler(CommandHandler("test",      cmd_test))
    app.add_handler(CommandHandler("env",       cmd_env))
    app.add_handler(CommandHandler("set",       cmd_set))
    app.add_handler(CommandHandler("wake",      cmd_wake))
    app.add_handler(CommandHandler("sleep",     cmd_sleep))
    app.add_handler(CommandHandler("keepalive", cmd_keepalive))
    app.add_handler(CommandHandler("silence",   cmd_silence))
    app.add_handler(CommandHandler("unsilence", cmd_unsilence))
    app.add_handler(CommandHandler("silences",  cmd_silences))
    app.add_handler(CommandHandler("dgx",       cmd_dgx))
    app.add_handler(CommandHandler("plan",      cmd_plan))
    app.add_handler(CommandHandler("digest",    cmd_digest))
    app.add_handler(CommandHandler("train",     cmd_train))
    app.add_handler(CommandHandler("ft",        cmd_ft))
    app.add_handler(CommandHandler("eval",      cmd_eval))
    app.add_handler(CommandHandler("deploy",    cmd_deploy))
    app.add_handler(CommandHandler("code",      cmd_code))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_chat_message))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(_error_handler)

    if TELEGRAM_MODE == "webhook":
        if not WEBHOOK_PUBLIC_URL:
            raise SystemExit("ARGUS_TELEGRAM_MODE=webhook, но ARGUS_WEBHOOK_URL не задан")
        webhook_url = WEBHOOK_PUBLIC_URL.rstrip("/") + WEBHOOK_PATH
        log.info(
            "Starting Argus bot (webhook): url=%s listen=%s:%s path=%s",
            webhook_url, WEBHOOK_LISTEN, WEBHOOK_PORT, WEBHOOK_PATH
        )
        app.run_webhook(
            listen=WEBHOOK_LISTEN,
            port=WEBHOOK_PORT,
            webhook_url=webhook_url,
            url_path=WEBHOOK_PATH.lstrip("/"),
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
        return

    log.info("Starting Argus bot (polling)…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
