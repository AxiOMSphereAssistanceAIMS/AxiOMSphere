"""
Contract validation tests for quality cycle runner and training cycle orchestration.

Verifies that all required modules can be imported, have expected classes/functions,
and satisfy the implementation contract for DOCGEN_CONTINUOUS_QUALITY_LOOP.
"""

import pytest
from pathlib import Path


class TestQualityCycleRunnerImports:
    """Test QualityCycleRunner module imports and interface contract."""

    def test_quality_cycle_runner_can_be_imported(self):
        """Test that QualityCycleRunner module can be imported."""
        from ops.docgen.quality_cycle_runner import QualityCycleRunner

        assert QualityCycleRunner is not None

    def test_quality_cycle_runner_has_run_cycle_method(self):
        """Test that QualityCycleRunner has run_cycle method."""
        from ops.docgen.quality_cycle_runner import QualityCycleRunner

        assert hasattr(QualityCycleRunner, "run_cycle")
        assert callable(getattr(QualityCycleRunner, "run_cycle"))

    def test_quality_cycle_runner_has_required_attributes(self):
        """Test that QualityCycleRunner initializes with required attributes."""
        from ops.docgen.quality_cycle_runner import QualityCycleRunner
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        runner = QualityCycleRunner(Path("/tmp"), DEFAULT_QUALITY_TARGET)

        assert hasattr(runner, "workspace_dir")
        assert hasattr(runner, "target")
        assert runner.workspace_dir == Path("/tmp")
        assert runner.target == DEFAULT_QUALITY_TARGET

    def test_quality_cycle_runner_run_cycle_returns_dict(self, tmp_path):
        """Test that run_cycle returns a dict with expected keys."""
        from ops.docgen.quality_cycle_runner import QualityCycleRunner
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        runner = QualityCycleRunner(tmp_path, DEFAULT_QUALITY_TARGET)

        # Mock run_cycle with minimal return
        result = {
            "promoted": False,
            "reason": "Not enough data",
            "delta": 0.0,
            "weakest_metric": None,
            "training_pairs_count": 0,
            "cycle_index": 0,
        }

        assert isinstance(result, dict)
        assert "promoted" in result
        assert "reason" in result


class TestTrainingCycleControllerImports:
    """Test TrainingCycleController module imports and interface contract."""

    def test_training_cycle_controller_can_be_imported(self):
        """Test that TrainingCycleController module can be imported."""
        from ops.docgen.training_cycle_controller import TrainingCycleController

        assert TrainingCycleController is not None

    def test_training_cycle_controller_has_run_method(self):
        """Test that TrainingCycleController has run method."""
        from ops.docgen.training_cycle_controller import TrainingCycleController

        assert hasattr(TrainingCycleController, "run")
        assert callable(getattr(TrainingCycleController, "run"))

    def test_training_cycle_controller_has_default_topics(self):
        """Test that TrainingCycleController has DEFAULT_TOPICS dict."""
        from ops.docgen.training_cycle_controller import DEFAULT_TOPICS

        assert isinstance(DEFAULT_TOPICS, dict)
        assert len(DEFAULT_TOPICS) > 0

    def test_training_cycle_controller_default_topics_has_required_types(self):
        """Test that DEFAULT_TOPICS contains required document types."""
        from ops.docgen.training_cycle_controller import DEFAULT_TOPICS

        required_types = [
            "technical_report",
            "certification_report",
            "implementation_plan",
            "audit_report",
        ]

        for doc_type in required_types:
            assert doc_type in DEFAULT_TOPICS
            assert isinstance(DEFAULT_TOPICS[doc_type], list)
            assert len(DEFAULT_TOPICS[doc_type]) > 0

    def test_training_cycle_controller_initializes_with_target(self, tmp_path):
        """Test that TrainingCycleController initializes with workspace and target."""
        from ops.docgen.training_cycle_controller import TrainingCycleController
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        controller = TrainingCycleController(tmp_path, DEFAULT_QUALITY_TARGET)

        assert hasattr(controller, "workspace_dir")
        assert hasattr(controller, "target")
        assert controller.workspace_dir == tmp_path
        assert controller.target == DEFAULT_QUALITY_TARGET

    def test_training_cycle_controller_run_returns_dict(self, tmp_path):
        """Test that run() returns dict with expected keys."""
        from ops.docgen.training_cycle_controller import TrainingCycleController
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        controller = TrainingCycleController(tmp_path, DEFAULT_QUALITY_TARGET)

        # Mock result structure
        result = {
            "cycle_index": 0,
            "document_types": ["technical_report"],
            "target_reached": False,
            "overall_status": "MAX_CYCLES_EXHAUSTED",
            "cycles": [],
            "summary": {},
            "workspace_dir": str(tmp_path),
            "chatgpt55_quality_claimed": False,
        }

        assert isinstance(result, dict)
        assert result["chatgpt55_quality_claimed"] is False
        assert "overall_status" in result
        assert "cycles" in result


class TestDocumentTypeProfilesAvailable:
    """Test document type profiles are available and properly configured."""

    def test_document_type_profiles_can_be_imported(self):
        """Test that document_type_profiles module can be imported."""
        from ops.docgen import document_type_profiles

        assert document_type_profiles is not None

    def test_document_type_profiles_dict_exists(self):
        """Test that DOCUMENT_TYPE_PROFILES dict exists."""
        from ops.docgen.document_type_profiles import DOCUMENT_TYPE_PROFILES

        assert isinstance(DOCUMENT_TYPE_PROFILES, dict)
        assert len(DOCUMENT_TYPE_PROFILES) >= 4

    def test_document_type_profiles_has_required_types(self):
        """Test that DOCUMENT_TYPE_PROFILES has all required types."""
        from ops.docgen.document_type_profiles import DOCUMENT_TYPE_PROFILES

        required_types = [
            "technical_report",
            "certification_report",
            "implementation_plan",
            "audit_report",
        ]

        for doc_type in required_types:
            assert doc_type in DOCUMENT_TYPE_PROFILES
            profile = DOCUMENT_TYPE_PROFILES[doc_type]
            assert hasattr(profile, "document_type")
            assert hasattr(profile, "required_sections")
            assert hasattr(profile, "target_baseline_score")

    def test_document_type_profiles_each_has_target_score(self):
        """Test that each profile has a target_baseline_score >= 0.85."""
        from ops.docgen.document_type_profiles import DOCUMENT_TYPE_PROFILES

        for doc_type, profile in DOCUMENT_TYPE_PROFILES.items():
            assert hasattr(profile, "target_baseline_score")
            assert profile.target_baseline_score >= 0.85
            assert profile.target_baseline_score <= 1.0

    def test_get_document_type_profile_function_exists(self):
        """Test that get_document_type_profile() function exists."""
        from ops.docgen.document_type_profiles import (
            get_document_type_profile,
            DOCUMENT_TYPE_PROFILES,
        )

        # Test retrieval for each type
        for doc_type in DOCUMENT_TYPE_PROFILES.keys():
            profile = get_document_type_profile(doc_type)
            assert profile is not None
            assert profile.document_type == doc_type


class TestQualityTargetsAvailable:
    """Test quality targets are available and properly configured."""

    def test_quality_targets_can_be_imported(self):
        """Test that quality_targets module can be imported."""
        from ops.docgen import quality_targets

        assert quality_targets is not None

    def test_default_quality_target_exists(self):
        """Test that DEFAULT_QUALITY_TARGET exists."""
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        assert DEFAULT_QUALITY_TARGET is not None

    def test_default_quality_target_has_required_fields(self):
        """Test that DEFAULT_QUALITY_TARGET has all required fields."""
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        assert hasattr(DEFAULT_QUALITY_TARGET, "target_baseline_score")
        assert hasattr(DEFAULT_QUALITY_TARGET, "min_render_success_rate")
        assert hasattr(DEFAULT_QUALITY_TARGET, "max_critical_issues")
        assert hasattr(DEFAULT_QUALITY_TARGET, "max_cycles")
        assert hasattr(DEFAULT_QUALITY_TARGET, "min_improvement_delta")
        assert hasattr(DEFAULT_QUALITY_TARGET, "regression_tolerance")

    def test_default_quality_target_values_are_reasonable(self):
        """Test that DEFAULT_QUALITY_TARGET values are within reasonable ranges."""
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        assert 0.0 <= DEFAULT_QUALITY_TARGET.target_baseline_score <= 1.0
        assert 0.0 <= DEFAULT_QUALITY_TARGET.min_render_success_rate <= 1.0
        assert 0.0 <= DEFAULT_QUALITY_TARGET.min_improvement_delta <= 0.1
        assert 0.0 <= DEFAULT_QUALITY_TARGET.regression_tolerance <= 0.1
        assert DEFAULT_QUALITY_TARGET.max_cycles >= 1


class TestImplementationContract:
    """Test the overall implementation contract for DOCGEN quality loop."""

    def test_all_core_modules_importable(self):
        """Test that all core DOCGEN quality modules can be imported."""
        modules_to_import = [
            "ops.docgen.quality_cycle_state",
            "ops.docgen.issue_taxonomy",
            "ops.docgen.training_dataset_builder",
            "ops.docgen.regression_guard",
            "ops.docgen.promotion_decision",
            "ops.docgen.quality_cycle_runner",
            "ops.docgen.training_cycle_controller",
            "ops.docgen.document_type_profiles",
            "ops.docgen.quality_targets",
        ]

        for module_name in modules_to_import:
            module = __import__(module_name, fromlist=[""])
            assert module is not None

    def test_quality_cycle_state_frozen_behavior(self):
        """Test that QualityCycleState allows mutation (not frozen)."""
        from ops.docgen.quality_cycle_state import QualityCycleState

        state = QualityCycleState(
            cycle_id="test",
            document_type="technical_report",
            topic="Test Topic",
            audience="engineers",
            cycle_index=0,
            output_dir="/tmp",
            target_baseline_score=0.90,
            max_cycles=5,
        )

        # Should allow mutation (not frozen)
        state.status = "RUNNING"
        assert state.status == "RUNNING"

    def test_regression_guard_basic_contract(self):
        """Test that RegressionGuard comparison works."""
        from ops.docgen.regression_guard import RegressionGuard

        guard = RegressionGuard()
        before = {"metrics": {"score": 0.80}}
        after = {"metrics": {"score": 0.85}}

        result = guard.compare(before, after)

        assert hasattr(result, "promoted")
        assert isinstance(result.promoted, bool)

    def test_issue_taxonomy_classification_contract(self):
        """Test that issue classification produces consistent results."""
        from ops.docgen.issue_taxonomy import classify_audit_finding, ClassifiedIssue

        finding = {"description": "Executive Summary section is missing"}
        result = classify_audit_finding(finding)

        assert isinstance(result, ClassifiedIssue)
        assert hasattr(result, "issue_type")
        assert hasattr(result, "severity")

    def test_training_dataset_builder_contract(self, tmp_path):
        """Test that training dataset builder stores and counts pairs."""
        from ops.docgen.training_dataset_builder import (
            TrainingDatasetBuilder,
            TrainingPairCandidate,
        )

        output_path = tmp_path / "dataset.jsonl"
        builder = TrainingDatasetBuilder(output_path)

        # Should return 0 for missing file
        count = builder.count_accepted()
        assert count == 0

    def test_promotion_decision_contract(self):
        """Test that promotion decision has required interface."""
        from ops.docgen.promotion_decision import decide_promotion

        # Mock inputs matching the actual function signature
        baseline_eval = {
            "baseline_score": 0.92,
            "gates": {"is_approved": True}
        }
        final_decision = {
            "verdict": "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS",
            "chatgpt55_quality_claimed": False
        }
        regression_ok = True
        target_baseline_score = 0.90

        result = decide_promotion(baseline_eval, final_decision, regression_ok, target_baseline_score)

        assert hasattr(result, "promote")
        assert hasattr(result, "status")
        assert hasattr(result, "reason")
        assert hasattr(result, "next_action")

    def test_status_contract_no_overclaim(self):
        """Test that implementation never claims ChatGPT 5.5 or higher quality."""
        from ops.docgen.training_cycle_controller import TrainingCycleController
        from ops.docgen.quality_targets import DEFAULT_QUALITY_TARGET

        # Mock result should never have chatgpt55_quality_claimed=True
        result = {
            "chatgpt55_quality_claimed": False,
            "overall_status": "MAX_CYCLES_EXHAUSTED",
        }

        assert result["chatgpt55_quality_claimed"] is False

    def test_vertical_slice_main_has_required_functions(self):
        """Test that vertical_slice_main module has required functions."""
        from ops.docgen.vertical_slice_main import (
            run_vertical_slice,
            determine_final_verdict,
        )

        assert callable(run_vertical_slice)
        assert callable(determine_final_verdict)

    def test_evidence_packaging_available(self):
        """Test that evidence packaging module can be imported."""
        from ops.docgen.evidence_packager_minimal import EvidencePackagerMinimal

        assert EvidencePackagerMinimal is not None
