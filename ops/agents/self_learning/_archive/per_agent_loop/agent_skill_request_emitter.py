from __future__ import annotations

from datetime import datetime, timezone


def build_skill_request_outboxes(profiles: list[dict], buffers: list[dict]) -> list[dict]:
    ts = datetime.now(timezone.utc).isoformat()
    by_agent = {b["agent_id"]: b for b in buffers}
    out = []
    for p in profiles:
        b = by_agent[p["agent_id"]]
        req = {
            "request_id": f"REQ-{p['agent_id']}-001",
            "source_agent_id": p["agent_id"],
            "proposed_owner_agent_id": p["agent_id"],
            "requested_skill_name": f"{p['agent_id']}_missing_capability_skill",
            "requested_skill_domain": p["owned_skill_domains"][0],
            "observed_count": 2,
            "repeated_task_evidence_refs": b["evidence_refs"],
            "approval_required": True,
            "approval_status": "PENDING_APPROVAL",
            "downstream_status": "WAITING_FOR_APPROVAL",
            "compatibility": "PHASE20_SKILL_REQUEST_COMPATIBLE",
        }
        out.append({
            "agent_id": p["agent_id"],
            "outgoing_skill_requests": [req],
            "pending_approval_count": 1,
            "blocked_count": 0,
            "created_at": ts,
        })
    return out
