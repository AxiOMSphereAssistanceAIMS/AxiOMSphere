"""Dry-run scheduler bridge for planned actions in long-running harness."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from logi.planned_actions import PlannedAction


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def evaluate_due_actions(actions: list[PlannedAction], *, dry_run: bool = True) -> dict[str, Any]:
    """Evaluate due/pending planned actions without destructive scheduling."""
    now = datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    pending = [a for a in actions if a.status == "PENDING"]
    for action in pending:
        due_dt = _parse_iso(action.due_time)
        is_due = (due_dt is None) or (due_dt <= now)
        if is_due:
            due.append(
                {
                    "action_id": action.action_id,
                    "title": action.title,
                    "schedule_type": action.schedule_type,
                    "due_time": action.due_time,
                    "dry_run_selected": dry_run,
                }
            )
    return {
        "status": "PASS",
        "dry_run": dry_run,
        "now_utc": now.isoformat(),
        "pending_total": len(pending),
        "due_total": len(due),
        "due_actions": due,
    }

