from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LONGRUN_ROOT = ROOT / "aims_workspace" / "long_running_self_regulation" / "runs"
DUBAI = timezone(timedelta(hours=4))


@dataclass
class ScheduleDecision:
    action_id: str
    decision: str
    reason: str
    conflict_type: str
    original_time: str
    proposed_time: str
    queue_position: int
    active_run_context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_active_long_run() -> dict[str, Any]:
    if not LONGRUN_ROOT.exists():
        return {"active": False, "run_id": "", "evidence": "longrun_root_missing"}
    runs = [p for p in LONGRUN_ROOT.iterdir() if p.is_dir() and p.name.startswith("long_running_self_regulation_v1_")]
    if not runs:
        return {"active": False, "run_id": "", "evidence": "no_runs_found"}
    latest = sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    # conservative heuristic: recent write activity in last 20 minutes means active
    recent_sec = (datetime.now(timezone.utc).timestamp() - latest.stat().st_mtime)
    active = recent_sec < 1200
    return {
        "active": active,
        "run_id": latest.name,
        "seconds_since_last_write": int(recent_sec),
        "evidence": str(latest),
    }


def evaluate_nightly_action(*, action_id: str, preferred_window_start_iso: str, required_services: list[str] | None = None) -> ScheduleDecision:
    required_services = required_services or ["axi-bot", "omi-bot"]
    active_ctx = _detect_active_long_run()
    original_time = preferred_window_start_iso
    proposed = preferred_window_start_iso
    decision = "RUN_NOW"
    reason = "No blocking conflict detected."
    ctype = "NONE"
    qpos = 0

    now = datetime.now(timezone.utc)
    dubai_now = now.astimezone(DUBAI)
    in_night_window = (dubai_now.hour > 22 or dubai_now.hour < 6 or (dubai_now.hour == 22 and dubai_now.minute >= 30))

    if active_ctx.get("active"):
        decision = "QUEUE_AFTER_ACTIVE_RUN"
        ctype = "ACTIVE_LONG_RUNNING_CERTIFICATION_CONFLICT"
        reason = "Active long-running certification detected; queue action after active run."
        proposed = (now + timedelta(hours=2)).isoformat()
        qpos = 1
    elif not in_night_window:
        decision = "RESCHEDULE_TO_SAFE_WINDOW"
        ctype = "RESOURCE_WINDOW_CONFLICT"
        reason = "Current time outside preferred night window Asia/Dubai."
        next_night = dubai_now.replace(hour=22, minute=30, second=0, microsecond=0)
        if dubai_now >= next_night:
            next_night += timedelta(days=1)
        proposed = next_night.astimezone(timezone.utc).isoformat()
    else:
        decision = "RUN_LIGHTWEIGHT_ONLY"
        ctype = "NIGHT_SCHEDULER_POLICY_CONFLICT"
        reason = "Night window active; run lightweight smoke with service lifecycle guard."

    return ScheduleDecision(
        action_id=action_id,
        decision=decision,
        reason=reason,
        conflict_type=ctype,
        original_time=original_time,
        proposed_time=proposed,
        queue_position=qpos,
        active_run_context={
            **active_ctx,
            "required_services": required_services,
            "service_guard_mode": "do_not_stop_required_during_cert",
        },
    )
