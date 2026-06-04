from __future__ import annotations

from typing import Any


def build_candidate_skill(pack: dict[str, Any]) -> dict[str, Any]:
    cid = f"CSK-{pack['skill_pack_id']}"
    return {
        "candidate_skill_id": cid,
        "source_skill_pack_id": pack["skill_pack_id"],
        "source_request_id": pack["source_request_id"],
        "lifecycle_state": "CANDIDATE_SKILL",
        "owner_agent_id": pack["owner_agent_id"],
        "skill_domain": pack["skill_domain"],
        "skill_name": pack["skill_name"],
        "proposed_trigger": pack.get("trigger_conditions", []),
        "proposed_instructions": pack.get("instructions", []),
        "evidence_refs": pack.get("evidence_refs", []),
        "required_gates": pack.get("safety_gates", []),
        "sandbox_test_plan_stub_id": f"SPS-{cid}",
        "rollback_notes": pack.get("rollback_notes", ""),
        "self_approval_allowed": False,
        "runtime_activation_allowed": False,
        "status": "READY_FOR_SANDBOX_PLAN_GENERATION",
    }
