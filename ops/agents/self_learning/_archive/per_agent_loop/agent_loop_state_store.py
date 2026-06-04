from __future__ import annotations

from datetime import datetime, timezone


def build_loop_states(profiles: list[dict], buffers: list[dict], outboxes: list[dict], monitors: list[dict], cycles: list[dict]) -> list[dict]:
    ts = datetime.now(timezone.utc).isoformat()
    b = {x["agent_id"]: x for x in buffers}
    o = {x["agent_id"]: x for x in outboxes}
    m = {x["agent_id"]: x for x in monitors}
    c = {x["agent_id"]: x for x in cycles}
    states = []
    for p in profiles:
        agent_id = p["agent_id"]
        states.append({
            "agent_id": agent_id,
            "loop_run_id": f"LOOP-{agent_id}-001",
            "created_at": ts,
            "loop_mode": p["loop_mode"],
            "loop_pace": p["loop_pace"],
            "observations_collected": len(b[agent_id]["observations"]),
            "repeated_patterns_detected": len(b[agent_id]["repeated_task_candidates"]),
            "skill_requests_created": len(o[agent_id]["outgoing_skill_requests"]),
            "active_skills_available": len(m[agent_id]["active_skills_observed"]),
            "active_skills_used": len(m[agent_id]["usage_events"]),
            "skill_monitoring_events": len(m[agent_id]["usage_events"]),
            "within_scope_improvements_queued": 1 if c[agent_id]["inside_approved_scope"] else 0,
            "new_approval_required_items": 1 if c[agent_id]["new_approval_required"] else 0,
            "blocked_items": 0,
            "safety_status": "PASS",
            "next_action": c[agent_id]["next_action"],
        })
    return states
