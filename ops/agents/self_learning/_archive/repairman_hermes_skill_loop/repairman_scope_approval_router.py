from __future__ import annotations

import datetime as dt


def build_scope_approval_request(adapted: dict, reason: str) -> dict:
    return {
        "request_id": f"scope_req_{adapted['adapted_skill_id']}",
        "adapted_skill_id": adapted["adapted_skill_id"],
        "target_agent_id": adapted["target_agent_id"],
        "reason": reason,
        "status": "PENDING_APPROVAL",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
