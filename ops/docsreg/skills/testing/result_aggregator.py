"""PHASE 7 Result Aggregator — analyzes test outcomes across all 6 skills.

Responsibilities:
- Aggregate metrics by skill and across all skills
- Classify skills by verdict (PROMOTED, ADVISORY, BLOCKED)
- Detect patterns (e.g., which skills have retention failures)
- Calculate pass/fail rates
- Generate summary reports
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple
from enum import Enum

from ops.docsreg.skills.testing.models import (
    SkillName,
    SkillVerdict,
    SkillSuiteResult,
    DataRetentionStatus,
)


class SkillClassification(Enum):
    """Skill classification by verdict."""
    PROMOTED = "PROMOTED"
    ADVISORY = "ADVISORY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AggregationSummary:
    """Immutable aggregation of test results across all skills."""
    total_skills: int
    promoted_skills: int
    advisory_skills: int
    blocked_skills: int
    total_test_cases: int
    promoted_cases: int
    advisory_cases: int
    blocked_cases: int
    retention_failure_count: int
    average_quality_improvement: float
    average_repair_time_ms: int
    recommendation: str  # Summary recommendation


class ResultAggregator:
    """Aggregates and analyzes test results across all 6 skill suites."""

    def __init__(self, skill_results: Dict[SkillName, SkillSuiteResult]):
        """Initialize with completed test results.

        Args:
            skill_results: Dict mapping SkillName to SkillSuiteResult
        """
        self.skill_results = skill_results

    def get_summary(self) -> AggregationSummary:
        """Get high-level aggregation summary.

        Returns:
            AggregationSummary with metrics and recommendation
        """
        promoted_skills = sum(
            1 for r in self.skill_results.values()
            if r.overall_verdict == SkillVerdict.PROMOTED
        )
        advisory_skills = sum(
            1 for r in self.skill_results.values()
            if r.overall_verdict == SkillVerdict.ADVISORY
        )
        blocked_skills = sum(
            1 for r in self.skill_results.values()
            if r.overall_verdict == SkillVerdict.BLOCKED
        )

        total_test_cases = sum(r.total_cases for r in self.skill_results.values())
        promoted_cases = sum(r.cases_promoted for r in self.skill_results.values())
        advisory_cases = sum(r.cases_advisory for r in self.skill_results.values())
        blocked_cases = sum(r.cases_blocked for r in self.skill_results.values())

        retention_failures = sum(
            1 for r in self.skill_results.values()
            for case in r.cases
            if case.retention_report.status == DataRetentionStatus.FAIL
        )

        # Calculate average quality improvement
        all_quality_deltas = []
        for result in self.skill_results.values():
            for case in result.cases:
                all_quality_deltas.append(case.test_output.quality_delta)
        avg_quality_improvement = sum(all_quality_deltas) / len(all_quality_deltas) if all_quality_deltas else 0.0

        # Calculate average repair time
        all_repair_times = []
        for result in self.skill_results.values():
            for case in result.cases:
                all_repair_times.append(case.test_output.repair_time_ms)
        avg_repair_time_ms = int(sum(all_repair_times) / len(all_repair_times)) if all_repair_times else 0

        # Determine recommendation
        if blocked_skills == 0 and promoted_skills == 6:
            recommendation = "ALL_SKILLS_PROMOTED — Ready for deployment"
        elif blocked_skills == 0 and advisory_skills > 0:
            recommendation = f"{advisory_skills} skills at ADVISORY threshold — Investigate metrics below target"
        elif blocked_skills > 0:
            recommendation = f"{blocked_skills} skills BLOCKED by data retention failures — Fix required before deployment"
        else:
            recommendation = "Unknown state"

        return AggregationSummary(
            total_skills=len(self.skill_results),
            promoted_skills=promoted_skills,
            advisory_skills=advisory_skills,
            blocked_skills=blocked_skills,
            total_test_cases=total_test_cases,
            promoted_cases=promoted_cases,
            advisory_cases=advisory_cases,
            blocked_cases=blocked_cases,
            retention_failure_count=retention_failures,
            average_quality_improvement=avg_quality_improvement,
            average_repair_time_ms=avg_repair_time_ms,
            recommendation=recommendation,
        )

    def classify_skills(self) -> Dict[SkillClassification, List[SkillName]]:
        """Classify skills by verdict.

        Returns:
            Dict mapping SkillClassification to list of skills
        """
        classified: Dict[SkillClassification, List[SkillName]] = {
            SkillClassification.PROMOTED: [],
            SkillClassification.ADVISORY: [],
            SkillClassification.BLOCKED: [],
        }

        for skill, result in self.skill_results.items():
            if result.overall_verdict == SkillVerdict.PROMOTED:
                classified[SkillClassification.PROMOTED].append(skill)
            elif result.overall_verdict == SkillVerdict.ADVISORY:
                classified[SkillClassification.ADVISORY].append(skill)
            elif result.overall_verdict == SkillVerdict.BLOCKED:
                classified[SkillClassification.BLOCKED].append(skill)

        return classified

    def get_skills_by_verdict(self, verdict: SkillVerdict) -> List[SkillName]:
        """Get list of skills with a specific verdict.

        Args:
            verdict: SkillVerdict to filter by

        Returns:
            List of SkillName values matching verdict
        """
        return [
            skill for skill, result in self.skill_results.items()
            if result.overall_verdict == verdict
        ]

    def find_retention_failures(self) -> List[Tuple[SkillName, str, float]]:
        """Find all test cases with retention FAIL verdict.

        Returns:
            List of (skill_name, test_case_id, token_loss_percentage) tuples
        """
        failures = []
        for skill, result in self.skill_results.items():
            for case in result.cases:
                if case.retention_report.status == DataRetentionStatus.FAIL:
                    failures.append((
                        skill,
                        case.test_case_id,
                        case.retention_report.token_loss_percentage,
                    ))
        return failures

    def find_advisory_cases(self) -> List[Tuple[SkillName, str, float]]:
        """Find all test cases at ADVISORY threshold (1.5%-2.0% loss).

        Returns:
            List of (skill_name, test_case_id, token_loss_percentage) tuples
        """
        advisory = []
        for skill, result in self.skill_results.items():
            for case in result.cases:
                if case.retention_report.status == DataRetentionStatus.ADVISORY:
                    advisory.append((
                        skill,
                        case.test_case_id,
                        case.retention_report.token_loss_percentage,
                    ))
        return advisory

    def get_slowest_repairs(self, limit: int = 5) -> List[Tuple[SkillName, str, int]]:
        """Get slowest repairs by execution time.

        Args:
            limit: Maximum number of results

        Returns:
            List of (skill_name, test_case_id, repair_time_ms) sorted by time descending
        """
        repairs = []
        for skill, result in self.skill_results.items():
            for case in result.cases:
                repairs.append((
                    skill,
                    case.test_case_id,
                    case.test_output.repair_time_ms,
                ))
        repairs.sort(key=lambda x: x[2], reverse=True)
        return repairs[:limit]

    def get_best_quality_improvements(self, limit: int = 5) -> List[Tuple[SkillName, str, float]]:
        """Get best quality improvements.

        Args:
            limit: Maximum number of results

        Returns:
            List of (skill_name, test_case_id, quality_delta) sorted by delta descending
        """
        improvements = []
        for skill, result in self.skill_results.items():
            for case in result.cases:
                improvements.append((
                    skill,
                    case.test_case_id,
                    case.test_output.quality_delta,
                ))
        improvements.sort(key=lambda x: x[2], reverse=True)
        return improvements[:limit]

    def generate_report(self) -> str:
        """Generate human-readable test report.

        Returns:
            Formatted report string
        """
        summary = self.get_summary()
        classifications = self.classify_skills()

        report = []
        report.append("=" * 80)
        report.append("PHASE 7 SKILL TESTING FRAMEWORK — TEST REPORT")
        report.append("=" * 80)
        report.append("")

        # Summary section
        report.append("SUMMARY")
        report.append("-" * 80)
        report.append(f"Total Skills: {summary.total_skills}")
        report.append(f"  PROMOTED: {summary.promoted_skills}")
        report.append(f"  ADVISORY: {summary.advisory_skills}")
        report.append(f"  BLOCKED: {summary.blocked_skills}")
        report.append("")
        report.append(f"Total Test Cases: {summary.total_test_cases}")
        report.append(f"  PROMOTED: {summary.promoted_cases}")
        report.append(f"  ADVISORY: {summary.advisory_cases}")
        report.append(f"  BLOCKED: {summary.blocked_cases}")
        report.append("")
        report.append(f"Retention Failures: {summary.retention_failure_count}")
        report.append(f"Average Quality Improvement: {summary.average_quality_improvement:.4f}")
        report.append(f"Average Repair Time: {summary.average_repair_time_ms} ms")
        report.append("")
        report.append(f"RECOMMENDATION: {summary.recommendation}")
        report.append("")

        # Skill classifications
        report.append("SKILL VERDICTS")
        report.append("-" * 80)
        if classifications[SkillClassification.PROMOTED]:
            report.append(f"PROMOTED: {', '.join(s.value for s in classifications[SkillClassification.PROMOTED])}")
        if classifications[SkillClassification.ADVISORY]:
            report.append(f"ADVISORY: {', '.join(s.value for s in classifications[SkillClassification.ADVISORY])}")
        if classifications[SkillClassification.BLOCKED]:
            report.append(f"BLOCKED: {', '.join(s.value for s in classifications[SkillClassification.BLOCKED])}")
        report.append("")

        # Retention failures
        failures = self.find_retention_failures()
        if failures:
            report.append("RETENTION FAILURES (Data Loss > 2.0%)")
            report.append("-" * 80)
            for skill, case_id, loss_pct in failures:
                report.append(f"  {skill.value:30} {case_id:20} {loss_pct:.2f}%")
            report.append("")

        # Advisory cases
        advisory = self.find_advisory_cases()
        if advisory:
            report.append("ADVISORY CASES (Data Loss 1.5%-2.0%)")
            report.append("-" * 80)
            for skill, case_id, loss_pct in advisory:
                report.append(f"  {skill.value:30} {case_id:20} {loss_pct:.2f}%")
            report.append("")

        # Slowest repairs
        slowest = self.get_slowest_repairs()
        if slowest:
            report.append("SLOWEST REPAIRS (Top 5)")
            report.append("-" * 80)
            for skill, case_id, time_ms in slowest:
                report.append(f"  {skill.value:30} {case_id:20} {time_ms} ms")
            report.append("")

        # Best quality improvements
        best = self.get_best_quality_improvements()
        if best:
            report.append("BEST QUALITY IMPROVEMENTS (Top 5)")
            report.append("-" * 80)
            for skill, case_id, delta in best:
                report.append(f"  {skill.value:30} {case_id:20} +{delta:.4f}")
            report.append("")

        report.append("=" * 80)
        return "\n".join(report)
