"""
Tests for DOCSREG evidence gate.

Covers:
  - TestEvidenceGateResult  — dataclass fields, construction, default_factory
  - TestCheckEvidenceGate   — filesystem scenarios via tmp_path
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ops.docsreg.docsreg_evidence_gate import (
    REQUIRED_EVIDENCE_FILES,
    EvidenceGateResult,
    check_evidence_gate,
)


# ---------------------------------------------------------------------------
# TestEvidenceGateResult — dataclass
# ---------------------------------------------------------------------------


class TestEvidenceGateResult:
    """Verify the EvidenceGateResult dataclass fields and defaults."""

    def test_passed_field_true(self):
        result = EvidenceGateResult(passed=True)
        assert result.passed is True

    def test_passed_field_false(self):
        result = EvidenceGateResult(passed=False)
        assert result.passed is False

    def test_default_missing_files_is_empty_list(self):
        result = EvidenceGateResult(passed=False)
        assert result.missing_files == []

    def test_default_present_files_is_empty_list(self):
        result = EvidenceGateResult(passed=True)
        assert result.present_files == []

    def test_default_evidence_dir_is_empty_string(self):
        result = EvidenceGateResult(passed=False)
        assert result.evidence_dir == ""

    def test_explicit_construction(self):
        result = EvidenceGateResult(
            passed=False,
            missing_files=["a.json"],
            present_files=["b.json"],
            evidence_dir="/tmp/evidence",
        )
        assert result.passed is False
        assert result.missing_files == ["a.json"]
        assert result.present_files == ["b.json"]
        assert result.evidence_dir == "/tmp/evidence"

    def test_default_factory_independence(self):
        """Two instances must not share the same list object."""
        r1 = EvidenceGateResult(passed=False)
        r2 = EvidenceGateResult(passed=False)
        r1.missing_files.append("x.json")
        assert r2.missing_files == [], "default_factory must create independent lists"


# ---------------------------------------------------------------------------
# TestCheckEvidenceGate — filesystem scenarios
# ---------------------------------------------------------------------------


class TestCheckEvidenceGate:
    """Verify check_evidence_gate() behaviour across filesystem scenarios."""

    # ── helpers ──────────────────────────────────────────────────────────────

    def _populate(self, directory: Path, filenames: list[str]) -> None:
        """Create empty files in *directory*."""
        for name in filenames:
            (directory / name).touch()

    # ── all files present ────────────────────────────────────────────────────

    def test_pass_when_all_files_present(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        result = check_evidence_gate(tmp_path)
        assert result.passed is True

    def test_pass_missing_is_empty(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        result = check_evidence_gate(tmp_path)
        assert result.missing_files == []

    def test_pass_present_contains_all(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        result = check_evidence_gate(tmp_path)
        assert set(result.present_files) == set(REQUIRED_EVIDENCE_FILES)

    # ── no files present ─────────────────────────────────────────────────────

    def test_fail_when_no_files_present(self, tmp_path):
        result = check_evidence_gate(tmp_path)
        assert result.passed is False

    def test_fail_missing_contains_all_required(self, tmp_path):
        result = check_evidence_gate(tmp_path)
        assert set(result.missing_files) == set(REQUIRED_EVIDENCE_FILES)

    def test_fail_present_is_empty_when_no_files(self, tmp_path):
        result = check_evidence_gate(tmp_path)
        assert result.present_files == []

    # ── partial presence ─────────────────────────────────────────────────────

    def test_fail_when_one_file_missing(self, tmp_path):
        all_files = list(REQUIRED_EVIDENCE_FILES)
        self._populate(tmp_path, all_files[:-1])  # omit last one
        result = check_evidence_gate(tmp_path)
        assert result.passed is False
        assert all_files[-1] in result.missing_files

    def test_partial_present_and_missing_counts_add_up(self, tmp_path):
        all_files = list(REQUIRED_EVIDENCE_FILES)
        present_subset = all_files[:3]
        self._populate(tmp_path, present_subset)
        result = check_evidence_gate(tmp_path)
        assert len(result.present_files) + len(result.missing_files) == len(REQUIRED_EVIDENCE_FILES)

    def test_partial_present_files_match_what_was_created(self, tmp_path):
        present_subset = list(REQUIRED_EVIDENCE_FILES)[:4]
        self._populate(tmp_path, present_subset)
        result = check_evidence_gate(tmp_path)
        assert set(result.present_files) == set(present_subset)

    # ── nonexistent directory ────────────────────────────────────────────────

    def test_fail_when_directory_does_not_exist(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = check_evidence_gate(nonexistent)
        assert result.passed is False

    def test_nonexistent_dir_missing_contains_all(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = check_evidence_gate(nonexistent)
        assert set(result.missing_files) == set(REQUIRED_EVIDENCE_FILES)

    def test_nonexistent_dir_present_is_empty(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = check_evidence_gate(nonexistent)
        assert result.present_files == []

    # ── extra (unrelated) files in directory ─────────────────────────────────

    def test_extra_files_do_not_cause_failure(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        (tmp_path / "extra_file.txt").touch()
        (tmp_path / "another_extra.json").touch()
        result = check_evidence_gate(tmp_path)
        assert result.passed is True

    def test_extra_files_not_in_present_or_missing(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        (tmp_path / "unexpected.json").touch()
        result = check_evidence_gate(tmp_path)
        assert "unexpected.json" not in result.present_files
        assert "unexpected.json" not in result.missing_files

    # ── input type: str vs Path ───────────────────────────────────────────────

    def test_accepts_string_path(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        result = check_evidence_gate(str(tmp_path))
        assert result.passed is True

    def test_accepts_pathlib_path(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        result = check_evidence_gate(tmp_path)
        assert result.passed is True

    # ── evidence_dir field ────────────────────────────────────────────────────

    def test_evidence_dir_field_set_on_pass(self, tmp_path):
        self._populate(tmp_path, list(REQUIRED_EVIDENCE_FILES))
        result = check_evidence_gate(tmp_path)
        assert result.evidence_dir == str(tmp_path)

    def test_evidence_dir_field_set_on_fail(self, tmp_path):
        nonexistent = tmp_path / "missing_dir"
        result = check_evidence_gate(nonexistent)
        assert result.evidence_dir == str(nonexistent)

    # ── constant integrity ────────────────────────────────────────────────────

    def test_required_evidence_files_has_eleven_entries(self):
        assert len(REQUIRED_EVIDENCE_FILES) == 11

    def test_required_evidence_files_contains_best_draft(self):
        assert "best_draft.md" in REQUIRED_EVIDENCE_FILES

    def test_required_evidence_files_contains_registration_precheck(self):
        assert "registration_precheck.json" in REQUIRED_EVIDENCE_FILES

    def test_required_evidence_files_entries_are_unique(self):
        assert len(REQUIRED_EVIDENCE_FILES) == len(set(REQUIRED_EVIDENCE_FILES))
