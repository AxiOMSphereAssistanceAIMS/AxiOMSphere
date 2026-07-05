#!/usr/bin/env python3
"""LogiAgent Telegram interface.

All text goes to LogiAgent (LLM loop with tools).
Special commands: /help /whoami /plans /clear /status
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request

# Add ops/ to path so logi.agent can import logi.plans
_ops = os.path.join(os.path.dirname(__file__), "..")
if _ops not in sys.path:
    sys.path.insert(0, _ops)

from logi.conversational_orchestrator import LogiAgent
from logi.plans import list_plans, load_plan
from logi.project_goal_intake import ingest_telegram_goal_text
from logi.project_goal_intake import DEFAULT_ARCHITECTURE_ROOT, GOAL_INDEX_JSON
from logi.project_goal_autorunner import AutorunnerConfig, status as autorunner_status
from logi.syntax_interpreter import interpret_syntax_intent
from logi.syntax_policy import evaluate_intent_policy, render_policy_response
from logi.ai_intent_router import route_intent
from logi.claude_skill_index import skill_context_preamble
from logi.skills_view import render_skills, render_skills_refresh

try:
    from logi.claude_code_executor import (
        ClaudeCodeExecutionError,
        run_claude_code_sync,
        select_route,
    )
except Exception:  # Keep Telegram Logi bootable if Claude Code bridge is unavailable.
    ClaudeCodeExecutionError = RuntimeError
    run_claude_code_sync = None
    select_route = None

# ── Learning Loop Consumer (EventBus → Phase 2B learning) ─────────────────────
_LEARNING_LOOP_ENABLED = os.environ.get("AIMS_LEARNING_LOOP_ENABLED", "false").lower() in ("true", "1", "yes")


def _start_learning_loop_background():
    """Start LearningLoopConsumer in a background daemon thread."""
    import asyncio

    async def _run_consumer():
        try:
            from logi.learning_loop_consumer import create_learning_loop_consumer
            consumer = await create_learning_loop_consumer()
            if consumer:
                log.info("LearningLoopConsumer started — subscribed to EventBus")
                # Keep alive until process exits
                while not _stop_event.is_set():
                    await asyncio.sleep(5)
            else:
                log.warning("LearningLoopConsumer creation returned None — EventBus may be down")
        except Exception as exc:
            log.error("LearningLoopConsumer failed: %s", exc)

    def _thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_consumer())
        finally:
            loop.close()

    t = threading.Thread(target=_thread_target, name="learning-loop", daemon=True)
    t.start()
    log.info("Learning loop background thread started")

# Setup logging
log = logging.getLogger(__name__)

# ── Logi skill context loading ─────────────────────────────────────────────────

def _load_logi_skill_context() -> str:
    """Load Logi strategy skill pack from registry."""
    try:
        from agents.agent_skill_loader import load_agent_skill_text

        text = load_agent_skill_text("logi")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        log.info("Logi skill pack loaded: agent=logi chars=%s sha256=%s", len(text), digest)
        return text
    except Exception as exc:
        log.warning("Logi skill pack load failed; continuing without skill pack: %s", exc)
        return ""


# ── config ─────────────────────────────────────────────────────────────────────

TOKEN = (
    os.environ.get("LOGI_BOT_TOKEN")
    or os.environ.get("LOGI_ORCHESTRATOR_BOT_TOKEN")
    or ""
).strip()

ALLOWED_USERS_RAW = os.environ.get("LOGI_ALLOWED_USERS", "").strip()
PROJECT_GOALS_ENABLED = os.environ.get("LOGI_TELEGRAM_PROJECT_GOALS_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
PROJECT_GOAL_INTAKE_MODE = os.environ.get("LOGI_TELEGRAM_GOAL_INTAKE_MODE", "private_text").strip().lower()

# Claude Code CLI backend for Telegram-facing Logi.
# false = keep legacy LogiAgent as default; /cc still uses Claude Code.
# true  = plain text uses Claude Code slot32 by default.
LOGI_CLAUDE_CODE_DEFAULT = os.environ.get("LOGI_CLAUDE_CODE_DEFAULT", "false").lower() in (
    "true",
    "1",
    "yes",
)
LOGI_CLAUDE_CODE_PREFIX = os.environ.get("LOGI_CLAUDE_CODE_PREFIX", "/cc").strip() or "/cc"
LOGI_CLAUDE_CODE_REASONING_PREFIX = os.environ.get("LOGI_CLAUDE_CODE_REASONING_PREFIX", "/ccr").strip() or "/ccr"

if not TOKEN:
    raise SystemExit("Missing LOGI_BOT_TOKEN")

ALLOWED_USERS: set[int] = {
    int(x.strip())
    for x in ALLOWED_USERS_RAW.replace(" ", "").split(",")
    if x.strip().isdigit()
}

BOT_API = f"https://api.telegram.org/bot{TOKEN}"

# ── bot API helpers ────────────────────────────────────────────────────────────

def _api(method: str, payload: dict | None = None) -> dict:
    url = f"{BOT_API}/{method}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload else "GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(chat_id: int, text: str) -> None:
    text = text or "(empty)"
    while len(text) > 3800:
        _api("sendMessage", {"chat_id": chat_id, "text": text[:3800], "disable_web_page_preview": True})
        text = text[3800:]
    _api("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})


# ── agent singleton ────────────────────────────────────────────────────────────

LOGI_SKILL_CONTEXT = _load_logi_skill_context()

_agent = LogiAgent()
_user_locks: dict[int, threading.Lock] = {}
_user_locks_mutex = threading.Lock()


def _get_lock(user_id: int) -> threading.Lock:
    with _user_locks_mutex:
        if user_id not in _user_locks:
            _user_locks[user_id] = threading.Lock()
        return _user_locks[user_id]


# ── message handling ───────────────────────────────────────────────────────────

def _command_of(text: str) -> str:
    if not text.startswith("/"):
        return ""
    return text.split()[0].split("@", 1)[0].strip().lower()

def _proxy_health() -> str:
    checks = {
        "legacy_8082": "http://127.0.0.1:8082/health",
        "slot32_claude_code_8084": "http://127.0.0.1:8084/health",
        "reasoning_8086": "http://127.0.0.1:8086/health",
    }
    result = {}
    for name, url in checks.items():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                raw = r.read().decode("utf-8", errors="replace")
            try:
                result[name] = json.loads(raw)
            except Exception:
                result[name] = raw[:500]
        except Exception as e:
            result[name] = f"unavailable: {e}"
    result["logi_claude_code_default"] = LOGI_CLAUDE_CODE_DEFAULT
    result["claude_code_prefix"] = LOGI_CLAUDE_CODE_PREFIX
    result["claude_code_reasoning_prefix"] = LOGI_CLAUDE_CODE_REASONING_PREFIX
    return json.dumps(result, ensure_ascii=False, indent=2)



def _handle_claude_code_run(
    chat_id: int,
    user_id: int,
    text: str,
    route_name: str | None = None,
) -> None:
    lock = _get_lock(user_id)
    if not lock.acquire(blocking=False):
        send(chat_id, "Still processing your previous request...")
        return

    try:
        if run_claude_code_sync is None:
            send(chat_id, "Claude Code backend is unavailable: import failed.")
            return

        clean_text = text.strip()
        if clean_text.startswith(LOGI_CLAUDE_CODE_REASONING_PREFIX):
            clean_text = clean_text[len(LOGI_CLAUDE_CODE_REASONING_PREFIX):].strip()
            route_name = route_name or "reasoning"
        elif clean_text.startswith(LOGI_CLAUDE_CODE_PREFIX):
            clean_text = clean_text[len(LOGI_CLAUDE_CODE_PREFIX):].strip()
            route_name = route_name or "slot32"

        if not clean_text:
            send(
                chat_id,
                "Usage:\n"
                f"{LOGI_CLAUDE_CODE_PREFIX} <task>  — Claude Code slot32\n"
                f"{LOGI_CLAUDE_CODE_REASONING_PREFIX} <task> — Claude Code reasoning",
            )
            return

        selected_route = route_name or (select_route(clean_text) if select_route else "slot32")
        send(chat_id, f"Logi → Claude Code CLI started. route={selected_route}")

        preamble = skill_context_preamble(clean_text, top_k=5)
        backend_prompt = (
            f"{preamble}\n\nUser task:\n{clean_text}"
            if preamble else clean_text
        )
        result = run_claude_code_sync(backend_prompt, route_name=selected_route)
        send(chat_id, result)
    except ClaudeCodeExecutionError as exc:
        send(chat_id, "Claude Code backend error:\n" + str(exc)[-3000:])
    except Exception:
        send(chat_id, "Claude Code bridge error:\n" + traceback.format_exc()[-3000:])
    finally:
        lock.release()

def _handle_run(chat_id: int, user_id: int, text: str) -> None:
    lock = _get_lock(user_id)
    if not lock.acquire(blocking=False):
        send(chat_id, "Still processing your previous request...")
        return

    try:
        def notify(msg: str) -> None:
            send(chat_id, msg)

        result = _agent.run(user_id, text, notify, skill_context=LOGI_SKILL_CONTEXT)
        send(chat_id, result)
    except Exception:
        send(chat_id, "Agent error:\n" + traceback.format_exc()[-2000:])
    finally:
        lock.release()


def _handle_project_goal_intake(chat_id: int, user_id: int, msg: dict, text: str) -> None:
    try:
        record = ingest_telegram_goal_text(
            text=text,
            chat_id=chat_id,
            user_id=user_id,
            message_id=int(msg.get("message_id", 0) or 0),
            chat_type=str(msg.get("chat", {}).get("type") or "private"),
        )
        send(
            chat_id,
            "Project goal registered for Logi automation.\n"
            f"Goal ID: {record.goal_id}\n"
            f"Status: {record.status}\n"
            f"Architecture: {record.architecture_dir}\n"
            f"Queued: {record.autorunner_request_path}\n\n"
            "The Telegram message is now a project architecture artifact; the queue item is transport only.",
        )
    except Exception:
        send(chat_id, "Project goal intake error:\n" + traceback.format_exc()[-2000:])


def _project_goal_index_text(limit: int = 10) -> str:
    index_path = DEFAULT_ARCHITECTURE_ROOT / GOAL_INDEX_JSON
    if not index_path.exists():
        return "No project goals registered yet."
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return "Project goal index exists but could not be read."
    goals = index.get("goals") or []
    if not goals:
        return "No project goals registered yet."
    lines = ["Project goals:"]
    for item in goals[:limit]:
        lines.append(
            f"- {item.get('goal_id')} [{item.get('status')}] "
            f"{item.get('title')} — {item.get('architecture_dir')}"
        )
    return "\n".join(lines)


def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    chat_type = str(msg.get("chat", {}).get("type") or "")
    user_id = int(msg.get("from", {}).get("id", 0))
    text = (msg.get("text") or "").strip()
    command = _command_of(text)

    if command == "/whoami":
        send(chat_id, f"Your Telegram user id: {user_id}")
        return

    if not user_id or user_id not in ALLOWED_USERS:
        send(chat_id, f"Access denied. Your id: {user_id}")
        return

    if command in {"/start", "/help"}:
        send(chat_id, (
            "LogiAgent — AIMS AI-first project operator\n\n"
            "Plain text is treated as a request/question first. Project goals are registered only "
            "through /goal or an explicit request to register a project goal.\n\n"
            "Commands:\n"
            "/skills — show indexed Claude Code/AIMS skills and capabilities\n"
            "/skills refresh — rebuild the compact skills index\n"
            "/goal <text> — register a project goal from this private chat\n"
            "/goals — list registered project goals\n"
            "/plans — list your plans\n"
            "/plan <id> — show plan details\n"
            "/clear — reset conversation history\n"
            "/status — proxy, agent, and project automation status\n"
            "/whoami — show your user id\n"
            f"{LOGI_CLAUDE_CODE_PREFIX} <task> — run task through Claude Code CLI slot32\n"
            f"{LOGI_CLAUDE_CODE_REASONING_PREFIX} <task> — run task through Claude Code CLI reasoning route\n\n"
            "Examples:\n"
            "• Build the Logi project automation executor for Telegram goals\n"
            "• Register the DOCGEN quality loop as a project automation objective\n"
            "• Create an implementation plan for AIMS maintenance strategy generation\n"
            "• Verify current project automation readiness"
        ))
        return

    if command == "/clear":
        _agent.clear_history(user_id)
        send(chat_id, "Conversation history cleared.")
        return

    if command == "/skills":
        arg = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        if arg.lower() == "refresh":
            send(chat_id, render_skills_refresh())
        else:
            send(chat_id, render_skills(arg))
        return

    if command == LOGI_CLAUDE_CODE_REASONING_PREFIX.lower():
        _handle_claude_code_run(chat_id, user_id, text, route_name="reasoning")
        return

    if command == LOGI_CLAUDE_CODE_PREFIX.lower():
        _handle_claude_code_run(chat_id, user_id, text, route_name="slot32")
        return

    if command == "/status":
        health = _proxy_health()
        plans = list_plans(user_id)
        active = [p for p in plans if p.status in ("draft", "active")]
        auto = autorunner_status(AutorunnerConfig())
        send(
            chat_id,
            f"Proxy health:\n{health}\n\n"
            f"Active plans: {len(active)}\n\n"
            "Project automation:\n"
            f"- status: {auto.get('status')}\n"
            f"- pid_alive: {auto.get('pid_alive')}\n"
            f"- pending goals: {auto.get('pending_count')}\n"
            f"- inbox: {auto.get('inbox_dir')}",
        )
        return

    if command == "/goals":
        send(chat_id, _project_goal_index_text())
        return

    if command == "/plans":
        plans = list_plans(user_id)
        if not plans:
            send(chat_id, "No plans found.")
            return
        lines = []
        for p in plans[:10]:
            lines.append(f"• {p.id} [{p.status}] {p.title} ({len(p.steps)} steps)")
        send(chat_id, "\n".join(lines))
        return

    if command == "/goal":
        goal_text = text.split(" ", 1)[1].strip() if " " in text else ""
        if not goal_text:
            send(chat_id, "Usage: /goal <project goal text>")
            return
        if chat_type != "private":
            send(chat_id, "Project goals are accepted only from the personal Logi chat.")
            return
        _handle_project_goal_intake(chat_id, user_id, msg, goal_text)
        return

    if command == "/plan":
        plan_id = text.split(" ", 1)[1].strip() if " " in text else ""
        if not plan_id:
            send(chat_id, "Usage: /plan <id>")
            return
        # Prevent legacy /plan <id> route from consuming reserved planning horizons.
        if plan_id.lower() in {"day", "week", "month", "strategic"}:
            send(
                chat_id,
                "Request recognized: plan_view "
                f"({plan_id.lower()}).\n"
                "Logi is proceeding under the approved strategy.\n"
                "Review the current plan and reply with corrections if needed.\n"
                "Human approval is required only for exception actions.",
            )
            return
        plan = load_plan(user_id, plan_id)
        if not plan:
            send(chat_id, f"Plan {plan_id} not found")
            return
        lines = [plan.summary()]
        for s in plan.steps:
            if s.result:
                lines.append(f"\nStep {s.id} result:\n{s.result[:400]}")
        send(chat_id, "\n".join(lines))
        return

    # ── Logi Assistant Gateway (Логи, / /logi prefix only) ──────────────
    try:
        from ops.telegram.logi_bot_assistant import (
            should_route_to_gateway, handle_gateway_message,
        )
        if should_route_to_gateway(text):
            send(chat_id, handle_gateway_message(
                text, str(chat_id),
                str(msg.get("from", {}).get("id", ""))
            ))
            return
    except Exception:
        pass  # Never break the existing bot
    # ────────────────────────────────────────────────────────────────────

    if text.startswith("/") and command:
        send(
            chat_id,
            "Unknown Logi command. Use /help or /skills. "
            "This was not registered as a project goal.",
        )
        return

    if LOGI_CLAUDE_CODE_DEFAULT:
        _handle_claude_code_run(chat_id, user_id, text, route_name=None)
        return

    routed = route_intent(text)
    if routed.intent == "skills_query":
        send(chat_id, render_skills(text))
        return
    if routed.intent == "register_goal" and routed.confidence >= 0.9:
        if chat_type != "private":
            send(chat_id, "Project goals are accepted only from the personal Logi chat.")
            return
        _handle_project_goal_intake(chat_id, user_id, msg, text)
        return

    # Natural-language-first intent routing for planning/status UX.
    intent = evaluate_intent_policy(interpret_syntax_intent(text))
    if intent.intent_type != "unknown":
        send(chat_id, render_policy_response(intent))
        return

    if not text:
        return

    threading.Thread(
        target=_handle_run,
        args=(chat_id, user_id, text),
        daemon=True,
    ).start()


# ── main polling loop ──────────────────────────────────────────────────────────

_stop_event = threading.Event()


def _handle_sigterm(signum, frame) -> None:
    print("SIGTERM received — shutting down cleanly")
    _stop_event.set()


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_sigterm)

    print(f"LogiAgent Telegram Bot started")
    print(f"Allowed users: {sorted(ALLOWED_USERS) if ALLOWED_USERS else 'NONE'}")

    # Start learning loop consumer in background if enabled
    if _LEARNING_LOOP_ENABLED:
        _start_learning_loop_background()
    else:
        print("Learning loop consumer disabled (set AIMS_LEARNING_LOOP_ENABLED=true to enable)")

    # Clear any webhook so long-polling works
    try:
        _api("deleteWebhook", {"drop_pending_updates": False})
        print("Webhook cleared")
    except Exception as e:
        print(f"deleteWebhook failed (non-fatal): {e}")

    offset = 0
    _409_backoff = 5
    while not _stop_event.is_set():
        try:
            params = urllib.parse.urlencode({"timeout": 30, "offset": offset})
            with urllib.request.urlopen(f"{BOT_API}/getUpdates?{params}", timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            _409_backoff = 5  # reset on success
            for update in data.get("result", []):
                offset = max(offset, update["update_id"] + 1)
                if "message" in update:
                    handle_message(update["message"])

        except KeyboardInterrupt:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 409:
                # Another instance or webhook conflict — back off and retry
                print(f"409 Conflict from Telegram (another instance running?), retry in {_409_backoff}s")
                _stop_event.wait(_409_backoff)
                _409_backoff = min(_409_backoff * 2, 120)
            else:
                print(traceback.format_exc())
                _stop_event.wait(5)
        except Exception:
            print(traceback.format_exc())
            _stop_event.wait(5)


if __name__ == "__main__":
    main()
