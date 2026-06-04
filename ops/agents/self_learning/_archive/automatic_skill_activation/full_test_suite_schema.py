from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class FullTestSuiteResult:
    test_suite_id: str
    source_skill_pack_id: str
    source_candidate_skill_id: str
    sandbox_plan_id: str
    execution_id: str
    certification_candidate_id: str
    tests_run: int
    tests_passed: int
    tests_warned: int
    tests_failed: int
    required_tests: list[str] = field(default_factory=list)
    missing_tests: list[str] = field(default_factory=list)
    safety_tests_passed: bool = False
    scope_tests_passed: bool = False
    rollback_tests_passed: bool = False
    forbidden_action_tests_passed: bool = False
    evidence_tests_passed: bool = False
    result_status: str = "FULL_TEST_FAIL"
    blocking_reasons: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
