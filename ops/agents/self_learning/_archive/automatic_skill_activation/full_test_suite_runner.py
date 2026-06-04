from __future__ import annotations

import datetime as dt

from .full_test_suite_schema import FullTestSuiteResult


def run_full_tests(scope: dict, lineage: dict) -> dict:
    required = [
        "lineage_test",
        "scope_test",
        "sandbox_result_test",
        "forbidden_action_test",
        "rollback_test",
        "owner_binding_test",
        "registry_test",
        "first_use_test",
        "safety_counters_test",
        "evidence_test",
    ]

    blocking = []
    passed = 0

    if lineage.get("lineage_ok"):
        passed += 1
    else:
        blocking.append("lineage missing")

    if lineage.get("scope_ok"):
        passed += 1
    else:
        blocking.append("scope verification failed")

    if lineage.get("sandbox_ok"):
        passed += 1
    else:
        blocking.append("sandbox result not PASS/WARN")

    if lineage.get("forbidden_ok"):
        passed += 1
    else:
        blocking.append("forbidden actions test failed")

    if lineage.get("rollback_ok"):
        passed += 1
    else:
        blocking.append("rollback metadata missing")

    if lineage.get("owner_ok"):
        passed += 1
    else:
        blocking.append("owner binding mismatch")

    if lineage.get("registry_ok"):
        passed += 1
    else:
        blocking.append("registry write artifact test failed")

    if lineage.get("first_use_ok"):
        passed += 1
    else:
        blocking.append("first use test failed")

    if lineage.get("safety_counters_ok"):
        passed += 1
    else:
        blocking.append("dangerous counters non-zero")

    if lineage.get("evidence_ok"):
        passed += 1
    else:
        blocking.append("evidence missing")

    failed = len(required) - passed
    status = "FULL_TEST_PASS" if failed == 0 else "FULL_TEST_FAIL"

    obj = FullTestSuiteResult(
        test_suite_id=f"FTS-{lineage['skill_pack_id']}",
        source_skill_pack_id=lineage["skill_pack_id"],
        source_candidate_skill_id=lineage["candidate_skill_id"],
        sandbox_plan_id=lineage["sandbox_plan_id"],
        execution_id=lineage["execution_id"],
        certification_candidate_id=lineage["certification_candidate_id"],
        tests_run=len(required),
        tests_passed=passed,
        tests_warned=0,
        tests_failed=failed,
        required_tests=required,
        missing_tests=[],
        safety_tests_passed=lineage.get("safety_counters_ok", False),
        scope_tests_passed=lineage.get("scope_ok", False),
        rollback_tests_passed=lineage.get("rollback_ok", False),
        forbidden_action_tests_passed=lineage.get("forbidden_ok", False),
        evidence_tests_passed=lineage.get("evidence_ok", False),
        result_status=status,
        blocking_reasons=blocking,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    return obj.to_dict()
