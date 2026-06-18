"""Tests for PHASE 9 Quality Validator."""
import pytest

from ops.docsreg.dataset_qa.quality_validator import (
    QualityValidator,
    MIN_DATA_RETENTION_RATE,
    MAX_DATA_LOSS_PERCENTAGE,
    MIN_REQUIRED_FIELD_PRESERVATION,
    MIN_SECTION_PRESERVATION,
)
from ops.docsreg.dataset_qa.models import (
    TrainingExample,
    AdmissionVerdict,
    RejectionReason,
)


def _make_example(**overrides) -> TrainingExample:
    """Create a perfect (ACCEPTED) example with optional overrides."""
    defaults = dict(
        example_id="ex_test_1",
        document_id="doc1",
        archetype="technical_report",
        failure_class="missing_header",
        skill_id="fix_structure",
        skill_version="v1",
        source_text="broken text here",
        failure_context="header missing",
        repair_instruction="add header",
        repaired_text="fixed text with header",
        quality_before=0.70,
        quality_after=0.95,
        quality_delta=0.25,
        data_retention_rate=0.995,
        data_loss_percentage=0.5,
        required_field_preservation_rate=1.0,
        section_preservation_rate=0.99,
        retention_verdict="PASS",
        repair_verdict="PROMOTED",
        input_sha256="a" * 64,
        output_sha256="b" * 64,
        created_at="2026-06-18T12:00:00+00:00",
    )
    defaults.update(overrides)
    return TrainingExample(**defaults)


class TestQualityValidator:
    def setup_method(self):
        self.validator = QualityValidator()

    def test_perfect_example_accepted(self):
        ex = _make_example()
        result = self.validator.validate(ex)
        assert result.verdict == AdmissionVerdict.ACCEPTED
        assert result.rejection_reasons == []

    def test_repair_not_promoted(self):
        ex = _make_example(repair_verdict="BLOCKED")
        result = self.validator.validate(ex)
        assert result.verdict == AdmissionVerdict.REJECTED
        assert RejectionReason.REPAIR_NOT_PROMOTED in result.rejection_reasons

    def test_retention_fail(self):
        ex = _make_example(retention_verdict="FAIL")
        result = self.validator.validate(ex)
        assert RejectionReason.RETENTION_FAIL in result.rejection_reasons

    def test_retention_rate_low(self):
        ex = _make_example(data_retention_rate=0.97)
        result = self.validator.validate(ex)
        assert RejectionReason.RETENTION_RATE_LOW in result.rejection_reasons

    def test_retention_rate_boundary(self):
        ex = _make_example(data_retention_rate=0.98)
        result = self.validator.validate(ex)
        assert RejectionReason.RETENTION_RATE_LOW not in result.rejection_reasons

    def test_loss_too_high(self):
        ex = _make_example(data_loss_percentage=2.5)
        result = self.validator.validate(ex)
        assert RejectionReason.LOSS_TOO_HIGH in result.rejection_reasons

    def test_loss_boundary(self):
        ex = _make_example(data_loss_percentage=2.0)
        result = self.validator.validate(ex)
        assert RejectionReason.LOSS_TOO_HIGH not in result.rejection_reasons

    def test_field_preservation_low(self):
        ex = _make_example(required_field_preservation_rate=0.95)
        result = self.validator.validate(ex)
        assert RejectionReason.FIELD_PRESERVATION_LOW in result.rejection_reasons

    def test_section_preservation_low(self):
        ex = _make_example(section_preservation_rate=0.97)
        result = self.validator.validate(ex)
        assert RejectionReason.SECTION_PRESERVATION_LOW in result.rejection_reasons

    def test_no_quality_improvement(self):
        ex = _make_example(quality_delta=0.0)
        result = self.validator.validate(ex)
        assert RejectionReason.QUALITY_NO_IMPROVEMENT in result.rejection_reasons

    def test_negative_quality_delta(self):
        ex = _make_example(quality_delta=-0.05)
        result = self.validator.validate(ex)
        assert RejectionReason.QUALITY_NO_IMPROVEMENT in result.rejection_reasons

    def test_identical_hashes(self):
        ex = _make_example(input_sha256="a" * 64, output_sha256="a" * 64)
        result = self.validator.validate(ex)
        assert RejectionReason.IDENTICAL_INPUT_OUTPUT in result.rejection_reasons

    def test_identical_text(self):
        ex = _make_example(source_text="same", repaired_text="same")
        result = self.validator.validate(ex)
        assert RejectionReason.IDENTICAL_INPUT_OUTPUT in result.rejection_reasons

    def test_empty_source(self):
        ex = _make_example(source_text="   ")
        result = self.validator.validate(ex)
        assert RejectionReason.EMPTY_SOURCE in result.rejection_reasons

    def test_empty_repair(self):
        ex = _make_example(repaired_text="")
        result = self.validator.validate(ex)
        assert RejectionReason.EMPTY_REPAIR in result.rejection_reasons

    def test_missing_failure_class(self):
        ex = _make_example(failure_class="")
        result = self.validator.validate(ex)
        assert RejectionReason.MISSING_FAILURE_CLASS in result.rejection_reasons

    def test_missing_skill_id(self):
        ex = _make_example(skill_id="")
        result = self.validator.validate(ex)
        assert RejectionReason.MISSING_SKILL_ID in result.rejection_reasons

    def test_invalid_hash(self):
        ex = _make_example(input_sha256="short")
        result = self.validator.validate(ex)
        assert RejectionReason.INVALID_HASH in result.rejection_reasons

    def test_multiple_rejections(self):
        ex = _make_example(
            repair_verdict="BLOCKED",
            data_retention_rate=0.90,
            quality_delta=-0.1,
        )
        result = self.validator.validate(ex)
        assert result.verdict == AdmissionVerdict.REJECTED
        assert len(result.rejection_reasons) >= 3

    def test_validate_all(self):
        examples = [_make_example(), _make_example(repair_verdict="BLOCKED")]
        results = self.validator.validate_all(examples)
        assert len(results) == 2
        assert results[0].verdict == AdmissionVerdict.ACCEPTED
        assert results[1].verdict == AdmissionVerdict.REJECTED

    def test_filter_accepted(self):
        examples = [
            _make_example(example_id="ex1"),
            _make_example(example_id="ex2", repair_verdict="BLOCKED"),
        ]
        results = self.validator.validate_all(examples)
        accepted = self.validator.filter_accepted(examples, results)
        assert len(accepted) == 1
        assert accepted[0].example_id == "ex1"

    def test_filter_rejected(self):
        examples = [
            _make_example(example_id="ex1"),
            _make_example(example_id="ex2", repair_verdict="BLOCKED"),
        ]
        results = self.validator.validate_all(examples)
        rejected = self.validator.filter_rejected(examples, results)
        assert len(rejected) == 1
        assert rejected[0].example_id == "ex2"

    def test_notes_describe_rejection(self):
        ex = _make_example(repair_verdict="BLOCKED")
        result = self.validator.validate(ex)
        assert "Rejected for" in result.notes
        assert "repair_not_promoted" in result.notes
