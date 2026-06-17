"""PHASE 7 Result Aggregator Tests — validates result analysis and classification."""
import pytest

from ops.docsreg.skills.testing.framework import SkillTestingFramework
from ops.docsreg.skills.testing.result_aggregator import (
    ResultAggregator,
    SkillClassification,
    AggregationSummary,
)
from ops.docsreg.skills.testing.models import SkillName, SkillVerdict


class TestResultAggregatorBasics:
    """Basic aggregator initialization and summary generation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_aggregator_initialization(self, framework_with_results):
        """Aggregator initializes with skill results."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        assert aggregator.skill_results is not None
        assert len(aggregator.skill_results) == 6

    def test_get_summary_returns_summary_object(self, framework_with_results):
        """get_summary returns AggregationSummary."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        summary = aggregator.get_summary()

        assert isinstance(summary, AggregationSummary)
        assert summary.total_skills == 6
        assert summary.total_test_cases == 30

    def test_summary_has_all_fields(self, framework_with_results):
        """Summary has all required fields."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        summary = aggregator.get_summary()

        assert summary.total_skills > 0
        assert summary.promoted_skills >= 0
        assert summary.advisory_skills >= 0
        assert summary.blocked_skills >= 0
        assert summary.total_test_cases == 30
        assert summary.promoted_cases >= 0
        assert summary.advisory_cases >= 0
        assert summary.blocked_cases >= 0
        assert summary.retention_failure_count >= 0
        assert isinstance(summary.average_quality_improvement, float)
        assert isinstance(summary.average_repair_time_ms, int)
        assert isinstance(summary.recommendation, str)

    def test_summary_counts_sum_correctly(self, framework_with_results):
        """Summary counts sum to totals correctly."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        summary = aggregator.get_summary()

        assert (
            summary.promoted_skills
            + summary.advisory_skills
            + summary.blocked_skills
            == summary.total_skills
        )
        assert (
            summary.promoted_cases
            + summary.advisory_cases
            + summary.blocked_cases
            == summary.total_test_cases
        )


class TestSkillClassification:
    """Test skill verdict classification."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_classify_skills(self, framework_with_results):
        """Skills are classified by verdict."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        classified = aggregator.classify_skills()

        assert isinstance(classified, dict)
        assert SkillClassification.PROMOTED in classified
        assert SkillClassification.ADVISORY in classified
        assert SkillClassification.BLOCKED in classified

    def test_classification_covers_all_skills(self, framework_with_results):
        """Classification accounts for all 6 skills."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        classified = aggregator.classify_skills()

        total_classified = (
            len(classified[SkillClassification.PROMOTED])
            + len(classified[SkillClassification.ADVISORY])
            + len(classified[SkillClassification.BLOCKED])
        )
        assert total_classified == 6

    def test_get_skills_by_verdict_promoted(self, framework_with_results):
        """Can retrieve skills by PROMOTED verdict."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        promoted_skills = aggregator.get_skills_by_verdict(SkillVerdict.PROMOTED)

        assert isinstance(promoted_skills, list)
        for skill in promoted_skills:
            assert skill in SkillName

    def test_get_skills_by_verdict_advisory(self, framework_with_results):
        """Can retrieve skills by ADVISORY verdict."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        advisory_skills = aggregator.get_skills_by_verdict(SkillVerdict.ADVISORY)

        assert isinstance(advisory_skills, list)
        for skill in advisory_skills:
            assert skill in SkillName

    def test_get_skills_by_verdict_blocked(self, framework_with_results):
        """Can retrieve skills by BLOCKED verdict."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        blocked_skills = aggregator.get_skills_by_verdict(SkillVerdict.BLOCKED)

        assert isinstance(blocked_skills, list)
        for skill in blocked_skills:
            assert skill in SkillName


class TestFailureDetection:
    """Test failure and issue detection."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_find_retention_failures(self, framework_with_results):
        """Can find retention failures (>2% data loss)."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        failures = aggregator.find_retention_failures()

        assert isinstance(failures, list)
        for skill, case_id, loss_pct in failures:
            assert skill in SkillName
            assert isinstance(case_id, str)
            assert isinstance(loss_pct, float)
            assert loss_pct > 2.0

    def test_find_advisory_cases(self, framework_with_results):
        """Can find advisory cases (1.5%-2.0% data loss)."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        advisory = aggregator.find_advisory_cases()

        assert isinstance(advisory, list)
        for skill, case_id, loss_pct in advisory:
            assert skill in SkillName
            assert isinstance(case_id, str)
            assert isinstance(loss_pct, float)
            assert 1.5 <= loss_pct <= 2.0

    def test_get_slowest_repairs(self, framework_with_results):
        """Can retrieve slowest repairs."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        slowest = aggregator.get_slowest_repairs(limit=5)

        assert isinstance(slowest, list)
        assert len(slowest) <= 5
        for skill, case_id, time_ms in slowest:
            assert skill in SkillName
            assert isinstance(case_id, str)
            assert isinstance(time_ms, int)
            assert time_ms > 0

    def test_slowest_repairs_are_sorted(self, framework_with_results):
        """Slowest repairs are sorted in descending order by time."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        slowest = aggregator.get_slowest_repairs(limit=10)

        if len(slowest) > 1:
            for i in range(len(slowest) - 1):
                assert slowest[i][2] >= slowest[i + 1][2]

    def test_get_best_quality_improvements(self, framework_with_results):
        """Can retrieve best quality improvements."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        best = aggregator.get_best_quality_improvements(limit=5)

        assert isinstance(best, list)
        assert len(best) <= 5
        for skill, case_id, delta in best:
            assert skill in SkillName
            assert isinstance(case_id, str)
            assert isinstance(delta, float)

    def test_best_improvements_are_sorted(self, framework_with_results):
        """Best improvements are sorted in descending order by delta."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        best = aggregator.get_best_quality_improvements(limit=10)

        if len(best) > 1:
            for i in range(len(best) - 1):
                assert best[i][2] >= best[i + 1][2]


class TestReportGeneration:
    """Test human-readable report generation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_generate_report(self, framework_with_results):
        """Report generation produces string output."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        report = aggregator.generate_report()

        assert isinstance(report, str)
        assert len(report) > 0

    def test_report_contains_summary_section(self, framework_with_results):
        """Report includes summary section."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        report = aggregator.generate_report()

        assert "SUMMARY" in report
        assert "Total Skills:" in report
        assert "Total Test Cases:" in report

    def test_report_contains_verdict_section(self, framework_with_results):
        """Report includes skill verdicts section."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        report = aggregator.generate_report()

        assert "SKILL VERDICTS" in report

    def test_report_contains_failure_section_if_failures(self, framework_with_results):
        """Report includes failure section if there are retention failures."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        failures = aggregator.find_retention_failures()
        report = aggregator.generate_report()

        if failures:
            assert "RETENTION FAILURES" in report

    def test_report_is_properly_formatted(self, framework_with_results):
        """Report is properly formatted with delimiters."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        report = aggregator.generate_report()

        # Should have header and footer
        assert report.count("=" * 80) >= 2
        # Should have section delimiters
        assert "-" * 80 in report


class TestAggregatorRecommendations:
    """Test aggregator recommendation generation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_recommendation_is_string(self, framework_with_results):
        """Recommendation is a string."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        summary = aggregator.get_summary()

        assert isinstance(summary.recommendation, str)
        assert len(summary.recommendation) > 0

    def test_recommendation_matches_verdict(self, framework_with_results):
        """Recommendation text reflects the verdict."""
        aggregator = ResultAggregator(framework_with_results.skill_results)
        summary = aggregator.get_summary()

        if summary.blocked_skills > 0:
            assert "BLOCKED" in summary.recommendation
        elif summary.advisory_skills > 0:
            assert "ADVISORY" in summary.recommendation
        else:
            assert "PROMOTED" in summary.recommendation
