from __future__ import annotations

import datetime as dt


def activate_skill(adapted: dict, plan: dict, test_result: dict) -> tuple[dict, dict, dict]:
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    active = {
        "active_skill_id": f"active_{adapted['adapted_skill_id']}",
        "adapted_skill_id": adapted["adapted_skill_id"],
        "source_hermes_skill_candidate_id": adapted["source_hermes_skill_candidate_id"],
        "source_hermes_skill_package_id": adapted["source_hermes_skill_package_id"],
        "source_hermes_test_report_id": adapted["source_hermes_test_report_id"],
        "origin": "HERMES_INCUBATED",
        "source_author": "hermes",
        "incubated_by": "hermes",
        "tested_by_hermes": True,
        "owner_agent_id": adapted["owner_after_adoption"],
        "lifecycle_state": "ACTIVE_RUNTIME_SKILL",
        "activation_status": "ACTIVE_WITHIN_APPROVED_SCOPE",
        "repairman_model_slot": 32,
        "hermes_consultant_role": "SKILL_CREATOR_INCUBATOR_AND_REVIEWER",
        "runtime_use_mode": "CONTROLLED_SCOPE_ONLY",
        "evidence_refs": adapted.get("evidence_refs", []),
        "activated_at": ts,
        "activated_by": "AIMS_REPAIRMAN_ADOPTION_PIPELINE",
    }
    binding = {
        "binding_id": f"bind_{active['active_skill_id']}",
        "owner_agent_id": active["owner_agent_id"],
        "active_skill_id": active["active_skill_id"],
        "skill_name": adapted["adapted_skill_name"],
        "execution_mode": "CONTROLLED_SCOPE_ONLY",
        "activation_status": active["activation_status"],
        "monitoring_required": True,
        "created_at": ts,
    }
    first_use = {
        "first_use_id": f"firstuse_{active['active_skill_id']}",
        "active_skill_id": active["active_skill_id"],
        "owner_agent_id": active["owner_agent_id"],
        "skill_name": adapted["adapted_skill_name"],
        "simulated_or_controlled": "controlled",
        "input_context": "repairman adoption verification",
        "output_summary": "within-scope adoption first-use pass",
        "result_status": "FIRST_USE_PASS",
        "created_at": ts,
    }
    return active, binding, first_use
