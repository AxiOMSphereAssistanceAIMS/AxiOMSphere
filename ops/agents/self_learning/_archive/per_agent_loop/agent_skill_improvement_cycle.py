from __future__ import annotations


def build_improvement_cycles(monitors: list[dict]) -> list[dict]:
    out = []
    for m in monitors:
        out.append({
            "agent_id": m["agent_id"],
            "active_skill_id": m["active_skills_observed"][0],
            "current_version": "1.0.0",
            "proposed_improvement": "trigger_refinement",
            "inside_approved_scope": True,
            "new_approval_required": False,
            "evidence_refs": m["evidence_refs"],
            "next_action": "RUN_WITHIN_SCOPE_IMPROVEMENT_PIPELINE",
            "compatibility": "PHASE27_WITHIN_SCOPE_COMPATIBLE",
        })
    return out
