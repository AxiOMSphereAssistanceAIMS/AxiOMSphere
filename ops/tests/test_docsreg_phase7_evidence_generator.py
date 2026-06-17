"""PHASE 7 Evidence Generator Tests — validates comprehensive evidence package generation and export."""
import pytest
import json
import tempfile
from pathlib import Path

from ops.docsreg.skills.testing.framework import SkillTestingFramework
from ops.docsreg.skills.testing.evidence_generator import EvidenceGenerator, EvidenceMetadata
from ops.docsreg.skills.testing.models import SkillName, SkillVerdict, DataRetentionStatus


class TestEvidenceGeneratorBasics:
    """Basic evidence generator initialization and package creation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_evidence_generator_initialization(self, framework_with_results):
        """EvidenceGenerator initializes with skill results."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        assert generator.skill_results is not None
        assert len(generator.skill_results) == 6

    def test_create_evidence_package_returns_dict(self, framework_with_results):
        """create_evidence_package returns dict."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()

        assert isinstance(evidence, dict)
        assert len(evidence) > 0

    def test_evidence_package_has_required_sections(self, framework_with_results):
        """Evidence package has all required sections."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()

        assert "metadata" in evidence
        assert "aggregated_metrics" in evidence
        assert "skill_details" in evidence
        assert "diagnostics" in evidence
        assert "deployment_readiness" in evidence


class TestEvidenceMetadata:
    """Test evidence metadata generation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_metadata_is_complete(self, framework_with_results):
        """Metadata includes all required fields."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        metadata = evidence["metadata"]

        assert "framework_version" in metadata
        assert "generated_at" in metadata
        assert "execution_timestamp" in metadata
        assert "total_skills" in metadata
        assert "total_cases" in metadata
        assert "overall_verdict" in metadata

    def test_metadata_values_correct(self, framework_with_results):
        """Metadata values are correct."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        metadata = evidence["metadata"]

        assert metadata["framework_version"] == "PHASE_7_v1"
        assert metadata["total_skills"] == 6
        assert metadata["total_cases"] == 30
        assert metadata["overall_verdict"] in ["PROMOTED", "ADVISORY", "BLOCKED"]


class TestAggregatedMetrics:
    """Test aggregated metrics generation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_aggregated_metrics_has_required_fields(self, framework_with_results):
        """Aggregated metrics has all required fields."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        metrics = evidence["aggregated_metrics"]

        assert "total_test_cases" in metrics
        assert "promoted_cases" in metrics
        assert "advisory_cases" in metrics
        assert "blocked_cases" in metrics
        assert "promotion_rate_percent" in metrics
        assert "quality_metrics" in metrics
        assert "performance_metrics" in metrics
        assert "retention_metrics" in metrics

    def test_aggregated_metrics_counts_sum(self, framework_with_results):
        """Case counts sum to total."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        metrics = evidence["aggregated_metrics"]

        total = (
            metrics["promoted_cases"]
            + metrics["advisory_cases"]
            + metrics["blocked_cases"]
        )
        assert total == metrics["total_test_cases"]
        assert total == 30

    def test_quality_metrics_present(self, framework_with_results):
        """Quality metrics are present and valid."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        quality = evidence["aggregated_metrics"]["quality_metrics"]

        assert "average_quality_delta" in quality
        assert "min_quality_delta" in quality
        assert "max_quality_delta" in quality
        assert isinstance(quality["average_quality_delta"], (int, float))
        assert isinstance(quality["min_quality_delta"], (int, float))
        assert isinstance(quality["max_quality_delta"], (int, float))

    def test_performance_metrics_present(self, framework_with_results):
        """Performance metrics are present and valid."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        perf = evidence["aggregated_metrics"]["performance_metrics"]

        assert "average_repair_time_ms" in perf
        assert "min_repair_time_ms" in perf
        assert "max_repair_time_ms" in perf
        assert isinstance(perf["average_repair_time_ms"], int)
        assert perf["average_repair_time_ms"] >= 0

    def test_retention_metrics_present(self, framework_with_results):
        """Retention metrics are present and valid."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        retention = evidence["aggregated_metrics"]["retention_metrics"]

        assert "failure_count" in retention
        assert "failure_rate_percent" in retention
        assert isinstance(retention["failure_count"], int)
        assert isinstance(retention["failure_rate_percent"], (int, float))


class TestSkillDetails:
    """Test skill-by-skill detail generation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_skill_details_covers_all_skills(self, framework_with_results):
        """Skill details includes all 6 skills."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        skills = evidence["skill_details"]

        assert len(skills) == 6
        for skill in SkillName:
            assert skill.value in skills

    def test_skill_detail_has_required_fields(self, framework_with_results):
        """Each skill detail has required fields."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()

        for skill_name, skill_detail in evidence["skill_details"].items():
            assert "overall_verdict" in skill_detail
            assert "total_cases" in skill_detail
            assert "cases_promoted" in skill_detail
            assert "cases_advisory" in skill_detail
            assert "cases_blocked" in skill_detail
            assert "executed_at" in skill_detail
            assert "cases" in skill_detail

    def test_skill_detail_has_five_cases(self, framework_with_results):
        """Each skill detail has exactly 5 test cases."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()

        for skill_detail in evidence["skill_details"].values():
            assert skill_detail["total_cases"] == 5
            assert len(skill_detail["cases"]) == 5

    def test_skill_case_has_required_fields(self, framework_with_results):
        """Each skill case has required fields."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()

        for skill_detail in evidence["skill_details"].values():
            for case in skill_detail["cases"]:
                assert "test_case_id" in case
                assert "verdict" in case
                assert "quality_delta" in case
                assert "retention_status" in case


class TestDiagnostics:
    """Test diagnostic information generation."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_diagnostics_has_required_sections(self, framework_with_results):
        """Diagnostics has all required sections."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        diag = evidence["diagnostics"]

        assert "retention_failures" in diag
        assert "advisory_cases" in diag
        assert "slow_repairs" in diag

    def test_retention_failures_list_type(self, framework_with_results):
        """Retention failures is a list."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        failures = evidence["diagnostics"]["retention_failures"]

        assert isinstance(failures, list)
        if failures:
            for failure in failures:
                assert "skill" in failure
                assert "test_case_id" in failure
                assert "token_loss_percentage" in failure
                assert "guidance" in failure

    def test_advisory_cases_list_type(self, framework_with_results):
        """Advisory cases is a list."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        advisory = evidence["diagnostics"]["advisory_cases"]

        assert isinstance(advisory, list)
        if advisory:
            for case in advisory:
                assert "skill" in case
                assert "test_case_id" in case
                assert "token_loss_percentage" in case
                assert "guidance" in case

    def test_slow_repairs_list_type(self, framework_with_results):
        """Slow repairs is a list."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        slow = evidence["diagnostics"]["slow_repairs"]

        assert isinstance(slow, list)
        if slow:
            for repair in slow:
                assert "skill" in repair
                assert "test_case_id" in repair
                assert "repair_time_ms" in repair
                assert "guidance" in repair


class TestDeploymentReadiness:
    """Test deployment readiness assessment."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_deployment_readiness_has_required_fields(self, framework_with_results):
        """Deployment readiness has all required fields."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        deploy = evidence["deployment_readiness"]

        assert "status" in deploy
        assert "promoted_skills" in deploy
        assert "advisory_skills" in deploy
        assert "blocked_skills" in deploy
        assert "recommendation" in deploy
        assert "gates" in deploy

    def test_deployment_status_values(self, framework_with_results):
        """Deployment status is valid."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        status = evidence["deployment_readiness"]["status"]

        assert status in ["PROMOTED", "ADVISORY", "BLOCKED"]

    def test_deployment_recommendation_present(self, framework_with_results):
        """Deployment recommendation is present and meaningful."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        rec = evidence["deployment_readiness"]["recommendation"]

        assert isinstance(rec, str)
        assert len(rec) > 0
        # Should contain action directive
        assert any(word in rec for word in ["PROMOTED", "ADVISORY", "BLOCKED", "INVESTIGATE", "FIX"])

    def test_deployment_gates_present(self, framework_with_results):
        """Deployment gates are present."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()
        gates = evidence["deployment_readiness"]["gates"]

        assert "retention_gate_status" in gates
        assert "quality_target_status" in gates
        assert "repair_efficacy_status" in gates

        for gate_status in gates.values():
            assert gate_status in ["PASS", "FAIL"]


class TestJsonExport:
    """Test JSON export functionality."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_export_json_creates_file(self, framework_with_results):
        """export_json creates a file."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "evidence.json")
            generator.export_json(filepath)

            assert Path(filepath).exists()

    def test_exported_json_is_valid(self, framework_with_results):
        """Exported JSON is valid and parseable."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "evidence.json")
            generator.export_json(filepath)

            with open(filepath) as f:
                data = json.load(f)

            assert isinstance(data, dict)
            assert "metadata" in data
            assert "aggregated_metrics" in data

    def test_exported_json_contains_all_sections(self, framework_with_results):
        """Exported JSON contains all evidence sections."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "evidence.json")
            generator.export_json(filepath)

            with open(filepath) as f:
                data = json.load(f)

            assert "metadata" in data
            assert "aggregated_metrics" in data
            assert "skill_details" in data
            assert "diagnostics" in data
            assert "deployment_readiness" in data


class TestTextReportExport:
    """Test text report export functionality."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_export_text_report_creates_file(self, framework_with_results):
        """export_text_report creates a file."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "report.txt")
            generator.export_text_report(filepath)

            assert Path(filepath).exists()

    def test_exported_text_is_string(self, framework_with_results):
        """Exported text is readable string."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "report.txt")
            generator.export_text_report(filepath)

            with open(filepath) as f:
                content = f.read()

            assert isinstance(content, str)
            assert len(content) > 0

    def test_exported_text_contains_sections(self, framework_with_results):
        """Exported text contains required sections."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "report.txt")
            generator.export_text_report(filepath)

            with open(filepath) as f:
                content = f.read()

            assert "METADATA" in content
            assert "AGGREGATED METRICS" in content
            assert "DEPLOYMENT READINESS" in content

    def test_exported_text_has_proper_formatting(self, framework_with_results):
        """Exported text has proper formatting."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "report.txt")
            generator.export_text_report(filepath)

            with open(filepath) as f:
                content = f.read()

            # Should have header and footer delimiters
            assert "=" * 100 in content
            # Should have section delimiters
            assert "-" * 100 in content


class TestEvidenceIntegration:
    """End-to-end evidence generation tests."""

    @pytest.fixture
    def framework_with_results(self):
        """Execute framework once and return results."""
        framework = SkillTestingFramework()
        framework.load_test_cases()
        framework.execute_all_skills()
        return framework

    def test_full_evidence_workflow(self, framework_with_results):
        """Complete evidence workflow: create → export JSON/text."""
        generator = EvidenceGenerator(framework_with_results.skill_results)

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = str(Path(tmpdir) / "evidence.json")
            text_path = str(Path(tmpdir) / "report.txt")

            # Create and export
            generator.export_json(json_path)
            generator.export_text_report(text_path)

            # Verify both files exist
            assert Path(json_path).exists()
            assert Path(text_path).exists()

            # Verify JSON is valid
            with open(json_path) as f:
                json_data = json.load(f)
            assert "metadata" in json_data

            # Verify text is readable
            with open(text_path) as f:
                text_data = f.read()
            assert len(text_data) > 0

    def test_evidence_reflects_actual_results(self, framework_with_results):
        """Evidence package reflects actual framework results."""
        generator = EvidenceGenerator(framework_with_results.skill_results)
        evidence = generator.create_evidence_package()

        # Total cases should match framework
        assert evidence["metadata"]["total_cases"] == 30
        assert evidence["aggregated_metrics"]["total_test_cases"] == 30

        # Skills should match framework
        assert evidence["metadata"]["total_skills"] == 6
        assert len(evidence["skill_details"]) == 6

        # Verdict logic should be consistent
        if evidence["deployment_readiness"]["blocked_skills"] > 0:
            assert evidence["metadata"]["overall_verdict"] == "BLOCKED"
        elif evidence["deployment_readiness"]["promoted_skills"] == 6:
            assert evidence["metadata"]["overall_verdict"] == "PROMOTED"
        else:
            assert evidence["metadata"]["overall_verdict"] == "ADVISORY"
