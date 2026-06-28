#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("AIMS_ROOT", "/home/axi_omi_sphere/aims-workspace")).resolve()
LAUNCHER = ROOT / "ops/scripts/claude_local_oneshot.sh"
CHECKPOINT_DIR = ROOT / "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def normalize_telegram_text(text: str, limit: int = 800) -> str:
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text or "")
    clean = clean.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in clean.splitlines() if line.strip()]
    if not lines:
        return "(empty)"
    compact = "\n".join(lines)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def build_prompt(message: str) -> str:
    return (
        "You are local AIMS slot32 and this is a Telegram production simulation.\n"
        f"Telegram message:\n{message.strip()}\n\n"
        "Rules:\n"
        "- Use the canonical repaired one-shot launcher path.\n"
        "- Keep the answer Telegram-safe and concise.\n"
        "- Do not expose raw logs, secrets, or stack traces.\n"
        "- If the request is a status check, summarize launcher health.\n"
        "- Return only the final answer.\n"
    )


def run_launcher(prompt: str, timeout_s: int) -> subprocess.CompletedProcess[str]:
    if not LAUNCHER.exists():
        raise FileNotFoundError(f"Missing launcher: {LAUNCHER}")
    return subprocess.run(
        [str(LAUNCHER), prompt],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def telegram_payload(chat_id: str, text: str) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }


def send_telegram(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = telegram_payload(chat_id, text)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return True, raw
    except Exception as exc:
        return False, repr(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate Telegram slot32 production requests.")
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    parser.add_argument("--send-real", action="store_true", help="Send to Telegram if credentials are available")
    parser.add_argument("--message", action="append", default=[], help="Telegram message to simulate; repeatable")
    parser.add_argument("--evidence-dir", default="", help="Evidence directory")
    parser.add_argument("--timeout-s", type=int, default=240)
    parser.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_GROUP_ID") or "")
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir or (ROOT / "aims_workspace/agent_architecture_status" / f"claude_slot32_telegram_prod_sim_{utc_stamp()}"))
    evidence_dir.mkdir(parents=True, exist_ok=True)

    messages = args.message or [
        "/slot32 hello",
        '/slot32 ooda "check launcher health"',
        "/slot32 summarize the launcher health, lock state, and whether Telegram-safe responses are working",
    ]

    launcher_health = read_json(CHECKPOINT_DIR / "launcher_health.json")
    launcher_health_latest = read_json(CHECKPOINT_DIR / "slot32_launcher_health_latest.json")
    lock_status = read_json(CHECKPOINT_DIR / "slot32_lock_status.json")
    context_budget = read_json(CHECKPOINT_DIR / "context_budget.json") or read_json(CHECKPOINT_DIR / "slot32_context_budget_latest.json")
    transcript_guard = read_json(CHECKPOINT_DIR / "transcript_guard_report.json")

    results: list[dict[str, Any]] = []
    telegram_env = {
        "token": (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("LOGI_BOT_TOKEN") or "").strip(),
        "chat_id": args.chat_id.strip(),
    }
    telegram_sent = False
    telegram_send_error = ""

    for idx, message in enumerate(messages, start=1):
        prompt = build_prompt(message)
        stdout_path = evidence_dir / f"telegram_sim_{idx:02d}_stdout.txt"
        stderr_path = evidence_dir / f"telegram_sim_{idx:02d}_stderr.txt"
        payload_path = evidence_dir / f"telegram_sim_{idx:02d}_payload.json"

        launcher_timeout = False
        try:
            proc = run_launcher(prompt, args.timeout_s)
            stdout_text = proc.stdout or ""
            stderr_text = proc.stderr or ""
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            launcher_timeout = True
            stdout_text = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr_text = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            if not stderr_text.strip():
                stderr_text = f"TIMEOUT after {args.timeout_s}s"
            returncode = 124

        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")

        safe_answer = normalize_telegram_text(stdout_text or stderr_text, 800)
        payload = telegram_payload(telegram_env["chat_id"] or "dry-run", safe_answer)
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        sent = False
        send_result = ""
        if args.send_real and not args.dry_run and telegram_env["token"] and telegram_env["chat_id"]:
            sent, send_result = send_telegram(telegram_env["token"], telegram_env["chat_id"], safe_answer)
            telegram_sent = telegram_sent or sent
            if not sent:
                telegram_send_error = send_result

        results.append(
            {
                "message": message,
                "prompt_chars": len(prompt),
                "returncode": returncode,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "payload_path": str(payload_path),
                "telegram_safe_answer": safe_answer,
                "telegram_sent": sent,
                "telegram_send_result": send_result,
                "launcher_timeout": launcher_timeout,
                "contains_413": "413" in (stdout_text or "") or "413" in (stderr_text or ""),
                "contains_401": "401" in (stdout_text or "") or "401" in (stderr_text or ""),
                "contains_429": "429" in (stdout_text or "") or "429" in (stderr_text or ""),
            }
        )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "launcher": str(LAUNCHER),
        "evidence_dir": str(evidence_dir),
        "commands": messages,
        "dry_run": bool(args.dry_run or not args.send_real),
        "send_real": bool(args.send_real and not args.dry_run),
        "telegram_env": {
            "token_present": bool(telegram_env["token"]),
            "chat_id_present": bool(telegram_env["chat_id"]),
        },
        "launcher_health": launcher_health,
        "launcher_health_latest": launcher_health_latest,
        "slot32_lock_status": lock_status,
        "context_budget": context_budget,
        "transcript_guard_report": transcript_guard,
        "results": results,
        "telegram_sent": telegram_sent,
        "telegram_send_error": telegram_send_error,
        "notes": "Telegram payloads are compact and source data stays in files.",
    }
    (evidence_dir / "telegram_simulation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        "status": "PASS" if all(r["returncode"] == 0 for r in results) else "DEGRADED",
        "evidence_dir": str(evidence_dir),
        "results": [
            {
                "message": r["message"],
                "returncode": r["returncode"],
                "launcher_timeout": r.get("launcher_timeout", False),
                "telegram_safe_answer": r["telegram_safe_answer"][:240],
            }
            for r in results
        ],
    }
    (evidence_dir / "telegram_simulation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
