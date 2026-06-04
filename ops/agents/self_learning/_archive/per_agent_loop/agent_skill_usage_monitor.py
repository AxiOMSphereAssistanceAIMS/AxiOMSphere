from __future__ import annotations

from datetime import datetime, timezone


def build_skill_usage_monitors(profiles: list[dict]) -> list[dict]:
    ts = datetime.now(timezone.utc).isoformat()
    out = []
    for p in profiles:
        event = {
            "event_id": f"USE-{p['agent_id']}-001",
            "active_skill_id": f"ACTIVE-{p['agent_id']}-001",
            "result": "IMPROVEMENT_OBSERVED",
            "inside_approved_scope": True,
            "evidence_ref": f"{p['local_evidence_store']}/usage_001.json",
        }
        out.append({
            "agent_id": p["agent_id"],
            "active_skills_observed": [event["active_skill_id"]],
            "usage_events": [event],
            "evidence_refs": [event["evidence_ref"]],
            "improvement_candidates": [event["active_skill_id"]],
            "rollback_candidates": [],
            "created_at": ts,
        })
    return out
