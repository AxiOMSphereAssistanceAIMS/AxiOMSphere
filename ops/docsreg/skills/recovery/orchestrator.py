"""PHASE 8 Recovery Orchestrator — end-to-end skill recovery pipeline.

Orchestrates:
1. Analysis of all blocked skills from Phase 7 results
2. Diagnosis of each retention failure
3. Strategy proposal for each blocked case
4. Simulation of each proposal
5. Aggregation into per-skill and overall recovery verdicts
6. Generation of recovery summary with deployment recommendation
"""
from typing import Dict, List

from ops.docsreg.skills.testing.models import (
    SkillName,
    SkillSuiteResult,
    SkillVerdict,
)
from ops.docsreg.skills.recovery.models import (
    RecoveryVerdict,
    RecoveryProposal,
    RecoveryOutcome,
    RetentionDiagnosis,
    SkillRecoveryReport,
    RecoverySummary,
)
from ops.docsreg.skills.recovery.analyzer import RecoveryAnalyzer
from ops.docsreg.skills.recovery.simulator import RecoverySimulator


class RecoveryOrchestrator:
    """End-to-end orchestrator for PHASE 8 skill recovery."""

    def __init__(self, skill_results: Dict[SkillName, SkillSuiteResult]):
        """Initialize with Phase 7 skill results.

        Args:
            skill_results: Dict mapping SkillName to SkillSuiteResult
        """
        self.skill_results = skill_results
        self.analyzer = RecoveryAnalyzer(skill_results)
        self.simulator = RecoverySimulator()
        self._skill_reports: List[SkillRecoveryReport] = []
        self._summary: RecoverySummary = None

    def run(self) -> RecoverySummary:
        """Execute full recovery pipeline.

        Returns:
            RecoverySummary with verdicts and recommendations
        """
        blocked_skills = self.analyzer.get_blocked_skills()

        if not blocked_skills:
            return RecoverySummary(
                total_blocked_skills=0,
                total_blocked_cases=0,
                resolved_count=0,
                partially_resolved_count=0,
                unresolved_count=0,
                overall_verdict=RecoveryVerdict.RESOLVED,
                recommendation="No blocked skills — all skills passed retention gate",
                skill_reports=[],
            )

        self._skill_reports = []
        for skill in blocked_skills:
            report = self._process_skill(skill)
            self._skill_reports.append(report)

        self._summary = self._build_summary(self._skill_reports)
        return self._summary

    def get_skill_reports(self) -> List[SkillRecoveryReport]:
        """Get individual skill recovery reports."""
        return list(self._skill_reports)

    def get_summary(self) -> RecoverySummary:
        """Get overall recovery summary. Must call run() first."""
        if self._summary is None:
            return self.run()
        return self._summary

    def _process_skill(self, skill: SkillName) -> SkillRecoveryReport:
        """Process recovery for a single blocked skill."""
        # Step 1: Diagnose blocked cases
        diagnoses = self.analyzer.diagnose_skill(skill)

        # Step 2: Propose recovery for each diagnosis
        proposals = [self.analyzer.propose_recovery(d) for d in diagnoses]

        # Step 3: Simulate each proposal
        outcomes = self.simulator.simulate_all(proposals)

        # Step 4: Determine skill recovery verdict
        overall_verdict = self._determine_skill_verdict(outcomes)
        feasibility = self._assess_feasibility(outcomes)

        return SkillRecoveryReport(
            skill_name=skill,
            blocked_case_count=len(diagnoses),
            diagnoses=diagnoses,
            proposals=proposals,
            outcomes=outcomes,
            overall_verdict=overall_verdict,
            recovery_feasibility=feasibility,
        )

    def _determine_skill_verdict(self, outcomes: List[RecoveryOutcome]) -> RecoveryVerdict:
        """Determine overall recovery verdict for a skill based on outcomes."""
        if not outcomes:
            return RecoveryVerdict.UNRESOLVED

        all_resolved = all(o.verdict == RecoveryVerdict.RESOLVED for o in outcomes)
        any_resolved = any(o.verdict == RecoveryVerdict.RESOLVED for o in outcomes)
        any_partial = any(o.verdict == RecoveryVerdict.PARTIALLY_RESOLVED for o in outcomes)

        if all_resolved:
            return RecoveryVerdict.RESOLVED
        if any_resolved or any_partial:
            return RecoveryVerdict.PARTIALLY_RESOLVED
        return RecoveryVerdict.UNRESOLVED

    def _assess_feasibility(self, outcomes: List[RecoveryOutcome]) -> str:
        """Assess recovery feasibility from simulation outcomes."""
        if not outcomes:
            return "low"

        resolved_count = sum(1 for o in outcomes if o.verdict == RecoveryVerdict.RESOLVED)
        total = len(outcomes)
        ratio = resolved_count / total

        if ratio >= 1.0:
            return "high"
        if ratio >= 0.5:
            return "medium"
        return "low"

    def _build_summary(self, reports: List[SkillRecoveryReport]) -> RecoverySummary:
        """Build overall recovery summary from skill reports."""
        total_blocked_cases = sum(r.blocked_case_count for r in reports)
        resolved = sum(1 for r in reports if r.overall_verdict == RecoveryVerdict.RESOLVED)
        partial = sum(1 for r in reports if r.overall_verdict == RecoveryVerdict.PARTIALLY_RESOLVED)
        unresolved = sum(1 for r in reports if r.overall_verdict == RecoveryVerdict.UNRESOLVED)

        # Overall verdict
        if unresolved > 0:
            overall_verdict = RecoveryVerdict.UNRESOLVED
        elif partial > 0:
            overall_verdict = RecoveryVerdict.PARTIALLY_RESOLVED
        else:
            overall_verdict = RecoveryVerdict.RESOLVED

        recommendation = self._build_recommendation(resolved, partial, unresolved, len(reports))

        return RecoverySummary(
            total_blocked_skills=len(reports),
            total_blocked_cases=total_blocked_cases,
            resolved_count=resolved,
            partially_resolved_count=partial,
            unresolved_count=unresolved,
            overall_verdict=overall_verdict,
            recommendation=recommendation,
            skill_reports=reports,
        )

    def _build_recommendation(
        self,
        resolved: int,
        partial: int,
        unresolved: int,
        total: int,
    ) -> str:
        """Build human-readable recommendation."""
        if resolved == total:
            return (
                f"ALL {total} BLOCKED SKILLS RECOVERABLE — "
                f"Apply proposed strategies to restore retention compliance"
            )
        if unresolved == 0:
            return (
                f"{resolved}/{total} skills fully recoverable, "
                f"{partial} partially recoverable — "
                f"Apply primary strategies and investigate partial cases for combined approaches"
            )
        return (
            f"{resolved}/{total} recoverable, {partial} partial, {unresolved} unresolved — "
            f"Unresolved skills require manual investigation or alternative repair approaches"
        )

    def generate_report(self) -> str:
        """Generate human-readable recovery report."""
        if self._summary is None:
            self.run()

        summary = self._summary
        lines = []
        lines.append("=" * 80)
        lines.append("PHASE 8 SKILL RECOVERY ENGINE — RECOVERY REPORT")
        lines.append("=" * 80)
        lines.append("")

        # Overall summary
        lines.append("RECOVERY SUMMARY")
        lines.append("-" * 80)
        lines.append(f"Blocked Skills:       {summary.total_blocked_skills}")
        lines.append(f"Blocked Cases:        {summary.total_blocked_cases}")
        lines.append(f"Resolved:             {summary.resolved_count}")
        lines.append(f"Partially Resolved:   {summary.partially_resolved_count}")
        lines.append(f"Unresolved:           {summary.unresolved_count}")
        lines.append(f"Overall Verdict:      {summary.overall_verdict.value}")
        lines.append(f"Recommendation:       {summary.recommendation}")
        lines.append("")

        # Per-skill details
        for report in summary.skill_reports:
            lines.append(f"SKILL: {report.skill_name.value}")
            lines.append("-" * 80)
            lines.append(f"  Blocked Cases:      {report.blocked_case_count}")
            lines.append(f"  Recovery Verdict:   {report.overall_verdict.value}")
            lines.append(f"  Feasibility:        {report.recovery_feasibility}")
            lines.append("")

            for i, outcome in enumerate(report.outcomes):
                prop = outcome.proposal
                lines.append(f"  Case {i+1}: {prop.test_case_id}")
                lines.append(f"    Loss Category:    {prop.diagnosis.loss_category.value}")
                lines.append(f"    Original Loss:    {outcome.original_loss_pct:.2f}%")
                lines.append(f"    Strategy:         {prop.strategy.value}")
                lines.append(f"    Simulated Loss:   {outcome.simulated_loss_pct:.2f}%")
                lines.append(f"    Improvement:      {outcome.improvement_pct:.2f}%")
                lines.append(f"    Passes Gate:      {outcome.passes_retention_gate}")
                lines.append(f"    Verdict:          {outcome.verdict.value}")
                lines.append(f"    Confidence:       {prop.confidence:.0%}")
                lines.append(f"    Root Cause:       {prop.diagnosis.root_cause}")
                lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)
