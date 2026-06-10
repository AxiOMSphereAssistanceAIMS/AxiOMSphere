"""
Test suite for Phase 1 helper functions: has_unresolved_issues and _get_gate.

Validates audit report severity handling, gate migration, and default value fallback.
"""

from __future__ import annotations

import pytest
from ops.docgen.vertical_slice_main import has_unresolved_issues, _get_gate


class TestHasUnresolvedIssues:
    """Test suite for has_unresolved_issues() helper function."""

    def test_has_unresolved_issues_ignores_warnings(self):
        """Test that warning/info severity levels do not trigger unresolved status."""
        audit_report = {
            "approval": False,
            "severity_counts": {
                "warning": 3,
                "info": 2,
                "debug": 1,
            },
            "findings": [],
        }
        assert not has_unresolved_issues(audit_report)

    def test_has_unresolved_issues_detects_major_from_severity_counts(self):
        """Test that major/high severity in severity_counts triggers unresolved."""
        audit_report = {
            "approval": False,
            "severity_counts": {
                "major": 1,
                "warning": 2,
            },
            "findings": [],
        }
        assert has_unresolved_issues(audit_report)

    def test_has_unresolved_issues_detects_critical_from_severity_counts(self):
        """Test that critical/fatal severity in severity_counts triggers unresolved."""
        audit_report = {
            "approval": False,
            "severity_counts": {
                "critical": 1,
                "info": 5,
            },
            "findings": [],
        }
        assert has_unresolved_issues(audit_report)

    def test_has_unresolved_issues_detects_major_from_findings(self):
        """Test that major severity in findings list triggers unresolved."""
        audit_report = {
            "approval": False,
            "severity_counts": {},
            "findings": [
                {"issue": "Missing section", "severity": "major"},
                {"issue": "Typo", "severity": "info"},
            ],
        }
        assert has_unresolved_issues(audit_report)

    def test_has_unresolved_issues_detects_fail_status(self):
        """Test that 'FAIL' overall_status triggers unresolved."""
        audit_report = {
            "overall_status": "FAIL",
            "severity_counts": {},
            "findings": [],
        }
        assert has_unresolved_issues(audit_report)

    def test_has_unresolved_issues_accepts_empty_report(self):
        """Test that empty/minimal audit report without issues returns False."""
        audit_report = {
            "approval": True,
            "severity_counts": {},
            "findings": [],
        }
        assert not has_unresolved_issues(audit_report)

    def test_has_unresolved_issues_accepts_dict_with_no_findings_key(self):
        """Test graceful handling of audit report with missing 'findings' key."""
        audit_report = {
            "approval": True,
            "severity_counts": {"warning": 1},
        }
        # Should not raise; should treat missing findings as empty list
        assert not has_unresolved_issues(audit_report)

    def test_has_unresolved_issues_accepts_none_severity_counts(self):
        """Test graceful handling of None or missing severity_counts."""
        audit_report = {
            "approval": True,
            "findings": [],
        }
        # Should not raise; should treat missing severity_counts as empty dict
        assert not has_unresolved_issues(audit_report)


class TestGetGate:
    """Test suite for _get_gate() gate migration helper."""

    def test_get_gate_prefers_canonical_over_legacy(self):
        """Test that canonical gate name is preferred if both present."""
        gates = {
            "render_qa_passed": True,
            "visual_qa": False,  # Legacy name
        }
        result = _get_gate(gates, canonical="render_qa_passed", legacy="visual_qa")
        assert result is True

    def test_get_gate_uses_legacy_if_canonical_missing(self):
        """Test that legacy gate name is used if canonical not found."""
        gates = {
            "visual_qa": True,  # Only legacy present
        }
        result = _get_gate(gates, canonical="render_qa_passed", legacy="visual_qa")
        assert result is True

    def test_get_gate_uses_default_if_both_missing(self):
        """Test that default value is returned if neither canonical nor legacy found."""
        gates = {}
        result = _get_gate(gates, canonical="render_qa_passed", legacy="visual_qa", default=False)
        assert result is False

    def test_get_gate_returns_specified_default(self):
        """Test that specified default value is honored."""
        gates = {}
        result = _get_gate(gates, canonical="audit_pass", default=True)
        assert result is True

    def test_get_gate_without_legacy_still_works(self):
        """Test that _get_gate works without legacy parameter (canonical only)."""
        gates = {"audit_pass": True}
        result = _get_gate(gates, canonical="audit_pass", default=False)
        assert result is True

    def test_get_gate_returns_false_value_not_default(self):
        """Test that False canonical value is returned (not replaced by default)."""
        gates = {"render_qa_passed": False}
        result = _get_gate(gates, canonical="render_qa_passed", legacy="visual_qa", default=True)
        assert result is False

    def test_get_gate_none_value_returns_none(self):
        """Test that None value in gates dict is returned as-is (not replaced by default)."""
        gates = {"render_qa_passed": None}
        # None is explicitly set in dict, so it is returned (not replaced by default)
        result = _get_gate(gates, canonical="render_qa_passed", default=False)
        assert result is None
