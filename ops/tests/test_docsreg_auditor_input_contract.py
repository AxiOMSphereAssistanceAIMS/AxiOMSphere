"""
Test suite for DOCSREG Auditor Input Contract Validation (F10).

Tests the validate_manifest_for_auditor() and rejection_result() functions
to ensure proper fail-closed behavior and logging at contract boundaries.
"""

import logging
import pytest

from ops.docsreg.docsreg_auditor_input_contract import (
    validate_manifest_for_auditor,
    rejection_result,
    MIN_DOCUMENT_TEXT_LEN,
)


# Test Class 1: Empty/Missing document_text
class TestRejectEmptyManifest:
    """Test rejection of manifests with missing or empty document_text."""

    def test_reject_manifest_with_document_text_len_zero(self):
        """Reject manifest where document_text is empty string."""
        manifest = {"document_text": ""}
        is_valid, reason = validate_manifest_for_auditor(manifest, "API")

        assert not is_valid, "Should reject empty document_text"
        assert "document_text_len=0" in reason
        assert reason

    def test_reject_manifest_with_missing_document_text_key(self):
        """Reject manifest where document_text key is absent."""
        manifest = {"other_field": "value"}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ISO")

        assert not is_valid, "Should reject missing document_text key"
        assert "document_text_len=0" in reason

    def test_reject_manifest_where_document_text_is_none(self):
        """Reject manifest where document_text is None (not string)."""
        manifest = {"document_text": None}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ASME")

        assert not is_valid, "Should reject non-string document_text"
        assert "must be str" in reason


# Test Class 2: Below-Threshold Length
class TestRejectBelowThreshold:
    """Test rejection of manifests with document_text below 1200 char threshold."""

    def test_reject_manifest_with_document_text_len_100(self):
        """Reject manifest with 100 characters (well below threshold)."""
        manifest = {"document_text": "x" * 100}
        is_valid, reason = validate_manifest_for_auditor(manifest, "DNV")

        assert not is_valid, "Should reject 100-char document"
        assert "document_text_len=100" in reason
        assert f"< {MIN_DOCUMENT_TEXT_LEN}" in reason

    def test_reject_manifest_with_document_text_len_500(self):
        """Reject manifest with 500 characters (below threshold)."""
        manifest = {"document_text": "y" * 500}
        is_valid, reason = validate_manifest_for_auditor(manifest, "API")

        assert not is_valid, "Should reject 500-char document"
        assert "document_text_len=500" in reason

    def test_reject_manifest_with_document_text_len_999(self):
        """Reject manifest with 999 characters (just below 1200 threshold)."""
        manifest = {"document_text": "z" * 999}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ISO")

        assert not is_valid, "Should reject 999-char document (just below threshold)"
        assert "document_text_len=999" in reason
        assert f"< {MIN_DOCUMENT_TEXT_LEN}" in reason


# Test Class 3: At/Above Threshold
class TestAcceptAtAndAboveThreshold:
    """Test acceptance of manifests at or above 1200 char threshold."""

    def test_accept_manifest_with_document_text_len_1200(self):
        """Accept manifest with exactly 1200 characters (at threshold)."""
        manifest = {"document_text": "a" * MIN_DOCUMENT_TEXT_LEN}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ASME")

        assert is_valid, "Should accept exactly 1200-char document"
        assert reason == "", f"Should have empty reason string, got: {reason}"

    def test_accept_manifest_with_document_text_len_2000(self):
        """Accept manifest with 2000 characters (well above threshold)."""
        manifest = {"document_text": "b" * 2000}
        is_valid, reason = validate_manifest_for_auditor(manifest, "DNV")

        assert is_valid, "Should accept 2000-char document"
        assert reason == ""

    def test_accept_manifest_with_realistic_content(self):
        """Accept manifest with realistic industrial document content."""
        realistic_doc = """
ISO 55001:2014 Preventive Maintenance Procedure
================================================

Objective: Establish systematic preventive maintenance schedules for Class A-500
centrifugal pumps to ensure operational reliability and safety compliance.

Scope: This procedure applies to all rotating equipment in the production facility,
including centrifugal pumps, motors, gearboxes, and compressors rated above 50 HP.

Maintenance Schedule:
- Daily: Visual inspection, noise/vibration monitoring, temperature check
- Monthly: Seal integrity check, bearing temperature trend analysis
- Quarterly: Fluid analysis, mechanical seal replacement if needed
- Annual: Full disassembly, bearing replacement, and certification test

Failure Response:
1. If vibration exceeds 0.28 inches/second peak:
   - Isolate equipment
   - Perform diagnostic inspection
   - Replace bearing if needed
   - Run balance test before returning to service

Spare Parts Inventory:
- Mechanical seals (ASTM B117 stainless): 8-week lead time
- Precision bearings (FAG 6309-2Z): maintain 3-unit stock
- Coupling elements: $4,200 per replacement
- Thermal compound: specialized heat transfer medium

Technical Specifications:
- Minimum pressure rating: 300 psi
- Maximum operating temperature: 185°F
- Motor torque: 1,250 ft-lbs at 1,200 RPM
- Shaft vibration limit: ± 0.15 mils at 3000 RPM
- Required training: Pump Maintenance Certification (Level II)

This document requires annual review by the Maintenance Engineering Committee.
Revision 3.2 | Issued 2026-06-01 | Next review: 2027-06-01
        """
        manifest = {"document_text": realistic_doc}
        is_valid, reason = validate_manifest_for_auditor(manifest, "API")

        assert is_valid, "Should accept realistic industrial document"
        assert reason == ""


# Test Class 4: Type Validation
class TestRejectInvalidTypes:
    """Test rejection of manifests with invalid field types."""

    def test_reject_manifest_when_document_text_is_list(self):
        """Reject manifest where document_text is a list (not string)."""
        manifest = {"document_text": ["item1", "item2"]}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ISO")

        assert not is_valid, "Should reject list document_text"
        assert "must be str" in reason
        assert "list" in reason

    def test_reject_manifest_when_document_text_is_int(self):
        """Reject manifest where document_text is an int."""
        manifest = {"document_text": 12345}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ASME")

        assert not is_valid, "Should reject int document_text"
        assert "must be str" in reason

    def test_reject_manifest_when_document_text_is_dict(self):
        """Reject manifest where document_text is a dict."""
        manifest = {"document_text": {"nested": "value"}}
        is_valid, reason = validate_manifest_for_auditor(manifest, "DNV")

        assert not is_valid, "Should reject dict document_text"
        assert "must be str" in reason

    def test_reject_when_manifest_itself_not_dict(self):
        """Reject when manifest parameter itself is not a dict."""
        manifest = "not a dict"
        is_valid, reason = validate_manifest_for_auditor(manifest, "API")

        assert not is_valid, "Should reject non-dict manifest"
        assert "manifest must be dict" in reason


# Test Class 5: rejection_result() Function
class TestRejectionResultFunction:
    """Test the rejection_result() factory function."""

    def test_rejection_result_returns_correct_structure(self):
        """Verify rejection_result returns expected auditor result format."""
        reason = "test rejection reason"
        result = rejection_result(reason)

        assert isinstance(result, dict)
        assert "status" in result
        assert "quality" in result
        assert "notes" in result
        assert "error" in result

    def test_rejection_result_sets_status_to_component_blocked(self):
        """Verify status field is set to COMPONENT_BLOCKED."""
        result = rejection_result("any reason")
        assert result["status"] == "COMPONENT_BLOCKED"

    def test_rejection_result_sets_quality_to_zero(self):
        """Verify quality field is set to 0.0."""
        result = rejection_result("any reason")
        assert result["quality"] == 0.0
        assert isinstance(result["quality"], float)

    def test_rejection_result_includes_reason_in_notes(self):
        """Verify rejection reason is included in notes field."""
        reason = "document_text too short"
        result = rejection_result(reason)

        assert "notes" in result
        assert reason in result["notes"]
        assert "input_contract_rejection:" in result["notes"]

    def test_rejection_result_sets_error_to_none(self):
        """Verify error field is None."""
        result = rejection_result("any reason")
        assert result["error"] is None

    def test_rejection_result_with_empty_reason(self):
        """Handle rejection with empty reason string."""
        result = rejection_result("")
        assert result["status"] == "COMPONENT_BLOCKED"
        assert result["quality"] == 0.0
        assert "input_contract_rejection:" in result["notes"]


# Test Class 6: Logging Behavior
class TestLoggingBehavior:
    """Test that validation function logs appropriately."""

    def test_validation_logs_on_rejection(self, caplog):
        """Verify rejection is logged with document_type."""
        manifest = {"document_text": "too short"}
        with caplog.at_level(logging.WARNING):
            validate_manifest_for_auditor(manifest, "API")

        # Check that warning was logged
        assert any("validate_manifest_for_auditor" in record.message for record in caplog.records)
        assert any("API" in record.message for record in caplog.records)

    def test_validation_logs_on_acceptance(self, caplog):
        """Verify acceptance is logged at debug level."""
        manifest = {"document_text": "x" * 2000}
        with caplog.at_level(logging.DEBUG):
            validate_manifest_for_auditor(manifest, "ISO")

        # Check that debug message was logged with PASS indicator
        assert any("PASS" in record.message for record in caplog.records)
        assert any("2000" in record.message for record in caplog.records)


# Test Class 7: Edge Cases
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_accept_manifest_with_1201_characters(self):
        """Accept manifest with 1201 characters (just above threshold)."""
        manifest = {"document_text": "x" * 1201}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ASME")

        assert is_valid, "Should accept 1201-char document (just above threshold)"
        assert reason == ""

    def test_manifest_with_extra_keys_still_validates(self):
        """Accept manifest with extra fields beyond document_text."""
        manifest = {
            "document_text": "y" * 1500,
            "document_type": "ISO",
            "metadata": "extra",
            "version": 1,
        }
        is_valid, reason = validate_manifest_for_auditor(manifest, "ISO")

        assert is_valid, "Should accept manifest with extra fields"
        assert reason == ""

    def test_document_text_with_whitespace_only(self):
        """Test manifest where document_text is only whitespace."""
        manifest = {"document_text": " " * 1500}  # All spaces, but > 1200 len
        is_valid, reason = validate_manifest_for_auditor(manifest, "DNV")

        # Should reject: whitespace-only fails contract check at line 58 (if not doc_text.strip())
        assert not is_valid, "Should reject whitespace-only document (no substantive content)"

    def test_document_text_with_newlines_count_as_length(self):
        """Verify newlines count toward character length."""
        doc = "line1\n" * 150  # 6 chars * 150 = 900, but we need 1200+
        if len(doc) < MIN_DOCUMENT_TEXT_LEN:
            doc = "line\n" * 250  # Adjust to exceed threshold
        manifest = {"document_text": doc}
        is_valid, reason = validate_manifest_for_auditor(manifest, "API")

        # Should pass if we constructed doc to be >= 1200
        if len(doc) >= MIN_DOCUMENT_TEXT_LEN:
            assert is_valid


# Test Class 8: Integration with Fixture Samples
class TestIntegrationWithFixtures:
    """Test validation against realistic fixture samples."""

    def test_validate_fixture_procedure_sample(self):
        """Validate a fixture-like procedure document (3,339 chars)."""
        procedure_doc = (
            "ISO 55001:2014 Preventive Maintenance Procedure\n"
            + "=" * 50 + "\n"
            + "Description of maintenance procedure for centrifugal pumps.\n"
            + "Daily checks, monthly inspections, quarterly deep maintenance.\n"
            + "Includes torque specifications (1250 ft-lbs), temperature limits (185°F).\n"
            + "Training requirement: Pump Maintenance Certification Level II.\n"
            + "Spare parts: mechanical seals, precision bearings, coupling elements.\n"
        ) * 40  # Repeat to ensure > 1200 chars

        manifest = {"document_text": procedure_doc}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ISO")

        assert is_valid, "Should accept fixture-like procedure sample"

    def test_validate_fixture_policy_sample(self):
        """Validate a fixture-like policy document."""
        policy_doc = (
            "Organizational Asset Integrity Policy\n"
            + "Core Principles: risk-based management, RCM, data-driven improvement\n"
            + "Governance Tiers: Strategic (Executive), Tactical (Managers), Operational\n"
            + "Performance Targets: Uptime ≥99.5%, MTBF 40,000 hours, Maintenance Cost <5%\n"
            + "Resource Commitment: 2.5 FTE for maintenance, $500K annual budget\n"
        ) * 50  # Repeat to ensure > 1200 chars

        manifest = {"document_text": policy_doc}
        is_valid, reason = validate_manifest_for_auditor(manifest, "ASME")

        assert is_valid, "Should accept fixture-like policy sample"
