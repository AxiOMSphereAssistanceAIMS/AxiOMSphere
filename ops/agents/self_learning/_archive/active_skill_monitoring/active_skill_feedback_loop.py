from __future__ import annotations

import datetime as dt


def build_feedback_queue(items: list[dict]) -> dict:
    queued = []
    auto = 0
    manual = 0
    for it in items:
        next_action = it.get("next_action")
        if next_action == "QUEUE_WITHIN_SCOPE_SKILL_IMPROVEMENT":
            processor = "WITHIN_SCOPE_SKILL_IMPROVEMENT_PIPELINE"
            exec_allowed = True
            auto += 1
        elif next_action == "CREATE_NEW_SKILL_REQUEST_OR_SCOPE_EXPANSION_REQUEST":
            processor = "NEW_SKILL_REQUEST_APPROVAL_GATE"
            exec_allowed = False
            manual += 1
        elif next_action == "ROLLBACK_PIPELINE":
            processor = "ROLLBACK_PIPELINE"
            exec_allowed = False
            manual += 1
        else:
            processor = "NO_ACTION_REQUIRED"
            exec_allowed = False

        queued.append(
            {
                "improvement_plan_id": it.get("improvement_plan_id"),
                "active_skill_id": it.get("active_skill_id"),
                "next_processor": processor,
                "execution_allowed": exec_allowed,
                "reason": next_action,
            }
        )

    return {
        "queue_id": f"FQ-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "queued_items": queued,
        "next_processor": "CONTINUE_SELF_LEARNING_FEEDBACK_LOOP",
        "execution_allowed": any(i.get("execution_allowed") for i in queued),
        "reason": "Automatic within-scope improvements continue automatically; scope expansion/rollback require new approval or gate action.",
        "automatic_within_scope_items": auto,
        "manual_approval_items": manual,
    }
