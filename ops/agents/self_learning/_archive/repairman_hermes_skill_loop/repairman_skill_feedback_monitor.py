from __future__ import annotations

import datetime as dt


def build_feedback_event(active_skill: dict) -> dict:
    return {
        "event_id": f"fb_{active_skill['active_skill_id']}",
        "active_skill_id": active_skill["active_skill_id"],
        "owner_agent_id": active_skill["owner_agent_id"],
        "event_type": "CONTROLLED_FIRST_USE",
        "inside_approved_scope": True,
        "success_signal": True,
        "improvement_signal": "minor prompt refinement",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
