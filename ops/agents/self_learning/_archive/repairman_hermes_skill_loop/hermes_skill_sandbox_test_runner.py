from __future__ import annotations

import datetime as dt


def run_hermes_sandbox_test(pkg: dict, fail_fixture: bool = False) -> dict:
    if fail_fixture:
        status = "HERMES_SANDBOX_FAIL"
        tests_passed = 5
        tests_failed = 2
    else:
        status = "HERMES_SANDBOX_PASS"
        tests_passed = 8
        tests_failed = 0
    return {
        "hermes_test_report_id": f"htr_{pkg['hermes_skill_package_id']}",
        "hermes_skill_package_id": pkg["hermes_skill_package_id"],
        "source_repair_case_id": pkg["source_repair_case_id"],
        "tests_run": 8,
        "tests_passed": tests_passed,
        "tests_warned": 0 if not fail_fixture else 1,
        "tests_failed": tests_failed,
        "fixture_tests_passed": not fail_fixture,
        "expected_output_tests_passed": not fail_fixture,
        "refusal_rule_tests_passed": True,
        "forbidden_action_tests_passed": True,
        "safety_rule_tests_passed": True,
        "evidence_tests_passed": True,
        "result_status": status,
        "blocking_reasons": [] if not fail_fixture else ["fixture mismatch"],
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
