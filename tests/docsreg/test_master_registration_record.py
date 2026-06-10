"""
Tests for ops/docsreg/docsreg_master_registration.py

Covers:
- RegistrationRecord field types and serialisation
- RegistrationRecordBuilder fluent setters
- Certification status logic (CERTIFIED / REJECTED / PENDING)
- certified_at timestamp population
- Validation (empty document_id, empty document_title)
- create_builder() factory
"""
from __future__ import annotations

import json

import pytest

from ops.docsreg.docsreg_master_registration import (
    RegistrationRecord,
    RegistrationRecordBuilder,
    create_builder,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_REQUIRED_KEYS = {
    "document_id",
    "document_title",
    "document_type",
    "document_version",
    "certification_status",
    "quality_score",
    "gate_verdicts",
    "created_at",
    "certified_at",
    "evidence_dir",
    "notes",
}


def _minimal_builder(
    *,
    doc_id: str = "DOC-2026-001",
    title: str = "Pump Failure Mode Analysis",
    doc_type: str = "AIM",
    version: str = "1.0",
    score: float = 0.97,
    gates: dict | None = None,
    evidence_dir: str = "/evidence/DOC-2026-001",
) -> RegistrationRecordBuilder:
    """Return a pre-filled builder ready for .build()."""
    b = create_builder().set_document(doc_id, title, doc_type, version)
    b.set_quality_score(score)
    b.set_evidence_dir(evidence_dir)
    if gates is not None:
        for gate_name, passed in gates.items():
            b.set_gate_verdict(gate_name, passed)
    return b


# ── TestRegistrationRecord ─────────────────────────────────────────────────────


class TestRegistrationRecord:
    """Tests for the RegistrationRecord dataclass and its serialisation helpers."""

    def _sample_record(self) -> RegistrationRecord:
        return _minimal_builder(
            score=0.97,
            gates={"evidence_gate": True, "precheck_gate": True},
        ).build()

    def test_field_types(self):
        rec = self._sample_record()
        assert isinstance(rec.document_id, str)
        assert isinstance(rec.document_title, str)
        assert isinstance(rec.document_type, str)
        assert isinstance(rec.document_version, str)
        assert isinstance(rec.certification_status, str)
        assert isinstance(rec.quality_score, float)
        assert isinstance(rec.gate_verdicts, dict)
        assert isinstance(rec.created_at, str)
        assert isinstance(rec.certified_at, str)
        assert isinstance(rec.evidence_dir, str)
        assert isinstance(rec.notes, str)

    def test_to_dict_keys_present(self):
        rec = self._sample_record()
        d = rec.to_dict()
        assert _REQUIRED_KEYS.issubset(d.keys()), f"Missing keys: {_REQUIRED_KEYS - d.keys()}"

    def test_to_dict_values_match(self):
        rec = self._sample_record()
        d = rec.to_dict()
        assert d["document_id"] == rec.document_id
        assert d["quality_score"] == rec.quality_score
        assert d["certification_status"] == rec.certification_status

    def test_to_json_valid_json(self):
        rec = self._sample_record()
        raw = rec.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        assert parsed["document_id"] == rec.document_id

    def test_to_json_indented(self):
        rec = self._sample_record()
        raw = rec.to_json()
        # json.dumps with indent=2 produces multi-line output
        assert "\n" in raw

    def test_from_dict_round_trip(self):
        rec = self._sample_record()
        d = rec.to_dict()
        rec2 = RegistrationRecord.from_dict(d)
        assert rec2.document_id == rec.document_id
        assert rec2.document_title == rec.document_title
        assert rec2.document_type == rec.document_type
        assert rec2.document_version == rec.document_version
        assert rec2.certification_status == rec.certification_status
        assert rec2.quality_score == rec.quality_score
        assert rec2.gate_verdicts == rec.gate_verdicts
        assert rec2.created_at == rec.created_at
        assert rec2.certified_at == rec.certified_at
        assert rec2.evidence_dir == rec.evidence_dir
        assert rec2.notes == rec.notes

    def test_from_dict_defaults_notes_and_certified_at(self):
        """from_dict must tolerate missing optional keys."""
        minimal = {
            "document_id": "DOC-X",
            "document_title": "Title",
            "document_type": "AIM",
            "document_version": "1.0",
            "certification_status": "PENDING",
            "quality_score": 0.70,
            "gate_verdicts": {},
            "created_at": "2026-06-10T00:00:00+00:00",
        }
        rec = RegistrationRecord.from_dict(minimal)
        assert rec.notes == ""
        assert rec.certified_at == ""
        assert rec.evidence_dir == ""


# ── TestBuilderSetters ─────────────────────────────────────────────────────────


class TestBuilderSetters:
    """Builder setters must be fluent and must store the provided values."""

    def test_set_document_returns_self(self):
        b = create_builder()
        result = b.set_document("ID-1", "Title", "AIM", "1.0")
        assert result is b

    def test_set_quality_score_returns_self(self):
        b = create_builder()
        result = b.set_quality_score(0.80)
        assert result is b

    def test_set_gate_verdict_returns_self(self):
        b = create_builder()
        result = b.set_gate_verdict("gate_a", True)
        assert result is b

    def test_set_evidence_dir_returns_self(self):
        b = create_builder()
        result = b.set_evidence_dir("/some/path")
        assert result is b

    def test_set_notes_returns_self(self):
        b = create_builder()
        result = b.set_notes("extra info")
        assert result is b

    def test_set_document_values_applied(self):
        rec = (
            create_builder()
            .set_document("DOC-X", "My Title", "PFM", "2.1")
            .set_quality_score(0.70)
            .build()
        )
        assert rec.document_id == "DOC-X"
        assert rec.document_title == "My Title"
        assert rec.document_type == "PFM"
        assert rec.document_version == "2.1"

    def test_set_quality_score_value_applied(self):
        rec = _minimal_builder(score=0.88).build()
        assert rec.quality_score == pytest.approx(0.88)

    def test_set_gate_verdict_values_applied(self):
        rec = (
            _minimal_builder(
                score=0.97,
                gates={"gate_a": True, "gate_b": False},
            ).build()
        )
        assert rec.gate_verdicts["gate_a"] is True
        assert rec.gate_verdicts["gate_b"] is False

    def test_set_evidence_dir_value_applied(self):
        rec = _minimal_builder(evidence_dir="/path/to/evidence").build()
        assert rec.evidence_dir == "/path/to/evidence"

    def test_set_notes_value_applied(self):
        rec = _minimal_builder(score=0.70).set_notes("some note").build()
        assert rec.notes == "some note"

    def test_multiple_gate_verdicts_accumulated(self):
        b = create_builder().set_document("ID", "Title", "AIM", "1.0")
        b.set_quality_score(0.70)
        b.set_gate_verdict("g1", True)
        b.set_gate_verdict("g2", True)
        b.set_gate_verdict("g3", False)
        rec = b.build()
        assert len(rec.gate_verdicts) == 3


# ── TestBuilderCertificationStatus ────────────────────────────────────────────


class TestBuilderCertificationStatus:
    """Certification status must follow the defined thresholds."""

    def test_certified_high_score_all_gates_true(self):
        rec = _minimal_builder(
            score=0.95, gates={"g1": True, "g2": True}
        ).build()
        assert rec.certification_status == "CERTIFIED"

    def test_certified_score_above_threshold(self):
        rec = _minimal_builder(
            score=0.99, gates={"g1": True}
        ).build()
        assert rec.certification_status == "CERTIFIED"

    def test_certified_no_gates_high_score(self):
        """No gates defined — treat as all gates passing."""
        rec = _minimal_builder(score=0.97, gates={}).build()
        assert rec.certification_status == "CERTIFIED"

    def test_rejected_score_below_0_60(self):
        rec = _minimal_builder(score=0.59, gates={}).build()
        assert rec.certification_status == "REJECTED"

    def test_rejected_score_zero(self):
        rec = _minimal_builder(score=0.0, gates={}).build()
        assert rec.certification_status == "REJECTED"

    def test_pending_score_in_range_no_failed_gates(self):
        rec = _minimal_builder(score=0.75, gates={"g1": True}).build()
        assert rec.certification_status == "PENDING"

    def test_pending_score_exactly_0_60(self):
        rec = _minimal_builder(score=0.60, gates={"g1": True}).build()
        assert rec.certification_status == "PENDING"

    def test_pending_high_score_but_gate_failed(self):
        """Score qualifies but a gate failed → PENDING, not CERTIFIED."""
        rec = _minimal_builder(
            score=0.97, gates={"g1": True, "g2": False}
        ).build()
        assert rec.certification_status == "PENDING"

    def test_pending_score_in_middle_mixed_gates(self):
        rec = _minimal_builder(
            score=0.80, gates={"g1": True, "g2": False}
        ).build()
        assert rec.certification_status == "PENDING"


# ── TestBuilderCertifiedAt ─────────────────────────────────────────────────────


class TestBuilderCertifiedAt:
    """certified_at must be populated for CERTIFIED records, empty otherwise."""

    def test_certified_at_populated_when_certified(self):
        rec = _minimal_builder(
            score=0.97, gates={"g1": True}
        ).build()
        assert rec.certification_status == "CERTIFIED"
        assert rec.certified_at != ""

    def test_certified_at_is_iso8601(self):
        from datetime import datetime, timezone

        rec = _minimal_builder(score=0.97, gates={"g1": True}).build()
        # datetime.fromisoformat must not raise
        dt = datetime.fromisoformat(rec.certified_at)
        assert dt.tzinfo is not None

    def test_certified_at_empty_when_rejected(self):
        rec = _minimal_builder(score=0.40, gates={}).build()
        assert rec.certification_status == "REJECTED"
        assert rec.certified_at == ""

    def test_certified_at_empty_when_pending(self):
        rec = _minimal_builder(score=0.75, gates={"g1": True}).build()
        assert rec.certification_status == "PENDING"
        assert rec.certified_at == ""

    def test_created_at_always_populated(self):
        rec = _minimal_builder(score=0.70).build()
        assert rec.created_at != ""


# ── TestBuilderValidation ──────────────────────────────────────────────────────


class TestBuilderValidation:
    """Builder must raise ValueError for missing required fields."""

    def test_empty_document_id_raises(self):
        b = (
            create_builder()
            .set_document("", "Some Title", "AIM", "1.0")
            .set_quality_score(0.70)
        )
        with pytest.raises(ValueError, match="document_id"):
            b.build()

    def test_empty_document_title_raises(self):
        b = (
            create_builder()
            .set_document("DOC-001", "", "AIM", "1.0")
            .set_quality_score(0.70)
        )
        with pytest.raises(ValueError, match="document_title"):
            b.build()

    def test_no_set_document_call_raises(self):
        """Builder with no set_document() call has empty id and title."""
        b = create_builder().set_quality_score(0.70)
        with pytest.raises(ValueError):
            b.build()


# ── TestCreateBuilder ──────────────────────────────────────────────────────────


class TestCreateBuilder:
    """create_builder() must return a fresh, independent RegistrationRecordBuilder."""

    def test_returns_builder_instance(self):
        b = create_builder()
        assert isinstance(b, RegistrationRecordBuilder)

    def test_returns_fresh_builder_each_call(self):
        b1 = create_builder()
        b2 = create_builder()
        assert b1 is not b2

    def test_builders_are_independent(self):
        b1 = create_builder()
        b2 = create_builder()
        b1.set_gate_verdict("g1", True)
        # b2 must not see b1's gate
        b2.set_document("DOC-2", "Title 2", "PFM", "1.0")
        b2.set_quality_score(0.70)
        rec2 = b2.build()
        assert "g1" not in rec2.gate_verdicts
