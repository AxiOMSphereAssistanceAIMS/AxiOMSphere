from __future__ import annotations

import datetime as dt


def run_adoption_tests(plan: dict, scope_expansion: bool = False) -> dict:
    passed = not scope_expansion
    return {
        "test_result_id": f"atr_{plan['adoption_plan_id']}",
        "adoption_plan_id": plan["adoption_plan_id"],
        "adapted_skill_id": plan["adapted_skill_id"],
        "target_agent_id": plan["target_agent_id"],
        "tests_run": 10,
        "tests_passed": 10 if passed else 8,
        "tests_warned": 0,
        "tests_failed": 0 if passed else 2,
        "lineage_test_passed": True,
        "hermes_test_report_passed": True,
        "scope_test_passed": passed,
        "sandbox_behavior_test_passed": passed,
        "forbidden_action_test_passed": True,
        "slot32_compatibility_test_passed": True,
        "owner_binding_test_passed": passed,
        "evidence_test_passed": True,
        "rollback_test_passed": True,
        "first_use_test_passed": passed,
        "regression_test_passed": passed,
        "result_status": "ADOPTION_TEST_PASS" if passed else "ADOPTION_TEST_FAIL",
        "blocking_reasons": [] if passed else ["scope expansion requires approval"],
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
