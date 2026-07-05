"""
logi_bot_assistant.py

Guarded assistant entrypoint for the Telegram Logi-bot.

Activates ONLY on explicit addressing:
  - "Логи, ..." or "Logi, ..." (case-insensitive)
  - "/logi ..."

All other messages pass through to the existing bot without any change.
"""
from __future__ import annotations
import re

_PREFIX_RE = re.compile(
    r"^(Логи\s*,|Logi\s*,|/logi\b)",
    re.IGNORECASE,
)
_TELEGRAM_MAX = 3900


def should_route_to_gateway(text: str) -> bool:
    return bool(_PREFIX_RE.match((text or "").strip()))


def _strip_prefix(text: str) -> str:
    return _PREFIX_RE.sub("", text.strip()).strip()


def handle_gateway_message(text: str, chat_id: str, from_user: str = "") -> str:
    """
    Full gateway pipeline. Returns a Telegram-safe string (max 3900 chars).
    Never raises — catches all exceptions and returns a safe error message.
    """
    try:
        from ops.agents.logi_assistant_gateway import process_gateway_message
        clean = _strip_prefix(text)
        result = process_gateway_message(clean, source="telegram",
                                         chat_id=chat_id, from_user=from_user)
        return _format_response(result)
    except Exception as exc:
        return f"STATUS: FAILED\nSUMMARY:\nGateway error: {exc}"


def _format_response(result: dict) -> str:
    status = result.get("status", "UNKNOWN")
    area = result.get("mentioned_area", "")
    summary = result.get("summary", result.get("operational_summary", ""))
    warning = result.get("warning", "")
    sources = ", ".join(result.get("sources_used", []))
    reason = result.get("reason", "")

    lines = [f"STATUS: {status}"]
    if area:
        lines.append(f"AREA: {area}")
    if warning:
        lines.append(f"⚠ {warning}")
    if reason and status in ("BLOCKED", "REQUIRES_CONFIRMATION"):
        lines.append(f"REASON: {reason}")
    if summary:
        lines.append(f"\nSUMMARY:\n{summary[:800]}")
    if sources:
        lines.append(f"\nSOURCES: {sources}")

    text = "\n".join(lines)
    if len(text) > _TELEGRAM_MAX:
        text = text[:_TELEGRAM_MAX - 60] + "\n\n[truncated — response exceeded Telegram limit]"
    return text
