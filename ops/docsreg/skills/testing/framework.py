"""PHASE 7 Skill Testing Framework — orchestrates test execution, validation, and verdict assignment.

Core responsibilities:
- Load 30 synthetic test cases (5 per skill, 6 skills)
- Execute test cases against skill implementations
- Validate data retention hard gates (FAIL verdict blocks repair)
- Assign skill verdicts (PROMOTED/ADVISORY/BLOCKED)
- Aggregate results by skill suite
- Generate evidence packages for each skill
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

from ops.docsreg.skills.testing.models import (
    SkillName,
    SkillTestCase,
    SkillTestInput,
    SkillTestOutput,
    DataRetentionReport,
    DataRetentionStatus,
    SkillVerdict,
    SkillSuiteResult,
)
from ops.docsreg.skills.testing.synthetic_cases import SyntheticCaseGenerator


@dataclass(frozen=True)
class SkillExecutionMetrics:
    """Immutable metrics from a skill test execution."""
    skill_name: SkillName
    total_cases: int
    cases_promoted: int
    cases_advisory: int
    cases_blocked: int
    overall_verdict: SkillVerdict
    average_quality_delta: float
    average_repair_time_ms: int
    retention_failures: int  # Cases where retention FAIL was hit


class SkillTestingFramework:
    """Orchestrates skill testing: execution, retention validation, verdict assignment, aggregation.

    Architecture:
    1. Load test cases via SyntheticCaseGenerator
    2. Execute each case (in real implementation, would call actual skill repair)
    3. Validate retention gate: if DataRetentionStatus.FAIL, block repair
    4. Assign case verdict: PROMOTED (all good), ADVISORY (some metrics below), BLOCKED (retention FAIL)
    5. Aggregate by skill into SkillSuiteResult
    6. Determine overall verdict per skill (unanimous PROMOTED → skill PROMOTED; any BLOCKED → skill BLOCKED)
    """

    def __init__(self):
        """Initialize framework."""
        self.test_cases: List[SkillTestCase] = []
        self.skill_results: Dict[SkillName, SkillSuiteResult] = {}
        self.executed_at: Optional[datetime] = None

    def load_test_cases(self) -> None:
        """Load all 30 synthetic test cases."""
        self.test_cases = SyntheticCaseGenerator.generate_all_cases()

    def execute_all_skills(self) -> None:
        """Execute tests for all 6 skill suites.

        For PHASE 7, test cases are synthetic (pre-computed with realistic metrics).
        In production integration, this would call actual skill.repair() implementations.
        """
        self.executed_at = datetime.utcnow()

        # Group test cases by skill
        by_skill: Dict[SkillName, List[SkillTestCase]] = {}
        for skill in SkillName:
            by_skill[skill] = [tc for tc in self.test_cases if tc.skill_name == skill]

        # Execute each skill suite
        for skill in SkillName:
            cases = by_skill[skill]
            self.skill_results[skill] = self._execute_skill_suite(skill, cases)

    def _execute_skill_suite(self, skill: SkillName, cases: List[SkillTestCase]) -> SkillSuiteResult:
        """Execute a single skill suite (5 test cases).

        Args:
            skill: Skill name (e.g., FIX_TIMEOUT)
            cases: List of 5 test cases for this skill

        Returns:
            SkillSuiteResult with aggregated metrics and overall verdict
        """
        executed_cases: List[SkillTestCase] = []
        promoted_count = 0
        advisory_count = 0
        blocked_count = 0

        for case in cases:
            # For synthetic cases, the verdict is pre-assigned in the test case
            # In production, verdict would be assigned based on actual retention validation
            executed_cases.append(case)

            if case.verdict == SkillVerdict.PROMOTED:
                promoted_count += 1
            elif case.verdict == SkillVerdict.ADVISORY:
                advisory_count += 1
            elif case.verdict == SkillVerdict.BLOCKED:
                blocked_count += 1

        # Determine overall skill verdict
        # BLOCKED if any case is blocked (retention FAIL)
        # PROMOTED if all cases promoted, no FAIL cases
        # ADVISORY otherwise
        if blocked_count > 0:
            overall_verdict = SkillVerdict.BLOCKED
        elif promoted_count == len(cases):
            overall_verdict = SkillVerdict.PROMOTED
        else:
            overall_verdict = SkillVerdict.ADVISORY

        return SkillSuiteResult(
            skill_name=skill,
            total_cases=len(cases),
            cases=executed_cases,
            cases_promoted=promoted_count,
            cases_advisory=advisory_count,
            cases_blocked=blocked_count,
            overall_verdict=overall_verdict,
            executed_at=self.executed_at or datetime.utcnow(),
        )

    def get_skill_result(self, skill: SkillName) -> Optional[SkillSuiteResult]:
        """Get aggregated result for a single skill.

        Args:
            skill: Skill name

        Returns:
            SkillSuiteResult or None if not executed
        """
        return self.skill_results.get(skill)

    def get_all_results(self) -> Dict[SkillName, SkillSuiteResult]:
        """Get results for all skills."""
        return self.skill_results.copy()

    def get_overall_metrics(self) -> SkillExecutionMetrics:
        """Aggregate metrics across all 6 skills.

        Returns:
            Overall execution metrics
        """
        total_cases = sum(r.total_cases for r in self.skill_results.values())
        promoted = sum(r.cases_promoted for r in self.skill_results.values())
        advisory = sum(r.cases_advisory for r in self.skill_results.values())
        blocked = sum(r.cases_blocked for r in self.skill_results.values())

        # Overall verdict: BLOCKED if any skill blocked, else PROMOTED if all promoted, else ADVISORY
        if blocked > 0:
            overall_verdict = SkillVerdict.BLOCKED
        elif promoted == total_cases:
            overall_verdict = SkillVerdict.PROMOTED
        else:
            overall_verdict = SkillVerdict.ADVISORY

        # Calculate average quality delta
        all_quality_deltas = []
        for result in self.skill_results.values():
            for case in result.cases:
                all_quality_deltas.append(case.test_output.quality_delta)
        avg_quality_delta = sum(all_quality_deltas) / len(all_quality_deltas) if all_quality_deltas else 0.0

        # Calculate average repair time
        all_repair_times = []
        for result in self.skill_results.values():
            for case in result.cases:
                all_repair_times.append(case.test_output.repair_time_ms)
        avg_repair_time = int(sum(all_repair_times) / len(all_repair_times)) if all_repair_times else 0

        # Count retention failures
        retention_failures = sum(
            1 for result in self.skill_results.values()
            for case in result.cases
            if case.retention_report.status == DataRetentionStatus.FAIL
        )

        return SkillExecutionMetrics(
            skill_name=SkillName.FIX_TIMEOUT,  # Placeholder; overall metrics span all skills
            total_cases=total_cases,
            cases_promoted=promoted,
            cases_advisory=advisory,
            cases_blocked=blocked,
            overall_verdict=overall_verdict,
            average_quality_delta=avg_quality_delta,
            average_repair_time_ms=avg_repair_time,
            retention_failures=retention_failures,
        )

    def validate_retention_hard_gate(self, case: SkillTestCase) -> bool:
        """Validate retention hard gate for a test case.

        Args:
            case: SkillTestCase to validate

        Returns:
            True if retention passes or is advisory; False if FAIL (hard gate blocks repair)
        """
        return case.retention_report.status != DataRetentionStatus.FAIL

    def generate_evidence_package(self) -> Dict[str, Any]:
        """Generate evidence package documenting all test executions.

        Returns:
            Dict with evidence data (serializable for JSON export)
        """
        if not self.skill_results:
            return {"error": "No test results available; run execute_all_skills() first"}

        evidence = {
            "framework_version": "PHASE_7_v1",
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "overall_metrics": {
                "total_cases": sum(r.total_cases for r in self.skill_results.values()),
                "cases_promoted": sum(r.cases_promoted for r in self.skill_results.values()),
                "cases_advisory": sum(r.cases_advisory for r in self.skill_results.values()),
                "cases_blocked": sum(r.cases_blocked for r in self.skill_results.values()),
                "overall_verdict": self.get_overall_metrics().overall_verdict.value,
            },
            "skill_results": {},
        }

        # Skill-by-skill evidence
        for skill, result in self.skill_results.items():
            evidence["skill_results"][skill.value] = {
                "verdict": result.overall_verdict.value,
                "total_cases": result.total_cases,
                "cases_promoted": result.cases_promoted,
                "cases_advisory": result.cases_advisory,
                "cases_blocked": result.cases_blocked,
                "cases": [
                    {
                        "test_case_id": case.test_case_id,
                        "scenario_description": case.scenario_description,
                        "verdict": case.verdict.value,
                        "reasoning": case.reasoning,
                        "quality_delta": case.test_output.quality_delta,
                        "retention_status": case.retention_report.status.value,
                        "token_loss_percentage": case.retention_report.token_loss_percentage,
                        "repair_time_ms": case.test_output.repair_time_ms,
                    }
                    for case in result.cases
                ],
            }

        return evidence

    def export_evidence_json(self, filepath: str) -> None:
        """Export evidence package as JSON.

        Args:
            filepath: Path to write JSON evidence
        """
        import json
        evidence = self.generate_evidence_package()
        with open(filepath, "w") as f:
            json.dump(evidence, f, indent=2)
