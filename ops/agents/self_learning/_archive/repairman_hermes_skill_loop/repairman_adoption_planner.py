from __future__ import annotations

import datetime as dt


def build_adoption_plan(adapted: dict) -> dict:
    return {
        "adoption_plan_id": f"adopt_{adapted['adapted_skill_id']}",
        "target_agent_id": adapted["target_agent_id"],
        "source_hermes_skill_candidate_id": adapted["source_hermes_skill_candidate_id"],
        "source_hermes_skill_package_id": adapted["source_hermes_skill_package_id"],
        "source_hermes_test_report_id": adapted["source_hermes_test_report_id"],
        "adapted_skill_id": adapted["adapted_skill_id"],
        "repairman_model_slot": 32,
        "repairman_model_expected": "qwen3:32b-q8_0",
        "adoption_mode": "REPAIRMAN_OWNED_AFTER_ADOPTION",
        "approved_scope_id": "scope_repairman_default",
        "required_scope": "READ_ONLY_ANALYSIS",
        "tests_to_run": ["lineage", "scope", "forbidden_action", "slot32_compat"],
        "sandbox_fixtures": ["fixture_repairman_case"],
        "expected_behavior": "controlled scope-only skill use",
        "forbidden_behavior": "permission expansion",
        "rollback_plan": "disable binding and active registry entry",
        "approval_required": False,
        "activation_after_pass_allowed": True,
        "evidence_refs": adapted.get("evidence_refs", []),
        "status": "READY_FOR_ADOPTION_TESTS",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
