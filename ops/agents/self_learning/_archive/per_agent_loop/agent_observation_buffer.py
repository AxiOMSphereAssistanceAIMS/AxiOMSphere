from __future__ import annotations

from datetime import datetime, timezone


def build_observation_buffers(profiles: list[dict]) -> list[dict]:
    ts = datetime.now(timezone.utc).isoformat()
    out = []
    for p in profiles:
        obs = {
            "observation_id": f"OBS-{p['agent_id']}-001",
            "event_type": "REPEATED_TASK",
            "task_summary": "Repeated task pattern detected",
            "task_domain": p["owned_skill_domains"][0],
            "repeated_count": 2,
            "related_skill_id": "",
            "skill_gap_detected": True,
            "evidence_refs": [f"{p['local_evidence_store']}/obs_001.json"],
            "safe_to_convert_to_skill_request": True,
        }
        out.append({
            "agent_id": p["agent_id"],
            "observations": [obs],
            "repeated_task_candidates": [obs["observation_id"]],
            "evidence_refs": obs["evidence_refs"],
            "created_at": ts,
        })
    return out
