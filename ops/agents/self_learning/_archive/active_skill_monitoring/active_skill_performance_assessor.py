from __future__ import annotations

import datetime as dt


def assess_skill(active_entry: dict, events: list[dict]) -> dict:
    success = sum(1 for e in events if e.get("success_signal"))
    warn = sum(1 for e in events if e.get("improvement_signal") and not e.get("failure_signal"))
    fail = sum(1 for e in events if e.get("failure_signal"))
    scope_viol = sum(1 for e in events if not e.get("inside_approved_scope", True))
    unsafe = sum(1 for e in events if e.get("unsafe_action_detected"))
    rollback = sum(1 for e in events if e.get("rollback_signal"))

    effectiveness = 1.0 if success else 0.5
    reliability = 1.0 if fail == 0 else 0.4
    safety = 1.0 if unsafe == 0 and scope_viol == 0 else 0.3

    if rollback > 0:
        status = "ROLLBACK_RECOMMENDED"
    elif unsafe > 0 or scope_viol > 0:
        status = "NEW_APPROVAL_REQUIRED"
    elif fail > 0:
        status = "NEEDS_IMPROVEMENT_WITHIN_SCOPE"
    elif warn > 0:
        status = "HEALTHY_WITH_IMPROVEMENT_OPPORTUNITY"
    else:
        status = "HEALTHY"

    return {
        "assessment_id": f"ASM-{active_entry['active_skill_id']}",
        "active_skill_id": active_entry["active_skill_id"],
        "owner_agent_id": active_entry["owner_agent_id"],
        "skill_name": active_entry["skill_name"],
        "events_evaluated": len(events),
        "success_count": success,
        "warning_count": warn,
        "failure_count": fail,
        "scope_violation_count": scope_viol,
        "unsafe_action_count": unsafe,
        "rollback_trigger_count": rollback,
        "evidence_quality": "GOOD" if len(events) >= 1 else "LOW",
        "effectiveness_score": effectiveness,
        "reliability_score": reliability,
        "safety_score": safety,
        "improvement_needed": status in {"HEALTHY_WITH_IMPROVEMENT_OPPORTUNITY", "NEEDS_IMPROVEMENT_WITHIN_SCOPE"},
        "rollback_recommended": status == "ROLLBACK_RECOMMENDED",
        "new_approval_required": status == "NEW_APPROVAL_REQUIRED",
        "assessment_status": status,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
