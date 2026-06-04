from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any


CONFLICT_TYPES = {
    "ACTIVE_LONG_RUNNING_CERTIFICATION_CONFLICT",
    "NIGHT_SCHEDULER_POLICY_CONFLICT",
    "SERVICE_LIFECYCLE_POLICY_CONFLICT",
    "MODEL_SLOT_CONFLICT",
    "HEAVY_TRAINING_CONFLICT",
    "PROMOTION_GATE_CONFLICT",
    "RESOURCE_WINDOW_CONFLICT",
    "UNKNOWN_CONFLICT",
}

DECISIONS = {
    "RUN_NOW",
    "RUN_LIGHTWEIGHT_ONLY",
    "QUEUE_AFTER_ACTIVE_RUN",
    "RESCHEDULE_TO_SAFE_WINDOW",
    "BLOCK_PENDING_APPROVAL",
    "SKIP_AS_POLICY_EXPECTED",
    "ESCALATE",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScheduleConflictDecision:
    schedule_conflict_id: str
    action_id: str
    conflict_type: str
    active_run_context: dict[str, Any]
    original_time: str
    proposed_time: str
    decision: str
    reason: str
    safety_policy: dict[str, Any]
    evidence: dict[str, Any]
    queue_position: int
    validation_plan: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScheduleConflictResolver:
    def resolve(
        self,
        *,
        action_id: str,
        action_type: str,
        original_time: str,
        active_long_run: bool,
        active_long_run_id: str,
        heavy_action: bool,
        requires_slot120: bool,
        slot32_loaded: bool,
        scheduler_policy_requires_stop: bool,
        required_service_for_cert: bool,
    ) -> ScheduleConflictDecision:
        conflict_type = "UNKNOWN_CONFLICT"
        decision = "ESCALATE"
        reason = "No matching policy rule."
        proposed_time = original_time
        queue_position = 0

        if active_long_run and heavy_action:
            conflict_type = "ACTIVE_LONG_RUNNING_CERTIFICATION_CONFLICT"
            decision = "QUEUE_AFTER_ACTIVE_RUN"
            reason = "Heavy action conflicts with active long-running certification window."
            proposed_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            queue_position = 1
        elif requires_slot120 and slot32_loaded:
            conflict_type = "MODEL_SLOT_CONFLICT"
            decision = "BLOCK_PENDING_APPROVAL"
            reason = "slot120 requires slot32 unload; blocked for safety and approval."
        elif scheduler_policy_requires_stop and required_service_for_cert:
            conflict_type = "SERVICE_LIFECYCLE_POLICY_CONFLICT"
            decision = "RESCHEDULE_TO_SAFE_WINDOW"
            reason = "Night stop policy conflicts with required service for active certification."
            proposed_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        elif action_type == "promotion":
            conflict_type = "PROMOTION_GATE_CONFLICT"
            decision = "BLOCK_PENDING_APPROVAL"
            reason = "Promotion requires approval gate; not allowed during autonomous conflict resolution."
        elif action_type == "heavy_training":
            conflict_type = "HEAVY_TRAINING_CONFLICT"
            decision = "QUEUE_AFTER_ACTIVE_RUN" if active_long_run else "RESCHEDULE_TO_SAFE_WINDOW"
            reason = "Heavy training is not allowed during active certification windows."
            proposed_time = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
            queue_position = 2
        elif scheduler_policy_requires_stop and not required_service_for_cert:
            conflict_type = "NIGHT_SCHEDULER_POLICY_CONFLICT"
            decision = "SKIP_AS_POLICY_EXPECTED"
            reason = "Service downtime is policy-expected and not a certification blocker."
        else:
            conflict_type = "RESOURCE_WINDOW_CONFLICT" if heavy_action else "UNKNOWN_CONFLICT"
            decision = "RUN_LIGHTWEIGHT_ONLY" if heavy_action else "RUN_NOW"
            reason = "Run lightweight path under current safety/resource policy." if heavy_action else "No blocking conflict detected."

        return ScheduleConflictDecision(
            schedule_conflict_id=f"sc_{action_id}_{int(datetime.now(timezone.utc).timestamp())}",
            action_id=action_id,
            conflict_type=conflict_type,
            active_run_context={
                "active_long_run": active_long_run,
                "active_long_run_id": active_long_run_id,
            },
            original_time=original_time,
            proposed_time=proposed_time,
            decision=decision,
            reason=reason,
            safety_policy={
                "no_heavy_training_during_24h_72h": True,
                "no_slot32_slot120_conflict": True,
                "protected_service_restart_requires_approval": True,
            },
            evidence={
                "resolver_time": now_iso(),
                "inputs": {
                    "action_type": action_type,
                    "heavy_action": heavy_action,
                    "requires_slot120": requires_slot120,
                    "slot32_loaded": slot32_loaded,
                    "scheduler_policy_requires_stop": scheduler_policy_requires_stop,
                    "required_service_for_cert": required_service_for_cert,
                },
            },
            queue_position=queue_position,
            validation_plan="Validate decision in next scheduler tick and persist queue transition.",
        )
