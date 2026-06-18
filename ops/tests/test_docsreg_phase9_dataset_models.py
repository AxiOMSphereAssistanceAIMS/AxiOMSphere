"""Tests for PHASE 9 Dataset QA Models."""
import pytest
from dataclasses import asdict

from ops.docsreg.dataset_qa.models import (
    AdmissionVerdict,
    LeakageType,
    RejectionReason,
    TrainingExample,
    LeakageFinding,
    DatasetAdmissionResult,
    DeduplicationResult,
    BalanceBucket,
    BalanceReport,
    DatasetManifest,
    DatasetQualityReport,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------

class TestAdmissionVerdict:
    def test_values(self):
        assert AdmissionVerdict.ACCEPTED.value == "ACCEPTED"
        assert AdmissionVerdict.REJECTED.value == "REJECTED"

    def test_count(self):
        assert len(AdmissionVerdict) == 2


class TestLeakageType:
    def test_all_types(self):
        expected = {
            "person_name", "email", "phone", "company_name",
            "document_owner", "approver_role", "logo_marker",
            "internal_id", "author_metadata", "last_modified_by",
            "comments", "tracked_changes", "hidden_text",
            "document_path", "ai_marker",
        }
        actual = {lt.value for lt in LeakageType}
        assert actual == expected

    def test_count(self):
        assert len(LeakageType) == 15


class TestRejectionReason:
    def test_count(self):
        assert len(RejectionReason) >= 18

    def test_key_reasons(self):
        assert RejectionReason.RETENTION_FAIL.value == "retention_fail"
        assert RejectionReason.REPAIR_NOT_PROMOTED.value == "repair_not_promoted"
        assert RejectionReason.IDENTICAL_INPUT_OUTPUT.value == "identical_input_output"


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------

def _make_example(**overrides) -> TrainingExample:
    defaults = dict(
        example_id="ex_doc1_fc1_abcd1234",
        document_id="doc1",
        archetype="technical_report",
        failure_class="missing_header",
        skill_id="fix_structure",
        skill_version="v1",
        source_text="broken text",
        failure_context="header missing",
        repair_instruction="add header",
        repaired_text="fixed text with header",
        quality_before=0.70,
        quality_after=0.95,
        quality_delta=0.25,
        data_retention_rate=0.99,
        data_loss_percentage=1.0,
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


class TestTrainingExample:
    def test_create(self):
        ex = _make_example()
        assert ex.example_id == "ex_doc1_fc1_abcd1234"
        assert ex.quality_delta == 0.25

    def test_to_dict(self):
        ex = _make_example()
        d = asdict(ex)
        assert isinstance(d, dict)
        assert d["document_id"] == "doc1"
        assert len(d) == 22

    def test_all_fields_present(self):
        ex = _make_example()
        d = asdict(ex)
        expected_fields = {
            "example_id", "document_id", "archetype", "failure_class",
            "skill_id", "skill_version", "source_text", "failure_context",
            "repair_instruction", "repaired_text", "quality_before",
            "quality_after", "quality_delta", "data_retention_rate",
            "data_loss_percentage", "required_field_preservation_rate",
            "section_preservation_rate", "retention_verdict", "repair_verdict",
            "input_sha256", "output_sha256", "created_at",
        }
        assert set(d.keys()) == expected_fields


class TestLeakageFinding:
    def test_create(self):
        finding = LeakageFinding(
            leakage_type=LeakageType.EMAIL,
            field_name="source_text",
            matched_text="user@example.com",
            replacement="[EMAIL]",
            position=42,
        )
        assert finding.leakage_type == LeakageType.EMAIL
        assert finding.position == 42


class TestDatasetAdmissionResult:
    def test_accepted(self):
        result = DatasetAdmissionResult(
            example_id="ex1",
            verdict=AdmissionVerdict.ACCEPTED,
        )
        assert result.verdict == AdmissionVerdict.ACCEPTED
        assert result.rejection_reasons == []

    def test_rejected_with_reasons(self):
        result = DatasetAdmissionResult(
            example_id="ex2",
            verdict=AdmissionVerdict.REJECTED,
            rejection_reasons=[RejectionReason.RETENTION_FAIL, RejectionReason.LOSS_TOO_HIGH],
        )
        assert len(result.rejection_reasons) == 2


class TestDeduplicationResult:
    def test_no_duplicates(self):
        r = DeduplicationResult(
            total_before=10, total_after=10, duplicates_removed=0,
            exact_duplicates=0, normalized_duplicates=0,
            near_duplicates=0, same_doc_class_output=0,
        )
        assert r.duplicates_removed == 0
        assert r.total_before == r.total_after

    def test_with_duplicates(self):
        r = DeduplicationResult(
            total_before=10, total_after=7, duplicates_removed=3,
            exact_duplicates=1, normalized_duplicates=1,
            near_duplicates=1, same_doc_class_output=0,
        )
        assert r.exact_duplicates + r.normalized_duplicates + r.near_duplicates == 3


class TestBalanceReport:
    def test_empty(self):
        r = BalanceReport(total_examples=0)
        assert r.passes_balance_gate is True
        assert r.violations == []

    def test_with_violations(self):
        r = BalanceReport(
            total_examples=10,
            violations=["failure_class 'fc1' has 2 examples (minimum: 5)"],
            passes_balance_gate=False,
        )
        assert not r.passes_balance_gate


class TestDatasetManifest:
    def test_defaults(self):
        m = DatasetManifest()
        assert m.phase == "PHASE_9"
        assert m.split_strategy == "document_id"
        assert m.passes_all_gates is False

    def test_serializable(self):
        m = DatasetManifest(training_count=100, validation_count=25)
        d = asdict(m)
        assert d["training_count"] == 100


class TestDatasetQualityReport:
    def test_defaults(self):
        r = DatasetQualityReport()
        assert r.passes_quality_gate is False
        assert r.readiness_checklist == {}
