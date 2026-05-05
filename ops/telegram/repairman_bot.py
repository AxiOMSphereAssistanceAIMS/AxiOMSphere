#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = pathlib.Path("/home/axi_omi_sphere/aims-workspace")
RUN_REPAIRMAN = ROOT / "ops/claude_code/run_repairman.sh"
USE_MODEL = ROOT / "ops/claude_code/use_model.sh"
CURRENT_MODEL = ROOT / "ops/claude_code/current_model.env"
AUDIT_DIR = ROOT / "aims_workspace/audit/telegram_repairman"
ISSUES_DIR = AUDIT_DIR / "issues"
LOGS_DIR = AUDIT_DIR / "logs"

# Automation policy flags
AUTO_INSPECT = True      # Always safe, read-only
AUTO_STATUS = True       # Always safe, informational
AUTO_CURRENT = True      # Safe when retry threshold reached
AUTO_REPAIR = True       # Safe when concept unchanged
AUTO_FIX = True          # Safe for operability restoration
AUTO_MODEL = True        # Safe for system reliability

TOKEN = (
    os.environ.get("REPAIRMAN_BOT_TOKEN")
    or os.environ.get("TELEGRAM_BOT_TOKEN")
    or ""
).strip()
ALLOWED_USERS_RAW = os.environ.get("AIMS_REPAIRMAN_ALLOWED_USERS", "").strip()

if not TOKEN:
    raise SystemExit("Missing REPAIRMAN_BOT_TOKEN")

ALLOWED_USERS = {
    int(x.strip())
    for x in ALLOWED_USERS_RAW.replace(" ", "").split(",")
    if x.strip().isdigit()
}

BOT_API = f"https://api.telegram.org/bot{TOKEN}"

LOCK_TIMEOUT_SEC = int(os.environ.get("REPAIRMAN_LOCK_TIMEOUT", "600"))  # 10 min default

_run_lock = threading.Lock()
_lock_acquired_at: float = 0.0


def _acquire_lock() -> bool:
    """Acquire the run lock, auto-releasing if held longer than LOCK_TIMEOUT_SEC."""
    global _lock_acquired_at
    with threading.Lock():  # short guard for the timestamp check
        if _run_lock.acquire(blocking=False):
            _lock_acquired_at = time.monotonic()
            return True
        # Check if lock has timed out
        if time.monotonic() - _lock_acquired_at > LOCK_TIMEOUT_SEC:
            # Force-release stale lock and acquire
            try:
                _run_lock.release()
            except RuntimeError:
                pass
            if _run_lock.acquire(blocking=False):
                _lock_acquired_at = time.monotonic()
                return True
        return False


def _release_lock() -> None:
    global _lock_acquired_at
    _lock_acquired_at = 0.0
    try:
        _run_lock.release()
    except RuntimeError:
        pass


# Legacy alias used throughout the module
class _LockCompat:
    def acquire(self, blocking: bool = True) -> bool:
        return _acquire_lock()

    def release(self) -> None:
        _release_lock()


RUN_LOCK = _LockCompat()

ISSUES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def now_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def api(method: str, payload: dict | None = None) -> dict:
    url = f"{BOT_API}/{method}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload else "GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    while len(text) > 3500:
        api("sendMessage", {"chat_id": chat_id, "text": text[:3500], "disable_web_page_preview": True})
        text = text[3500:]

    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    api("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


def current_model_text() -> str:
    if not CURRENT_MODEL.exists():
        return "No current_model.env found. Default: local-nemotron"
    return CURRENT_MODEL.read_text(encoding="utf-8").strip()


def model_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Kiro Sonnet 4.5", "callback_data": "model:kiro-sonnet"}],
            [{"text": "KR Sonnet 4.5", "callback_data": "model:kr-sonnet"}],
            [{"text": "Kiro Haiku 4.5", "callback_data": "model:kiro-haiku"}],
            [{"text": "KR Haiku 4.5", "callback_data": "model:kr-haiku"}],
            [{"text": "Local Nemotron fallback", "callback_data": "model:local-nemotron"}],
            [{"text": "Auto repair fallback chain", "callback_data": "model:auto"}],
            [{"text": "Show current", "callback_data": "model:current"}],
        ]
    }


def set_model(profile: str) -> tuple[bool, str]:
    result = subprocess.run(
        [str(USE_MODEL), profile],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    return result.returncode == 0, result.stdout


def proxy_health() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8082/health", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Proxy health failed: {type(exc).__name__}: {exc}"


def write_issue_file(prefix: str, user_id: int, text: str) -> pathlib.Path:
    path = ISSUES_DIR / f"{now_id()}_{user_id}_{prefix}.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_repairman(chat_id: int, user_id: int, task_text: str, mode: str, auto_triggered: bool = False) -> None:
    """Execute repairman task.

    Args:
        chat_id: Telegram chat id
        user_id: Telegram user id
        task_text: Task description
        mode: Task mode (inspect|repair|fix)
        auto_triggered: True if triggered by LogiOrchestrator/ArgusAgent
    """
    if not RUN_LOCK.acquire(blocking=False):
        send_message(chat_id, "Repairman is already running another task.")
        return

    try:
        issue_path = write_issue_file(mode, user_id, task_text)
        log_path = LOGS_DIR / f"{issue_path.stem}.log"

        model_info = current_model_text().split('\n')[0] if current_model_text() else "unknown"
        trigger_source = "AUTO" if auto_triggered else "MANUAL"
        send_message(
            chat_id,
            f"Task accepted, thinking...\nModel: {model_info}\nTask: {mode}\nSource: {trigger_source}"
        )

        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["TERM"] = env.get("TERM", "xterm")

        started = time.time()
        proc = subprocess.run(
            [str(RUN_REPAIRMAN), str(ROOT), str(issue_path)],
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=3600,
        )
        elapsed = round(time.time() - started, 1)
        output = proc.stdout or ""
        log_path.write_text(output, encoding="utf-8", errors="replace")

        status = "SUCCESS" if proc.returncode == 0 else f"FAILED exit={proc.returncode}"
        send_message(
            chat_id,
            f"task finished.\n"
            f"Status: {status}\n"
            f"Elapsed: {elapsed}s\n"
        )

    except subprocess.TimeoutExpired:
        send_message(chat_id, "Repairman task timed out after 3600 seconds.")
    except Exception:
        send_message(chat_id, "Repairman bot error:\n" + traceback.format_exc()[-3000:])
    finally:
        RUN_LOCK.release()


def help_text() -> str:
    return """AIMS Repairman Bot

Commands:
/whoami
  Show your Telegram user id.

/model [AUTO]
  Choose model with buttons.
  Automatic: Maintains system operability, switches models for reliability.

/current [AUTO]
  Show current model.
  Automatic: When changes required multiple retries or failed after 5 attempts.

/status [AUTO]
  Show proxy health and current model.
  Automatic: Always safe, informational only.

/inspect [AUTO]
  Read-only inspection.
  Automatic: Safe, no modifications.

/repair [AUTO]
  Repairman task according to permission model.
  Automatic: When concept review passed and production process output remains unchanged.

/fix [AUTO]
  Explicitly allows project file edits inside /home/axi_omi_sphere/aims-workspace.
  Automatic: Restores process operability without changing concept.
  Still forbids secrets, databases, production data, model files, git push, deploy, and service restarts unless separately allowed.

[AUTO] = Can be triggered automatically by LogiOrchestrator or ArgusAgent.
"""


def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    user_id = int(msg.get("from", {}).get("id", 0))
    text = msg.get("text", "") or ""

    if text.startswith("/whoami"):
        send_message(chat_id, f"Your Telegram user id: {user_id}")
        return

    if not is_allowed(user_id):
        send_message(chat_id, f"Access denied.\nYour Telegram user id: {user_id}")
        return

    if text.startswith("/start") or text.startswith("/help"):
        send_message(chat_id, help_text())
        return

    if text.startswith("/model"):
        send_message(chat_id, "Choose repairman model:", reply_markup=model_keyboard())
        return

    if text.startswith("/current"):
        send_message(chat_id, current_model_text())
        return

    if text.startswith("/status"):
        send_message(chat_id, "Current model:\n" + current_model_text() + "\n\nProxy health:\n" + proxy_health())
        return

    if text.startswith("/inspect"):
        task = text.replace("/inspect", "", 1).strip()
        if not task:
            send_message(chat_id, "Usage: /inspect <task>")
            return
        full_task = "Inspect only. Do not modify files.\n\nTask:\n" + task
        threading.Thread(target=run_repairman, args=(chat_id, user_id, full_task, "inspect"), daemon=True).start()
        return

    if text.startswith("/repair"):
        task = text.replace("/repair", "", 1).strip()
        if not task:
            send_message(chat_id, "Usage: /repair <task>")
            return
        full_task = "Run as AIMS Claude Code Repairman. Follow the repairman permission model.\n\nTask:\n" + task
        threading.Thread(target=run_repairman, args=(chat_id, user_id, full_task, "repair"), daemon=True).start()
        return

    if text.startswith("/fix"):
        task = text.replace("/fix", "", 1).strip()
        if not task:
            send_message(chat_id, "Usage: /fix <task>")
            return
        full_task = (
            "You have explicit permission to modify project files inside /home/axi_omi_sphere/aims-workspace as needed for this task.\n"
            "Do not modify secrets, credentials, databases, production data, model files, external storage, deploy, git push, or restart services unless separately explicitly requested.\n\n"
            "Task:\n" + task
        )
        threading.Thread(target=run_repairman, args=(chat_id, user_id, full_task, "fix"), daemon=True).start()
        return

    # Plain text without a command → treat as /repair task
    if text and not text.startswith("/"):
        full_task = "Run as AIMS Claude Code Repairman. Follow the repairman permission model.\n\nTask:\n" + text
        threading.Thread(target=run_repairman, args=(chat_id, user_id, full_task, "repair"), daemon=True).start()
        return

    send_message(chat_id, "Unknown command. Use /help")


def handle_callback(cb: dict) -> None:
    callback_id = cb["id"]
    chat_id = cb["message"]["chat"]["id"]
    user_id = int(cb.get("from", {}).get("id", 0))
    data = cb.get("data", "")

    if not is_allowed(user_id):
        answer_callback(callback_id, "Access denied")
        send_message(chat_id, f"Access denied. Your Telegram user id: {user_id}")
        return

    if data == "model:current":
        answer_callback(callback_id, "Current model")
        send_message(chat_id, current_model_text())
        return

    if data.startswith("model:"):
        profile = data.split(":", 1)[1]
        ok, out = set_model(profile)
        answer_callback(callback_id, "Model updated" if ok else "Model update failed")
        send_message(chat_id, out + "\n\nCurrent:\n" + current_model_text())
        return


def main() -> None:
    print("AIMS Repairman Telegram Bot started")
    print(f"Allowed users: {sorted(ALLOWED_USERS) if ALLOWED_USERS else 'NONE'}")

    offset = 0
    while True:
        try:
            params = urllib.parse.urlencode({"timeout": 30, "offset": offset})
            with urllib.request.urlopen(f"{BOT_API}/getUpdates?{params}", timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for update in data.get("result", []):
                offset = max(offset, update["update_id"] + 1)
                if "message" in update:
                    handle_message(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])

        except KeyboardInterrupt:
            raise
        except Exception:
            print(traceback.format_exc())
            time.sleep(5)


if __name__ == "__main__":
    main()
