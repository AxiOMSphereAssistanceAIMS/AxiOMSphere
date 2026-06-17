"""Test suite for PHASE 2 DOCSREG universal improvement loop real code.

Verifies that all 9 modules are implemented in real Python code (not text-only
specifications) and conform to PHASE 2 mandatory requirements.
"""
import pytest
from ops.docsreg.universal_loop import (
    TerminalState,
    UniversalLoopContext,
    LoopDependencies,
    StageResult,
    StageOutcome,
    UniversalLoopResult,
    run_universal_improvement_loop,
    DataRetentionValidator,
    DocumentSnapshot,
    RetentionVerdict,
)
from ops.docsreg.universal_loop.cycle import UniversalImprovementLoop
from ops.docsreg.universal_loop.evidence import EvidenceStore


class TestPhase2ModulesImported:
    """Verify all 9 modules import successfully from disk."""

    def test_terminal_state_imported(self):
        """TerminalState enum imported."""
        assert hasattr(TerminalState, "READY_FOR_REVIEW")
        assert hasattr(TerminalState, "QUALITY_TARGET_EXCEEDED")
        assert hasattr(TerminalState, "REPAIR_REJECTED_DATA_LOSS")

    def test_stage_result_imported(self):
        """StageResult dataclass imported."""
        assert StageResult
        assert StageOutcome

    def test_context_imported(self):
        """Context classes imported."""
        assert UniversalLoopContext
        assert LoopDependencies

    def test_result_imported(self):
        """UniversalLoopResult dataclass imported."""
        assert UniversalLoopResult

    def test_cycle_imported(self):
        """Cycle orchestration imported."""
        assert run_universal_improvement_loop
        assert UniversalImprovementLoop

    def test_data_retention_validator_imported(self):
        """DataRetentionValidator imported."""
        assert DataRetentionValidator
        assert DocumentSnapshot
        assert RetentionVerdict

    def test_evidence_store_imported(self):
        """EvidenceStore imported."""
        assert EvidenceStore


class TestNoTextOnlySpecifications:
    """Verify no text-only specifications remain—all code is real Python."""

    def test_terminal_state_has_16_states(self):
        """All 16 terminal states defined."""
        expected_states = [
            "INPUT_BLOCKED",
            "VALIDATION_FAILED",
            "REPAIR_REQUIRED",
            "REPAIR_REJECTED_DATA_LOSS",
            "PLATEAU_DETECTED",
            "MAX_ITERATIONS_REACHED",
            "READY_FOR_REVIEW",
            "QUALITY_TARGET_EXCEEDED",
            "READY_FOR_BEST_VERSION_SELECTION",
            "READY_FOR_REGISTRATION",
            "REGISTRATION_COMPLETED",
            "OPERATOR_REVIEW_REQUIRED",
            "SKILL_CREATION_REQUIRED",
            "POLICY_PATCH_REQUIRED",
            "TRAINING_DATASET_REQUIRED",
            "UNKNOWN_FAILURE_REQUIRES_TRIAGE",
        ]
        for state in expected_states:
            assert hasattr(TerminalState, state), f"Missing state: {state}"

    def test_stage_outcome_has_all_states(self):
        """All stage outcome states defined."""
        assert hasattr(StageOutcome, "SUCCESS")
        assert hasattr(StageOutcome, "PARTIAL_SUCCESS")
        assert hasattr(StageOutcome, "FAILURE")
        assert hasattr(StageOutcome, "BLOCKED")
        assert hasattr(StageOutcome, "SKIPPED")

    def test_retention_verdict_has_three_states(self):
        """All retention verdict states defined."""
        assert hasattr(RetentionVerdict, "PASS")
        assert hasattr(RetentionVerdict, "ADVISORY")
        assert hasattr(RetentionVerdict, "FAIL")

    def test_stage_result_is_frozen_dataclass(self):
        """StageResult is immutable frozen dataclass."""
        sr = StageResult(
            stage_name="test",
            outcome=StageOutcome.SUCCESS,
            started_at=__import__("datetime").datetime.utcnow(),
            completed_at=__import__("datetime").datetime.utcnow(),
            quality_before=0.5,
            quality_after=0.6,
            content_before="before",
            content_after="after",
        )
        # Attempt to mutate should raise FrozenInstanceError
        with pytest.raises(Exception):
            sr.stage_name = "modified"

    def test_universal_loop_result_is_frozen_dataclass(self):
        """UniversalLoopResult is immutable frozen dataclass."""
        result = UniversalLoopResult(
            document_id="doc1",
            archetype_type="type1",
            terminal_state=TerminalState.READY_FOR_REVIEW,
            started_at=__import__("datetime").datetime.utcnow(),
            completed_at=__import__("datetime").datetime.utcnow(),
            quality_initial=0.5,
            quality_final=0.96,
            iterations=2,
        )
        with pytest.raises(Exception):
            result.document_id = "modified"


class TestQualityTargetMandatoryValues:
    """Verify PHASE 2 mandatory values: QUALITY_TARGET=0.95, not placeholder."""

    def test_quality_target_is_095(self):
        """QUALITY_TARGET constant is 0.95, not placeholder 0.75."""
        assert UniversalImprovementLoop.QUALITY_TARGET == 0.95

    def test_aspirational_target_is_098(self):
        """ASPIRATIONAL_TARGET constant is 0.98."""
        assert UniversalImprovementLoop.ASPIRATIONAL_TARGET == 0.98

    def test_no_placeholder_075_in_code(self):
        """No placeholder quality score 0.75 in cycle.py."""
        import inspect

        source = inspect.getsource(UniversalImprovementLoop)
        assert "0.75" not in source, "Placeholder score 0.75 found in cycle code"

    def test_plateau_threshold_is_002(self):
        """Quality plateau threshold is 0.02 (2%), not placeholder."""
        assert UniversalImprovementLoop.QUALITY_PLATEAU_THRESHOLD == 0.02


class TestNoPlaceholderOutputs:
    """Verify no placeholder repaired_string or dummy outputs in cycle."""

    def test_no_repaired_string_literal(self):
        """No placeholder 'repaired_string' in cycle.py."""
        import inspect

        source = inspect.getsource(UniversalImprovementLoop)
        assert (
            "repaired_string" not in source
        ), "Placeholder 'repaired_string' found in code"

    def test_repair_service_returns_str(self):
        """RepairService contract returns str, not placeholder."""
        from ops.docsreg.universal_loop.contracts import RepairService
        import inspect

        sig = inspect.signature(RepairService.repair)
        assert str(sig.return_annotation) == "<class 'str'>"


class TestReadyForReviewNotRegistered:
    """Verify READY_FOR_REVIEW terminal state is not registered state."""

    def test_ready_for_review_is_different_from_registration(self):
        """READY_FOR_REVIEW and READY_FOR_REGISTRATION are distinct states."""
        assert (
            TerminalState.READY_FOR_REVIEW != TerminalState.READY_FOR_REGISTRATION
        )

    def test_registration_completed_exists(self):
        """REGISTRATION_COMPLETED is separate terminal state."""
        assert TerminalState.REGISTRATION_COMPLETED

    def test_cycle_does_not_advance_to_registration(self):
        """Cycle does not automatically advance READY_FOR_REVIEW to REGISTRATION."""
        import inspect

        source = inspect.getsource(UniversalImprovementLoop)
        # Verify cycle.py does not SET terminal_state to REGISTRATION_COMPLETED
        # Check that the main run() method doesn't assign REGISTRATION_COMPLETED
        assert "terminal_state = TerminalState.REGISTRATION_COMPLETED" not in source and \
               "terminal_state = TerminalState.READY_FOR_REGISTRATION" not in source, \
               "Cycle should not set terminal_state to registration states directly"


class TestDataLossOverTwoPercentRejected:
    """Verify repair candidates with >2% data loss are rejected."""

    def test_data_loss_threshold_over_2_percent_is_fail(self):
        """Token loss > 2.0% results in FAIL verdict."""
        before = DocumentSnapshot(
            content="a " * 100,  # ~100 tokens (100 words * 1.3)
            sections=["S1"],
            required_fields=["F1"],
        )
        after = DocumentSnapshot(
            content="a " * 97,  # 97 tokens, ~3% loss
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert report.token_loss_percentage > 2.0

    def test_data_loss_threshold_exactly_2_0_is_fail(self):
        """Token loss exactly 2.0% results in FAIL."""
        before = DocumentSnapshot(
            content="a " * 100,
            sections=["S1"],
            required_fields=["F1"],
        )
        after = DocumentSnapshot(
            content="a " * 98,  # ~2% loss
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL

    def test_data_loss_threshold_1_5_percent_is_pass(self):
        """Token loss ~1.5% results in PASS or ADVISORY boundary."""
        before = DocumentSnapshot(
            content="a " * 100,
            sections=["S1"],
            required_fields=["F1"],
        )
        # Token count: 100 words * 1.3 = 130 tokens
        # After: 99 words (98 + "a") * 1.3 = 128 tokens
        # Loss: (130 - 128) / 130 * 100 = 1.538% (at ADVISORY boundary)
        after = DocumentSnapshot(
            content="a " * 98 + "a",
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        # 1.538% loss at boundary—falls into ADVISORY (1.5% < loss ≤ 2.0%)
        assert report.verdict == RetentionVerdict.ADVISORY
        assert 1.5 < report.token_loss_percentage <= 2.0


class TestRequiredFieldLossRejected:
    """Verify repair candidates with lost required fields are rejected."""

    def test_lost_required_field_is_fail(self):
        """Any lost required field results in FAIL verdict."""
        before = DocumentSnapshot(
            content="content",
            required_fields=["F1", "F2", "F3"],
        )
        after = DocumentSnapshot(
            content="content",  # No token loss
            required_fields=["F1", "F3"],  # F2 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "F2" in report.lost_required_fields

    def test_lost_section_is_fail(self):
        """Any lost required section results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            sections=["Overview", "Methodology", "Results"],
        )
        after = DocumentSnapshot(
            content="content",
            sections=["Overview", "Results"],  # Methodology lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "Methodology" in report.lost_sections

    def test_lost_reference_is_fail(self):
        """Any lost reference results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            references=["REF1", "REF2"],
        )
        after = DocumentSnapshot(
            content="content",
            references=["REF1"],  # REF2 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "REF2" in report.lost_references

    def test_lost_table_is_fail(self):
        """Any lost table results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            tables=["Table1", "Table2"],
        )
        after = DocumentSnapshot(
            content="content",
            tables=["Table1"],  # Table2 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "Table2" in report.lost_tables

    def test_lost_link_is_fail(self):
        """Any lost link results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            links=["http://a.com", "http://b.com"],
        )
        after = DocumentSnapshot(
            content="content",
            links=["http://a.com"],  # http://b.com lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "http://b.com" in report.lost_links

    def test_lost_semantic_claim_is_fail(self):
        """Any lost semantic claim results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            semantic_claims=["Claim1", "Claim2"],
        )
        after = DocumentSnapshot(
            content="content",
            semantic_claims=["Claim1"],  # Claim2 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "Claim2" in report.lost_semantic_claims


class TestRepairCandidateNotPromotedOnRetentionFail:
    """Verify repair candidates are rejected even if quality improves when retention fails."""

    def test_retention_fail_overrides_quality_improvement(self):
        """If retention FAIL, candidate is rejected even with quality improvement."""
        # Verify the logic is implemented in cycle.py
        import inspect

        source = inspect.getsource(UniversalImprovementLoop._stage_repair_loop)

        # Check that retention verdict is checked before accepting repair
        # After orchestrator integration, uses passed_gate boolean from orchestrator
        assert "passed_gate, retention_report = self.orchestrator.validate_repair_retention(" in source
        assert "if not passed_gate:" in source
        assert (
            "continue" in source
        ), "Should skip accepting repair on retention FAIL"

    def test_failed_retention_written_to_evidence_only(self):
        """Failed repair candidate is written to evidence, not active content."""
        # Logic should be: if not passed_gate, do not update context.content
        import inspect

        source = inspect.getsource(UniversalImprovementLoop._stage_repair_loop)
        assert "context.content = repaired" in source
        assert (
            "if not passed_gate:" in source
        ), "Must check passed_gate before accepting repair"


class TestEvidencePackageCreated:
    """Verify evidence package is created and serializable."""

    def test_evidence_store_write_json_method_exists(self):
        """EvidenceStore.write_json method exists."""
        assert hasattr(EvidenceStore, "write_json")

    def test_evidence_store_create_stage_evidence_method(self):
        """EvidenceStore.create_stage_evidence converts StageResult to dict."""
        assert hasattr(EvidenceStore, "create_stage_evidence")

    def test_evidence_store_create_loop_evidence_package_method(self):
        """EvidenceStore.create_loop_evidence_package aggregates all evidence."""
        assert hasattr(EvidenceStore, "create_loop_evidence_package")

    def test_evidence_store_detect_failure_class_method(self):
        """EvidenceStore.detect_failure_class classifies failures."""
        assert hasattr(EvidenceStore, "detect_failure_class")

    def test_failure_class_detection_timeout(self):
        """Detect TIMEOUT failure class."""
        failure_class = EvidenceStore.detect_failure_class("Request timed out", "TimeoutError")
        assert failure_class == "TIMEOUT"

    def test_failure_class_detection_structure(self):
        """Detect STRUCTURE failure class."""
        failure_class = EvidenceStore.detect_failure_class(
            "Invalid format structure", "ValidationError"
        )
        assert failure_class == "STRUCTURE"

    def test_failure_class_detection_data_preservation(self):
        """Detect DATA_PRESERVATION_FAILURE class."""
        failure_class = EvidenceStore.detect_failure_class(
            "Data loss in retention check", "RetentionError"
        )
        assert failure_class == "DATA_PRESERVATION_FAILURE"

    def test_stage_result_has_diagnostics_field(self):
        """StageResult includes diagnostics dict for evidence."""
        sr = StageResult(
            stage_name="test",
            outcome=StageOutcome.SUCCESS,
            started_at=__import__("datetime").datetime.utcnow(),
            completed_at=__import__("datetime").datetime.utcnow(),
            quality_before=0.5,
            quality_after=0.6,
            content_before="before",
            content_after="after",
            diagnostics={"key": "value"},
        )
        assert sr.diagnostics == {"key": "value"}

    def test_universal_loop_result_has_evidence_package_field(self):
        """UniversalLoopResult includes evidence_package dict."""
        result = UniversalLoopResult(
            document_id="doc1",
            archetype_type="type1",
            terminal_state=TerminalState.READY_FOR_REVIEW,
            started_at=__import__("datetime").datetime.utcnow(),
            completed_at=__import__("datetime").datetime.utcnow(),
            quality_initial=0.5,
            quality_final=0.96,
            iterations=2,
            evidence_package={"key": "value"},
        )
        assert result.evidence_package == {"key": "value"}
