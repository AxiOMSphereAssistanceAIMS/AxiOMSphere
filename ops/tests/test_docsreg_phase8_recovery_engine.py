"""PHASE 8 Skill Recovery Engine Tests — validates analysis, simulation, and orchestration."""
import pytest

from ops.docsreg.skills.testing.framework import SkillTestingFramework
from ops.docsreg.skills.testing.models import (
    SkillName,
    SkillVerdict,
    DataRetentionStatus,
)
from ops.docsreg.skills.recovery.models import (
    LossCategory,
    RecoveryStrategy,
    RecoveryVerdict,
    RetentionDiagnosis,
    RecoveryProposal,
    RecoveryOutcome,
    SkillRecoveryReport,
    RecoverySummary,
)
from ops.docsreg.skills.recovery.analyzer import RecoveryAnalyzer
from ops.docsreg.skills.recovery.simulator import RecoverySimulator, RETENTION_GATE_THRESHOLD
from ops.docsreg.skills.recovery.orchestrator import RecoveryOrchestrator


@pytest.fixture(scope="module")
def framework_with_results():
    """Execute framework once for all tests in this module."""
    framework = SkillTestingFramework()
    framework.load_test_cases()
    framework.execute_all_skills()
    return framework


# ── Analyzer Tests ──────────────────────────────────────────────────────────


class TestRecoveryAnalyzerBasics:
    """Analyzer initialization and blocked skill detection."""

    def test_analyzer_initializes(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        assert analyzer.skill_results is not None

    def test_finds_all_blocked_skills(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        blocked = analyzer.get_blocked_skills()
        assert len(blocked) == 6
        for skill in SkillName:
            assert skill in blocked

    def test_get_blocked_cases_returns_fail_cases(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        for skill in SkillName:
            blocked_cases = analyzer.get_blocked_cases(skill)
            assert len(blocked_cases) == 1  # Each skill has exactly 1 FAIL case
            assert blocked_cases[0].retention_report.status == DataRetentionStatus.FAIL

    def test_get_blocked_cases_nonexistent_skill(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        # Clear results to test empty path
        empty_analyzer = RecoveryAnalyzer({})
        assert empty_analyzer.get_blocked_cases(SkillName.FIX_TIMEOUT) == []


class TestDiagnosis:
    """Retention failure diagnosis."""

    def test_diagnose_case_returns_diagnosis(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        blocked = analyzer.get_blocked_cases(SkillName.FIX_TIMEOUT)
        diagnosis = analyzer.diagnose_case(blocked[0])

        assert isinstance(diagnosis, RetentionDiagnosis)
        assert diagnosis.skill_name == SkillName.FIX_TIMEOUT
        assert diagnosis.original_loss_pct > 2.0
        assert diagnosis.severity in ("critical", "moderate", "marginal")
        assert isinstance(diagnosis.loss_category, LossCategory)

    def test_diagnose_all_skills(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        for skill in SkillName:
            diagnoses = analyzer.diagnose_skill(skill)
            assert len(diagnoses) == 1
            assert diagnoses[0].skill_name == skill

    def test_severity_moderate_for_2_to_3_pct(self, framework_with_results):
        """All synthetic cases have 2.2-2.8% loss — should be 'moderate'."""
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        for skill in SkillName:
            diagnoses = analyzer.diagnose_skill(skill)
            for d in diagnoses:
                assert d.severity == "moderate", (
                    f"{skill.value}: loss={d.original_loss_pct}% should be moderate"
                )

    def test_root_cause_is_skill_specific(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        for skill in SkillName:
            diagnoses = analyzer.diagnose_skill(skill)
            for d in diagnoses:
                assert skill.value.lower().replace("_", " ").split("fix ")[-1] in d.root_cause.lower() or \
                    d.test_case_id in d.root_cause


class TestProposal:
    """Recovery strategy proposal."""

    def test_propose_recovery_returns_proposal(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        blocked = analyzer.get_blocked_cases(SkillName.FIX_STRUCTURE)
        diagnosis = analyzer.diagnose_case(blocked[0])
        proposal = analyzer.propose_recovery(diagnosis)

        assert isinstance(proposal, RecoveryProposal)
        assert proposal.skill_name == SkillName.FIX_STRUCTURE
        assert isinstance(proposal.strategy, RecoveryStrategy)
        assert proposal.expected_loss_reduction_pct > 0
        assert proposal.estimated_new_loss_pct < proposal.diagnosis.original_loss_pct
        assert 0.0 <= proposal.confidence <= 1.0

    def test_all_skills_get_proposals(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        assert len(proposals) == 6  # One per blocked skill

    def test_proposal_has_rationale(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        for p in proposals:
            assert len(p.rationale) > 0
            assert isinstance(p.rationale, str)

    def test_proposal_estimated_loss_is_lower(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        for p in proposals:
            assert p.estimated_new_loss_pct < p.diagnosis.original_loss_pct


# ── Simulator Tests ─────────────────────────────────────────────────────────


class TestRecoverySimulator:
    """Recovery strategy simulation."""

    def test_simulate_returns_outcome(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        simulator = RecoverySimulator()

        outcome = simulator.simulate(proposals[0])
        assert isinstance(outcome, RecoveryOutcome)
        assert outcome.simulated_loss_pct >= 0
        assert outcome.original_loss_pct > 2.0
        assert outcome.improvement_pct >= 0

    def test_simulate_all(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        simulator = RecoverySimulator()

        outcomes = simulator.simulate_all(proposals)
        assert len(outcomes) == 6

    def test_simulated_loss_lower_than_original(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        simulator = RecoverySimulator()

        for outcome in simulator.simulate_all(proposals):
            assert outcome.simulated_loss_pct <= outcome.original_loss_pct

    def test_improvement_pct_is_positive(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        simulator = RecoverySimulator()

        for outcome in simulator.simulate_all(proposals):
            assert outcome.improvement_pct >= 0

    def test_verdict_resolved_when_below_threshold(self, framework_with_results):
        """Cases with simulated loss <= 2.0% should be RESOLVED."""
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        simulator = RecoverySimulator()

        for outcome in simulator.simulate_all(proposals):
            if outcome.simulated_loss_pct <= RETENTION_GATE_THRESHOLD:
                assert outcome.verdict == RecoveryVerdict.RESOLVED
                assert outcome.passes_retention_gate is True

    def test_simulation_notes_nonempty(self, framework_with_results):
        analyzer = RecoveryAnalyzer(framework_with_results.skill_results)
        proposals = analyzer.analyze_all_blocked()
        simulator = RecoverySimulator()

        for outcome in simulator.simulate_all(proposals):
            assert len(outcome.simulation_notes) > 0


# ── Orchestrator Tests ──────────────────────────────────────────────────────


class TestRecoveryOrchestrator:
    """End-to-end orchestrator."""

    def test_orchestrator_initializes(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        assert orch.analyzer is not None
        assert orch.simulator is not None

    def test_run_returns_summary(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        summary = orch.run()

        assert isinstance(summary, RecoverySummary)
        assert summary.total_blocked_skills == 6
        assert summary.total_blocked_cases == 6

    def test_summary_counts_sum(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        summary = orch.run()

        assert (
            summary.resolved_count
            + summary.partially_resolved_count
            + summary.unresolved_count
            == summary.total_blocked_skills
        )

    def test_skill_reports_complete(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        summary = orch.run()

        assert len(summary.skill_reports) == 6
        for report in summary.skill_reports:
            assert isinstance(report, SkillRecoveryReport)
            assert report.blocked_case_count >= 1
            assert len(report.diagnoses) >= 1
            assert len(report.proposals) >= 1
            assert len(report.outcomes) >= 1
            assert report.recovery_feasibility in ("high", "medium", "low")

    def test_each_skill_has_diagnosis_proposal_outcome(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        summary = orch.run()

        for report in summary.skill_reports:
            # Each blocked case should have diagnosis → proposal → outcome chain
            assert len(report.diagnoses) == len(report.proposals) == len(report.outcomes)

    def test_summary_has_recommendation(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        summary = orch.run()
        assert len(summary.recommendation) > 0

    def test_overall_verdict_is_valid(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        summary = orch.run()
        assert summary.overall_verdict in (
            RecoveryVerdict.RESOLVED,
            RecoveryVerdict.PARTIALLY_RESOLVED,
            RecoveryVerdict.UNRESOLVED,
        )


class TestOrchestratorNoBlocked:
    """Orchestrator with no blocked skills."""

    def test_no_blocked_returns_resolved(self):
        """When no skills are blocked, overall verdict is RESOLVED."""
        # Empty results = no blocked skills
        orch = RecoveryOrchestrator({})
        summary = orch.run()

        assert summary.total_blocked_skills == 0
        assert summary.overall_verdict == RecoveryVerdict.RESOLVED
        assert "No blocked skills" in summary.recommendation


class TestOrchestratorReport:
    """Report generation."""

    def test_generate_report(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        orch.run()
        report = orch.generate_report()

        assert isinstance(report, str)
        assert "PHASE 8" in report
        assert "RECOVERY SUMMARY" in report
        assert "RECOVERY REPORT" in report

    def test_report_contains_all_skills(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        orch.run()
        report = orch.generate_report()

        for skill in SkillName:
            assert skill.value in report

    def test_report_contains_verdicts(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        orch.run()
        report = orch.generate_report()

        assert "RESOLVED" in report or "PARTIALLY_RESOLVED" in report or "UNRESOLVED" in report

    def test_report_contains_strategies(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        orch.run()
        report = orch.generate_report()

        # At least one strategy should appear
        strategies = [s.value for s in RecoveryStrategy]
        assert any(s in report for s in strategies)

    def test_report_has_delimiters(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        orch.run()
        report = orch.generate_report()

        assert "=" * 80 in report
        assert "-" * 80 in report


class TestGetSummaryIdempotent:
    """get_summary auto-runs if needed."""

    def test_get_summary_without_run(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        # Don't call run() — get_summary should auto-run
        summary = orch.get_summary()
        assert isinstance(summary, RecoverySummary)
        assert summary.total_blocked_skills == 6

    def test_get_skill_reports(self, framework_with_results):
        orch = RecoveryOrchestrator(framework_with_results.skill_results)
        orch.run()
        reports = orch.get_skill_reports()
        assert len(reports) == 6
