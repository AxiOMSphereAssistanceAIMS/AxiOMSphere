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
from logi.syntax_interpreter import interpret_syntax_intent
from logi.syntax_policy import evaluate_intent_policy, render_policy_response

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

def _proxy_health() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8082/health", timeout=10) as r:
            data = json.loads(r.read())
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Proxy unavailable: {e}"


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


def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    user_id = int(msg.get("from", {}).get("id", 0))
    text = (msg.get("text") or "").strip()

    if text.startswith("/whoami"):
        send(chat_id, f"Your Telegram user id: {user_id}")
        return

    if not user_id or user_id not in ALLOWED_USERS:
        send(chat_id, f"Access denied. Your id: {user_id}")
        return

    if text.startswith("/start") or text.startswith("/help"):
        send(chat_id, (
            "LogiAgent — AIMS orchestrator\n\n"
            "Just type your request in plain language.\n\n"
            "Commands:\n"
            "/plans — list your plans\n"
            "/plan <id> — show plan details\n"
            "/clear — reset conversation history\n"
            "/status — proxy + agent status\n"
            "/whoami — show your user id\n\n"
            "Examples:\n"
            "• Создай план для разработки процедуры по HSE для бурения\n"
            "• Найди документы по ISO 45001\n"
            "• Что у нас есть по ПЛА?\n"
            "• Добавь шаг в план: поиск нормативных требований\n"
            "• Выполни план"
        ))
        return

    if text.startswith("/clear"):
        _agent.clear_history(user_id)
        send(chat_id, "Conversation history cleared.")
        return

    if text.startswith("/status"):
        health = _proxy_health()
        plans = list_plans(user_id)
        active = [p for p in plans if p.status in ("draft", "active")]
        send(chat_id, f"Proxy health:\n{health}\n\nActive plans: {len(active)}")
        return

    if text.startswith("/plans"):
        plans = list_plans(user_id)
        if not plans:
            send(chat_id, "No plans found.")
            return
        lines = []
        for p in plans[:10]:
            lines.append(f"• {p.id} [{p.status}] {p.title} ({len(p.steps)} steps)")
        send(chat_id, "\n".join(lines))
        return

    # Natural-language-first intent routing for planning/status UX.
    intent = evaluate_intent_policy(interpret_syntax_intent(text))
    if intent.intent_type != "unknown":
        send(chat_id, render_policy_response(intent))
        return

    if text.startswith("/plan "):
        plan_id = text.split(" ", 1)[1].strip()
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
