"""
operational_context_merger.py

Merge static schedule + live Telegram signals into a unified operational
context dict. Live signal takes priority; static-only answer must disclose
that live context was unavailable.
"""
from __future__ import annotations
import re

_OPERATIONAL_RE = re.compile(
    r"\b(today|сегодня|now|сейчас|scheduled|запланировано|running|идёт|"
    r"training|обучение|nightly|ночн\w+|график|tonight|прямо\s+сейчас|"
    r"current|текущ\w+|нынешн\w+|scheduler|статус)\b",
    re.IGNORECASE,
)


def is_operational_question(text: str) -> bool:
    return bool(_OPERATIONAL_RE.search(text or ""))


def merge_operational_context(
    user_query: str,
    static_schedule: dict | None,
    telegram_context: list[dict],
    scheduler_context: dict | None,
    now_utc: str,
) -> dict:
    live_training = [
        m for m in (telegram_context or [])
        if "training" in m.get("detected_topics", [])
        and m.get("confidence", 0) >= 0.7
    ]
    static_has_training = bool(
        static_schedule and any(
            "training" in v.lower() or "ft_prepare" in v.lower()
            for v in static_schedule.values()
        )
    )

    sources: list[str] = []
    if static_schedule:
        sources.append("static_schedule")
    if live_training:
        sources.append("telegram_operational_context")
    if scheduler_context:
        sources.append("scheduler_context")

    if live_training:
        best = live_training[0]
        raw_st = best.get("detected_status", "UNKNOWN")
        status_map = {
            "TRAINING_SCHEDULED": "TRAINING_SCHEDULED_TODAY",
            "TRAINING_RUNNING": "TRAINING_RUNNING",
            "TRAINING_COMPLETED": "TRAINING_COMPLETED",
            "TRAINING_FAILED": "TRAINING_FAILED",
        }
        status = status_map.get(raw_st, "TRAINING_SCHEDULED_TODAY" if static_has_training else "UNKNOWN")
        candidate = best.get("candidate") or "unknown"
        pairs_ready = best.get("pairs_ready")
        pairs_required = best.get("pairs_required")
        pairs_str = f"{pairs_ready}/{pairs_required}" if pairs_ready and pairs_required else "unknown"
        scheduled_at = best.get("scheduled_at_utc") or "unknown"
        model_slot = best.get("model_slot") or "unknown"
        answer = (
            f"✅ Training is scheduled today.\n"
            f"Model: {candidate}\nSlot: {model_slot}\n"
            f"Pairs ready: {pairs_str}\nScheduled at: {scheduled_at}\n"
            f"(Sources: live Telegram + static schedule)"
        )
        return {
            "status": status,
            "confidence": best.get("confidence", 0.9),
            "sources_used": sources,
            "static_schedule_match": static_has_training,
            "live_signal_match": True,
            "model_slot": model_slot,
            "candidate": candidate,
            "scheduled_at_utc": scheduled_at,
            "answer_summary": answer,
            "now_utc": now_utc,
        }

    # Static only
    sched_str = "; ".join(
        f"{k}: {v}" for k, v in (static_schedule or {}).items()
        if "training" in v.lower() or "ft_prepare" in v.lower()
    )
    if static_has_training:
        answer = (
            f"Static schedule: {sched_str}.\n"
            f"Live Telegram/Argus/Traini context was not available; "
            f"answer based only on static schedule."
        )
        return {
            "status": "TRAINING_SCHEDULED_TODAY",
            "confidence": 0.5,
            "sources_used": sources,
            "static_schedule_match": True,
            "live_signal_match": False,
            "model_slot": None, "candidate": None, "scheduled_at_utc": None,
            "answer_summary": answer,
            "now_utc": now_utc,
        }

    return {
        "status": "NO_TRAINING_FOUND",
        "confidence": 0.4,
        "sources_used": sources,
        "static_schedule_match": False,
        "live_signal_match": False,
        "model_slot": None, "candidate": None, "scheduled_at_utc": None,
        "answer_summary": (
            "No training found. "
            "Live Telegram/Argus/Traini context was not available; "
            "answer based only on static schedule."
        ),
        "now_utc": now_utc,
    }
