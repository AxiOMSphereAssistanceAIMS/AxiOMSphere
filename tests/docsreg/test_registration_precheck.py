"""
Tests for ops/docsreg/docsreg_registration_precheck.py

Coverage
--------
- PrecheckResult dataclass fields, defaults, default_factory independence
- run_precheck: all-pass scenario
- run_precheck: traceability failure
- run_precheck: evidence failure (missing files / nonexistent directory)
- run_precheck: write-policy failure
- run_precheck: partial (multi-gate) failures
- run_precheck never raises
"""
from __future__ import annotations

import pytest
from pathlib import Path

from ops.docsreg.docsreg_registration_precheck import PrecheckResult, run_precheck
from ops.docsreg.docsreg_evidence_gate import REQUIRED_EVIDENCE_FILES


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_full_evidence(tmp_path: Path) -> Path:
    """Create a directory containing all required evidence files."""
    for name in REQUIRED_EVIDENCE_FILES:
        (tmp_path / name).touch()
    return tmp_path


REQUIRED = ["section_A", "section_B", "section_C"]
REGISTERED_FULL = ["section_A", "section_B", "section_C", "section_D"]


# ── TestPrecheckResult ─────────────────────────────────────────────────────────


class TestPrecheckResult:
    def test_fields_stored_correctly(self):
        r = PrecheckResult(
            passed=True,
            traceability_passed=True,
            evidence_passed=True,
            write_policy_passed=True,
        )
        assert r.passed is True
        assert r.traceability_passed is True
        assert r.evidence_passed is True
        assert r.write_policy_passed is True

    def test_default_missing_sections_is_empty_list(self):
        r = PrecheckResult(
            passed=False,
            traceability_passed=False,
            evidence_passed=True,
            write_policy_passed=True,
        )
        assert r.missing_sections == []

    def test_default_missing_evidence_is_empty_list(self):
        r = PrecheckResult(
            passed=False,
            traceability_passed=True,
            evidence_passed=False,
            write_policy_passed=True,
        )
        assert r.missing_evidence == []

    def test_default_write_policy_violations_is_empty_list(self):
        r = PrecheckResult(
            passed=False,
            traceability_passed=True,
            evidence_passed=True,
            write_policy_passed=False,
        )
        assert r.write_policy_violations == []

    def test_default_notes_is_empty_string(self):
        r = PrecheckResult(
            passed=True,
            traceability_passed=True,
            evidence_passed=True,
            write_policy_passed=True,
        )
        assert r.notes == ""

    def test_notes_stored(self):
        r = PrecheckResult(
            passed=False,
            traceability_passed=False,
            evidence_passed=False,
            write_policy_passed=False,
            notes="something went wrong",
        )
        assert r.notes == "something went wrong"

    def test_default_factory_independence(self):
        """Two instances must not share the same list objects."""
        r1 = PrecheckResult(
            passed=False,
            traceability_passed=False,
            evidence_passed=False,
            write_policy_passed=False,
        )
        r2 = PrecheckResult(
            passed=False,
            traceability_passed=False,
            evidence_passed=False,
            write_policy_passed=False,
        )
        r1.missing_sections.append("X")
        assert r2.missing_sections == []

        r1.missing_evidence.append("file.json")
        assert r2.missing_evidence == []

        r1.write_policy_violations.append("violation")
        assert r2.write_policy_violations == []

    def test_explicit_list_fields(self):
        r = PrecheckResult(
            passed=False,
            traceability_passed=False,
            evidence_passed=False,
            write_policy_passed=False,
            missing_sections=["sec1"],
            missing_evidence=["f.json"],
            write_policy_violations=["v1", "v2"],
        )
        assert r.missing_sections == ["sec1"]
        assert r.missing_evidence == ["f.json"]
        assert r.write_policy_violations == ["v1", "v2"]


# ── TestRunPrecheckAllPass ─────────────────────────────────────────────────────


class TestRunPrecheckAllPass:
    def test_passed_is_true(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert result.passed is True

    def test_all_sub_gates_pass(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert result.traceability_passed is True
        assert result.evidence_passed is True
        assert result.write_policy_passed is True

    def test_missing_lists_empty(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert result.missing_sections == []
        assert result.missing_evidence == []
        assert result.write_policy_violations == []

    def test_empty_required_sections_passes_traceability(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck([], REGISTERED_FULL, tmp_path)
        assert result.traceability_passed is True
        assert result.passed is True

    def test_none_write_policy_violations_treated_as_empty(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path, write_policy_violations=None)
        assert result.write_policy_passed is True
        assert result.write_policy_violations == []

    def test_empty_write_policy_violations_passes(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path, write_policy_violations=[])
        assert result.write_policy_passed is True


# ── TestRunPrecheckTraceabilityFail ────────────────────────────────────────────


class TestRunPrecheckTraceabilityFail:
    def test_traceability_passed_false(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, ["section_A"], tmp_path)
        assert result.traceability_passed is False

    def test_passed_false(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, ["section_A"], tmp_path)
        assert result.passed is False

    def test_missing_sections_populated(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, ["section_A"], tmp_path)
        assert set(result.missing_sections) == {"section_B", "section_C"}

    def test_missing_sections_exact_count(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, [], tmp_path)
        assert len(result.missing_sections) == len(REQUIRED)

    def test_registered_superset_passes(self, tmp_path):
        """registered_sections is a strict superset — must still pass."""
        _make_full_evidence(tmp_path)
        result = run_precheck(
            REQUIRED,
            REQUIRED + ["extra_section_1", "extra_section_2"],
            tmp_path,
        )
        assert result.traceability_passed is True

    def test_evidence_still_checked_when_traceability_fails(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, [], tmp_path)
        # evidence dir is full → evidence should pass even when traceability fails
        assert result.evidence_passed is True


# ── TestRunPrecheckEvidenceFail ────────────────────────────────────────────────


class TestRunPrecheckEvidenceFail:
    def test_evidence_passed_false_when_files_missing(self, tmp_path):
        # do NOT create any evidence files → empty directory
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert result.evidence_passed is False

    def test_passed_false_when_evidence_missing(self, tmp_path):
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert result.passed is False

    def test_missing_evidence_populated(self, tmp_path):
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert len(result.missing_evidence) == len(REQUIRED_EVIDENCE_FILES)

    def test_partial_evidence_still_fails(self, tmp_path):
        # Create only the first half of the required files
        half = REQUIRED_EVIDENCE_FILES[: len(REQUIRED_EVIDENCE_FILES) // 2]
        for name in half:
            (tmp_path / name).touch()
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert result.evidence_passed is False
        assert len(result.missing_evidence) > 0

    def test_traceability_still_checked_when_evidence_fails(self, tmp_path):
        # traceability should pass; evidence fails due to empty dir
        result = run_precheck(REQUIRED, REGISTERED_FULL, tmp_path)
        assert result.traceability_passed is True


# ── TestRunPrecheckWritePolicyFail ─────────────────────────────────────────────


class TestRunPrecheckWritePolicyFail:
    def test_write_policy_passed_false(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(
            REQUIRED, REGISTERED_FULL, tmp_path,
            write_policy_violations=["file.py is write-protected"],
        )
        assert result.write_policy_passed is False

    def test_passed_false(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(
            REQUIRED, REGISTERED_FULL, tmp_path,
            write_policy_violations=["v1"],
        )
        assert result.passed is False

    def test_violations_propagated(self, tmp_path):
        _make_full_evidence(tmp_path)
        violations = ["violation_A", "violation_B"]
        result = run_precheck(
            REQUIRED, REGISTERED_FULL, tmp_path,
            write_policy_violations=violations,
        )
        assert result.write_policy_violations == violations

    def test_other_gates_pass_when_only_write_policy_fails(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(
            REQUIRED, REGISTERED_FULL, tmp_path,
            write_policy_violations=["v1"],
        )
        assert result.traceability_passed is True
        assert result.evidence_passed is True


# ── TestRunPrecheckPartialFail ─────────────────────────────────────────────────


class TestRunPrecheckPartialFail:
    def test_two_gates_fail_traceability_and_evidence(self, tmp_path):
        # empty dir (evidence fails) + missing sections (traceability fails)
        result = run_precheck(REQUIRED, [], tmp_path)
        assert result.traceability_passed is False
        assert result.evidence_passed is False
        assert result.write_policy_passed is True
        assert result.passed is False

    def test_two_gates_fail_evidence_and_write_policy(self, tmp_path):
        result = run_precheck(
            REQUIRED, REGISTERED_FULL, tmp_path,
            write_policy_violations=["v1"],
        )
        assert result.traceability_passed is True
        assert result.evidence_passed is False
        assert result.write_policy_passed is False
        assert result.passed is False

    def test_all_three_gates_fail(self, tmp_path):
        result = run_precheck(
            REQUIRED, [], tmp_path,
            write_policy_violations=["v1"],
        )
        assert result.traceability_passed is False
        assert result.evidence_passed is False
        assert result.write_policy_passed is False
        assert result.passed is False
        assert len(result.missing_sections) > 0
        assert len(result.missing_evidence) > 0
        assert len(result.write_policy_violations) > 0


# ── TestRunPrecheckNeverRaises ─────────────────────────────────────────────────


class TestRunPrecheckNeverRaises:
    def test_nonexistent_evidence_dir_does_not_raise(self, tmp_path):
        nonexistent = tmp_path / "does" / "not" / "exist"
        result = run_precheck(REQUIRED, REGISTERED_FULL, nonexistent)
        # Must not raise; evidence gate should fail gracefully
        assert result.evidence_passed is False
        assert result.passed is False

    def test_nonexistent_dir_returns_precheck_result(self, tmp_path):
        nonexistent = tmp_path / "ghost_dir"
        result = run_precheck([], [], nonexistent)
        assert isinstance(result, PrecheckResult)

    def test_string_path_accepted(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, REGISTERED_FULL, str(tmp_path))
        assert result.passed is True

    def test_path_object_accepted(self, tmp_path):
        _make_full_evidence(tmp_path)
        result = run_precheck(REQUIRED, REGISTERED_FULL, Path(tmp_path))
        assert result.passed is True
