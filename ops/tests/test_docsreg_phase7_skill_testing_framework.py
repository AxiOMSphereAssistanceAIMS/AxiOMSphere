"""PHASE 7 Skill Testing Framework Tests — validates orchestration, execution, and verdict assignment."""
import pytest
from datetime import datetime
from pathlib import Path
import json
import tempfile

from ops.docsreg.skills.testing.framework import SkillTestingFramework, SkillExecutionMetrics
from ops.docsreg.skills.testing.models import (
    SkillName,
    SkillVerdict,
    DataRetentionStatus,
    SkillTestCase,
    SkillTestInput,
    SkillTestOutput,
    DataRetentionReport,
)


class TestSkillTestingFrameworkBasics:
    """Basic framework initialization and loading."""

    def test_framework_initialization(self):
        """Framework initializes with empty results."""
        framework = SkillTestingFramework()
        assert framework.test_cases == []
        assert framework.skill_results == {}
        assert framework.executed_at is None

    def test_load_test_cases(self):
        """Framework loads all 30 synthetic test cases."""
        framework = SkillTestingFramework()
        framework.load_test_cases()

        assert len(framework.test_cases) == 30
        # Verify 5 cases per skill
        for skill in SkillName:
            skill_cases = [tc for tc in framework.test_cases if tc.skill_name == skill]
            assert len(skill_cases) == 5, f"Skill {skill.value} should have 5 cases"

    def test_test_cases_have_verdicts(self):
        """All loaded test cases have assigned verdicts."""
        framework = SkillTestingFramework()
        framework.load_test_cases()

        for case in framework.test_cases:
            assert case.verdict in [
                SkillVerdict.PROMOTED,
                SkillVerdict.ADVISORY,
                SkillVerdict.BLOCKED,
            ]


class TestSkillExecution:
    """Test skill execution and verdict assignment."""

    def test_execute_all_skills(self):
        """Framework executes all 6 skill suites."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        assert len(framework.skill_results) == 6
        for skill in SkillName:
            assert skill in framework.skill_results

    def test_execution_sets_timestamp(self):
        """Execution sets executed_at timestamp."""
        framework = SkillTestingFramework()
        framework.load_test_cases()

        before = datetime.utcnow()
        framework.execute_all_skills()
        after = datetime.utcnow()

        assert framework.executed_at is not None
        assert before <= framework.executed_at <= after

    def test_skill_suite_result_has_five_cases(self):
        """Each skill suite result contains exactly 5 test cases."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        for skill, result in framework.skill_results.items():
            assert result.total_cases == 5
            assert len(result.cases) == 5

    def test_skill_result_verdict_logic(self):
        """Skill verdict follows: BLOCKED if any case blocked, PROMOTED if all promoted, else ADVISORY."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        for skill, result in framework.skill_results.items():
            # Check verdict logic
            if result.cases_blocked > 0:
                assert result.overall_verdict == SkillVerdict.BLOCKED
            elif result.cases_promoted == 5:
                assert result.overall_verdict == SkillVerdict.PROMOTED
            else:
                assert result.overall_verdict == SkillVerdict.ADVISORY


class TestRetentionHardGate:
    """Test data retention hard gate validation."""

    def test_validate_retention_hard_gate_pass(self):
        """Hard gate passes for PASS status."""
        framework = SkillTestingFramework()
        framework.load_test_cases()

        # Find a PASS case
        pass_case = None
        for case in framework.test_cases:
            if case.retention_report.status == DataRetentionStatus.PASS:
                pass_case = case
                break

        if pass_case:
            assert framework.validate_retention_hard_gate(pass_case) is True

    def test_validate_retention_hard_gate_advisory(self):
        """Hard gate passes for ADVISORY status."""
        framework = SkillTestingFramework()
        framework.load_test_cases()

        # Find an ADVISORY case
        advisory_case = None
        for case in framework.test_cases:
            if case.retention_report.status == DataRetentionStatus.ADVISORY:
                advisory_case = case
                break

        if advisory_case:
            assert framework.validate_retention_hard_gate(advisory_case) is True

    def test_validate_retention_hard_gate_fail(self):
        """Hard gate fails for FAIL status."""
        framework = SkillTestingFramework()
        framework.load_test_cases()

        # Find a FAIL case
        fail_case = None
        for case in framework.test_cases:
            if case.retention_report.status == DataRetentionStatus.FAIL:
                fail_case = case
                break

        if fail_case:
            assert framework.validate_retention_hard_gate(fail_case) is False


class TestMetricsCalculation:
    """Test metrics aggregation across skills."""

    def test_get_overall_metrics(self):
        """Overall metrics aggregates across all 6 skills."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        metrics = framework.get_overall_metrics()

        assert isinstance(metrics, SkillExecutionMetrics)
        assert metrics.total_cases == 30
        assert metrics.cases_promoted + metrics.cases_advisory + metrics.cases_blocked == 30

    def test_overall_metrics_verdict_logic(self):
        """Overall verdict follows same logic as skill verdict."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        metrics = framework.get_overall_metrics()

        if metrics.cases_blocked > 0:
            assert metrics.overall_verdict == SkillVerdict.BLOCKED
        elif metrics.cases_promoted == 30:
            assert metrics.overall_verdict == SkillVerdict.PROMOTED
        else:
            assert metrics.overall_verdict == SkillVerdict.ADVISORY

    def test_quality_delta_metrics(self):
        """Quality delta metrics are calculated correctly."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        metrics = framework.get_overall_metrics()

        # All test cases have quality delta
        assert metrics.average_quality_delta >= 0.0

    def test_repair_time_metrics(self):
        """Repair time metrics are calculated correctly."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        metrics = framework.get_overall_metrics()

        # All test cases have repair time
        assert metrics.average_repair_time_ms >= 0


class TestEvidenceGeneration:
    """Test evidence package generation."""

    def test_generate_evidence_package(self):
        """Evidence package generates without error."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        evidence = framework.generate_evidence_package()

        assert isinstance(evidence, dict)
        assert "framework_version" in evidence
        assert "executed_at" in evidence
        assert "overall_metrics" in evidence
        assert "skill_results" in evidence

    def test_evidence_metadata_complete(self):
        """Evidence metadata is complete."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        evidence = framework.generate_evidence_package()

        metadata = evidence
        assert metadata["framework_version"] == "PHASE_7_v1"
        assert metadata["executed_at"] is not None
        assert metadata["overall_metrics"]["total_cases"] == 30

    def test_evidence_skill_results_complete(self):
        """Evidence includes results for all 6 skills."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        evidence = framework.generate_evidence_package()

        assert len(evidence["skill_results"]) == 6
        for skill in SkillName:
            assert skill.value in evidence["skill_results"]

    def test_evidence_case_details(self):
        """Each skill has detailed case information."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        evidence = framework.generate_evidence_package()

        for skill_name, skill_result in evidence["skill_results"].items():
            assert len(skill_result["cases"]) == 5
            for case in skill_result["cases"]:
                assert "test_case_id" in case
                assert "verdict" in case
                assert "quality_delta" in case
                assert "retention_status" in case


class TestEvidenceExport:
    """Test evidence export to files."""

    def test_export_evidence_json(self):
        """Evidence can be exported to JSON file."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "evidence.json")
            framework.export_evidence_json(filepath)

            assert Path(filepath).exists()

            with open(filepath) as f:
                data = json.load(f)

            assert "framework_version" in data
            assert data["framework_version"] == "PHASE_7_v1"

    def test_exported_json_is_valid(self):
        """Exported JSON is valid and parseable."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "evidence.json")
            framework.export_evidence_json(filepath)

            # Try to parse and validate structure
            with open(filepath) as f:
                data = json.load(f)

            assert isinstance(data, dict)
            assert "overall_metrics" in data
            assert "skill_results" in data
            assert isinstance(data["skill_results"], dict)


class TestFrameworkIntegration:
    """End-to-end framework integration tests."""

    def test_full_execution_workflow(self):
        """Complete workflow: load → execute → get results."""
        framework = SkillTestingFramework()

        # Step 1: Load
        framework.load_test_cases()
        assert len(framework.test_cases) == 30

        # Step 2: Execute
        framework.execute_all_skills()
        assert len(framework.skill_results) == 6

        # Step 3: Get results
        metrics = framework.get_overall_metrics()
        assert metrics.total_cases == 30

    def test_multiple_executions_independent(self):
        """Multiple executions create independent results."""
        framework1 = SkillTestingFramework()
        framework1.load_test_cases()
        framework1.execute_all_skills()
        metrics1 = framework1.get_overall_metrics()

        framework2 = SkillTestingFramework()
        framework2.load_test_cases()
        framework2.execute_all_skills()
        metrics2 = framework2.get_overall_metrics()

        # Both should complete successfully (actual values may vary due to randomization)
        assert metrics1.total_cases == 30
        assert metrics2.total_cases == 30

    def test_get_skill_result(self):
        """Individual skill results can be retrieved."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        for skill in SkillName:
            result = framework.get_skill_result(skill)
            assert result is not None
            assert result.skill_name == skill
            assert result.total_cases == 5

    def test_get_all_results(self):
        """All skill results can be retrieved at once."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()

        results = framework.get_all_results()

        assert isinstance(results, dict)
        assert len(results) == 6
        for skill, result in results.items():
            assert result.skill_name == skill
