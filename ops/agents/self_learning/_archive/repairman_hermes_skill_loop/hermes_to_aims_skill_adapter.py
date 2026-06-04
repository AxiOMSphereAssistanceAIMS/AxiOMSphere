from __future__ import annotations

import datetime as dt


def adapt_hermes_candidate(c: dict) -> dict:
    return {
        "adapted_skill_id": f"adapted_{c['hermes_skill_candidate_id']}",
        "source_hermes_skill_candidate_id": c["hermes_skill_candidate_id"],
        "source_hermes_skill_package_id": c["source_hermes_skill_package_id"],
        "source_hermes_test_report_id": c["source_hermes_test_report_id"],
        "source_repair_case_id": c["source_repair_case_id"],
        "target_agent_id": "repairman",
        "owner_after_adoption": "repairman",
        "origin": "HERMES_INCUBATED",
        "adapted_skill_name": c["suggested_skill_name"],
        "adapted_skill_domain": c["suggested_skill_domain"],
        "adapted_description": c.get("intended_use", ""),
        "approved_scope_required": False,
        "proposed_permission_level": "READ_ONLY_ANALYSIS",
        "proposed_risk_class": "LOW",
        "allowed_actions": c.get("proposed_actions", []),
        "forbidden_actions": c.get("forbidden_actions", []),
        "required_inputs": c.get("required_inputs", []),
        "expected_outputs": c.get("expected_outputs", []),
        "required_tests": c.get("required_tests", []),
        "required_gates": ["Poli", "Argus", "QA"],
        "repairman_slot32_compatibility": True,
        "hermes_consultant_role": "SKILL_CREATOR_INCUBATOR_AND_REVIEWER",
        "adoption_status": "READY_FOR_ADOPTION_PLAN",
        "evidence_refs": c.get("evidence_refs", []),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
