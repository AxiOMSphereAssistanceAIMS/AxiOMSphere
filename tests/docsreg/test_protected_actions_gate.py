"""
Tests for DOCSREG protected-actions audit gate.

Covers:
  - TestProtectedActionsResult       — dataclass fields, defaults, default_factory
  - TestCheckProtectedActionsGate    — filesystem scenarios via tmp_path
  - TestProtectedActionsFileConstant — module-level constant
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.docsreg.docsreg_protected_actions_gate import (
    PROTECTED_ACTIONS_FILE,
    ProtectedActionsResult,
    check_protected_actions,
)

_AUDIT_FILE = PROTECTED_ACTIONS_FILE  # "protected_actions_audit.json"


# ---------------------------------------------------------------------------
# TestProtectedActionsResult — dataclass
# ---------------------------------------------------------------------------


class TestProtectedActionsResult:
    """Verify ProtectedActionsResult dataclass fields and defaults."""

    def test_passed_field_true(self):
        r = ProtectedActionsResult(passed=True)
        assert r.passed is True

    def test_passed_field_false(self):
        r = ProtectedActionsResult(passed=False)
        assert r.passed is False

    def test_default_flagged_actions_is_empty_list(self):
        r = ProtectedActionsResult(passed=False)
        assert r.flagged_actions == []

    def test_default_all_actions_is_empty_list(self):
        r = ProtectedActionsResult(passed=True)
        assert r.all_actions == []

    def test_default_evidence_dir_is_empty_string(self):
        r = ProtectedActionsResult(passed=False)
        assert r.evidence_dir == ""

    def test_default_notes_is_empty_string(self):
        r = ProtectedActionsResult(passed=False)
        assert r.notes == ""

    def test_explicit_construction(self):
        r = ProtectedActionsResult(
            passed=False,
            flagged_actions=["delete_record"],
            all_actions=["delete_record", "archive"],
            evidence_dir="/tmp/ev",
            notes="1 protected action(s) flagged",
        )
        assert r.passed is False
        assert r.flagged_actions == ["delete_record"]
        assert r.all_actions == ["delete_record", "archive"]
        assert r.evidence_dir == "/tmp/ev"
        assert r.notes == "1 protected action(s) flagged"

    def test_flagged_actions_default_factory_independence(self):
        """Two instances must not share the same flagged_actions list."""
        r1 = ProtectedActionsResult(passed=False)
        r2 = ProtectedActionsResult(passed=False)
        r1.flagged_actions.append("some_action")
        assert r2.flagged_actions == [], "default_factory must create independent lists"

    def test_all_actions_default_factory_independence(self):
        """Two instances must not share the same all_actions list."""
        r1 = ProtectedActionsResult(passed=True)
        r2 = ProtectedActionsResult(passed=True)
        r1.all_actions.append("action_x")
        assert r2.all_actions == [], "default_factory must create independent lists"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_audit(directory: Path, data: object) -> None:
    """Write *data* as JSON to the audit file in *directory*."""
    (directory / _AUDIT_FILE).write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# TestCheckProtectedActionsGate — filesystem scenarios
# ---------------------------------------------------------------------------


class TestCheckProtectedActionsGate:
    """Verify check_protected_actions() across all documented scenarios."""

    # ── PASS scenarios ────────────────────────────────────────────────────────

    def test_pass_all_bool_false(self, tmp_path):
        _write_audit(tmp_path, {"flag_a": False, "flag_b": False, "flag_c": False})
        result = check_protected_actions(tmp_path)
        assert result.passed is True

    def test_pass_all_false_notes_message(self, tmp_path):
        _write_audit(tmp_path, {"flag_a": False})
        result = check_protected_actions(tmp_path)
        assert result.notes == "all protected actions clear"

    def test_pass_zero_values_are_falsy(self, tmp_path):
        """Integer 0 must not be flagged (falsy check, not strict is-False)."""
        _write_audit(tmp_path, {"numeric_flag": 0, "bool_flag": False})
        result = check_protected_actions(tmp_path)
        assert result.passed is True

    def test_pass_empty_string_is_falsy(self, tmp_path):
        _write_audit(tmp_path, {"str_flag": ""})
        result = check_protected_actions(tmp_path)
        assert result.passed is True

    def test_pass_empty_list_is_falsy(self, tmp_path):
        _write_audit(tmp_path, {"list_flag": []})
        result = check_protected_actions(tmp_path)
        assert result.passed is True

    def test_pass_empty_dict_no_flags(self, tmp_path):
        """An empty JSON object has no flags — gate must pass."""
        _write_audit(tmp_path, {})
        result = check_protected_actions(tmp_path)
        assert result.passed is True

    def test_pass_empty_dict_all_actions_empty(self, tmp_path):
        _write_audit(tmp_path, {})
        result = check_protected_actions(tmp_path)
        assert result.all_actions == []

    def test_pass_flagged_actions_empty_on_pass(self, tmp_path):
        _write_audit(tmp_path, {"action_a": False, "action_b": 0})
        result = check_protected_actions(tmp_path)
        assert result.flagged_actions == []

    def test_pass_accepts_str_path(self, tmp_path):
        """check_protected_actions must accept a str, not just a Path."""
        _write_audit(tmp_path, {"f": False})
        result = check_protected_actions(str(tmp_path))
        assert result.passed is True

    def test_pass_accepts_pathlib_path(self, tmp_path):
        _write_audit(tmp_path, {"f": False})
        result = check_protected_actions(tmp_path)
        assert result.passed is True

    # ── FAIL: flagged actions ─────────────────────────────────────────────────

    def test_fail_one_true_value(self, tmp_path):
        _write_audit(tmp_path, {"dangerous_op": True})
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_one_true_in_flagged_actions(self, tmp_path):
        _write_audit(tmp_path, {"dangerous_op": True})
        result = check_protected_actions(tmp_path)
        assert "dangerous_op" in result.flagged_actions

    def test_fail_all_true_values(self, tmp_path):
        _write_audit(tmp_path, {"op_a": True, "op_b": True, "op_c": True})
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_all_true_all_in_flagged(self, tmp_path):
        data = {"op_a": True, "op_b": True, "op_c": True}
        _write_audit(tmp_path, data)
        result = check_protected_actions(tmp_path)
        assert set(result.flagged_actions) == set(data.keys())

    def test_fail_mixed_true_and_false(self, tmp_path):
        _write_audit(tmp_path, {"clean": False, "dirty": True, "also_clean": False})
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_mixed_only_dirty_in_flagged(self, tmp_path):
        _write_audit(tmp_path, {"clean": False, "dirty": True, "also_clean": False})
        result = check_protected_actions(tmp_path)
        assert result.flagged_actions == ["dirty"]

    def test_fail_truthy_non_bool_integer(self, tmp_path):
        """Non-zero integer is truthy and must be flagged."""
        _write_audit(tmp_path, {"count_flag": 1})
        result = check_protected_actions(tmp_path)
        assert result.passed is False
        assert "count_flag" in result.flagged_actions

    def test_fail_truthy_non_empty_string(self, tmp_path):
        """Non-empty string is truthy and must be flagged."""
        _write_audit(tmp_path, {"reason": "pending review"})
        result = check_protected_actions(tmp_path)
        assert result.passed is False
        assert "reason" in result.flagged_actions

    def test_fail_notes_contain_count(self, tmp_path):
        _write_audit(tmp_path, {"op_a": True, "op_b": True})
        result = check_protected_actions(tmp_path)
        assert "2" in result.notes

    def test_fail_notes_nonempty_on_fail(self, tmp_path):
        _write_audit(tmp_path, {"op": True})
        result = check_protected_actions(tmp_path)
        assert result.notes != ""

    # ── all_actions populated regardless of pass/fail ─────────────────────────

    def test_all_actions_contains_all_keys_on_pass(self, tmp_path):
        data = {"a": False, "b": False, "c": False}
        _write_audit(tmp_path, data)
        result = check_protected_actions(tmp_path)
        assert set(result.all_actions) == set(data.keys())

    def test_all_actions_contains_all_keys_on_fail(self, tmp_path):
        data = {"clean": False, "dirty": True}
        _write_audit(tmp_path, data)
        result = check_protected_actions(tmp_path)
        assert set(result.all_actions) == set(data.keys())

    def test_all_actions_count_matches_dict_keys(self, tmp_path):
        data = {"x": False, "y": True, "z": False}
        _write_audit(tmp_path, data)
        result = check_protected_actions(tmp_path)
        assert len(result.all_actions) == 3

    # ── evidence_dir field ────────────────────────────────────────────────────

    def test_evidence_dir_set_on_pass(self, tmp_path):
        _write_audit(tmp_path, {"f": False})
        result = check_protected_actions(tmp_path)
        assert result.evidence_dir == str(tmp_path)

    def test_evidence_dir_set_on_fail_missing_dir(self, tmp_path):
        nonexistent = tmp_path / "no_such_dir"
        result = check_protected_actions(nonexistent)
        assert result.evidence_dir == str(nonexistent)

    def test_evidence_dir_set_on_fail_flagged(self, tmp_path):
        _write_audit(tmp_path, {"op": True})
        result = check_protected_actions(tmp_path)
        assert result.evidence_dir == str(tmp_path)

    def test_evidence_dir_set_when_file_missing(self, tmp_path):
        result = check_protected_actions(tmp_path)
        assert result.evidence_dir == str(tmp_path)

    # ── FAIL: directory does not exist ────────────────────────────────────────

    def test_fail_directory_does_not_exist(self, tmp_path):
        nonexistent = tmp_path / "ghost_dir"
        result = check_protected_actions(nonexistent)
        assert result.passed is False

    def test_fail_directory_does_not_exist_notes(self, tmp_path):
        nonexistent = tmp_path / "ghost_dir"
        result = check_protected_actions(nonexistent)
        assert "does not exist" in result.notes

    # ── FAIL: file missing from existing directory ────────────────────────────

    def test_fail_file_missing_from_existing_dir(self, tmp_path):
        # tmp_path exists but contains no audit file
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_file_missing_notes(self, tmp_path):
        result = check_protected_actions(tmp_path)
        assert "not found" in result.notes

    # ── FAIL: invalid JSON ────────────────────────────────────────────────────

    def test_fail_invalid_json_content(self, tmp_path):
        (tmp_path / _AUDIT_FILE).write_text("not valid json {{{{", encoding="utf-8")
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_invalid_json_notes(self, tmp_path):
        (tmp_path / _AUDIT_FILE).write_text("---", encoding="utf-8")
        result = check_protected_actions(tmp_path)
        assert "invalid JSON" in result.notes

    # ── FAIL: JSON is not a dict ──────────────────────────────────────────────

    def test_fail_json_is_list(self, tmp_path):
        _write_audit(tmp_path, [1, 2, 3])
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_json_is_list_notes(self, tmp_path):
        _write_audit(tmp_path, [True, False])
        result = check_protected_actions(tmp_path)
        assert "JSON object" in result.notes

    def test_fail_json_is_string(self, tmp_path):
        (tmp_path / _AUDIT_FILE).write_text('"just a string"', encoding="utf-8")
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_json_is_string_notes(self, tmp_path):
        (tmp_path / _AUDIT_FILE).write_text('"just a string"', encoding="utf-8")
        result = check_protected_actions(tmp_path)
        assert "JSON object" in result.notes

    def test_fail_json_is_integer(self, tmp_path):
        (tmp_path / _AUDIT_FILE).write_text("42", encoding="utf-8")
        result = check_protected_actions(tmp_path)
        assert result.passed is False

    def test_fail_json_is_null(self, tmp_path):
        (tmp_path / _AUDIT_FILE).write_text("null", encoding="utf-8")
        result = check_protected_actions(tmp_path)
        assert result.passed is False
        assert "JSON object" in result.notes

    # ── never raises ─────────────────────────────────────────────────────────

    def test_never_raises_on_missing_dir(self, tmp_path):
        """check_protected_actions must not raise under any scenario."""
        nonexistent = tmp_path / "totally_absent"
        result = check_protected_actions(nonexistent)
        assert isinstance(result, ProtectedActionsResult)

    def test_never_raises_on_empty_file(self, tmp_path):
        (tmp_path / _AUDIT_FILE).write_text("", encoding="utf-8")
        result = check_protected_actions(tmp_path)
        assert isinstance(result, ProtectedActionsResult)
        assert result.passed is False


# ---------------------------------------------------------------------------
# TestProtectedActionsFileConstant
# ---------------------------------------------------------------------------


class TestProtectedActionsFileConstant:
    """Verify the module-level filename constant."""

    def test_constant_value(self):
        assert PROTECTED_ACTIONS_FILE == "protected_actions_audit.json"

    def test_constant_is_string(self):
        assert isinstance(PROTECTED_ACTIONS_FILE, str)

    def test_constant_ends_with_json(self):
        assert PROTECTED_ACTIONS_FILE.endswith(".json")
