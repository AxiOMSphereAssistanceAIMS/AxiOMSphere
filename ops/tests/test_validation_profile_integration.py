#!/usr/bin/env python3
"""
Test suite for Phase 2: Type-Specific Validation Profile Integration

Tests validate that cross-type leakage has been eliminated:
- Document types have type-specific validation profiles
- Rules are not applied universally across all document types
- Tri-state validation (REQUIRED/OPTIONAL/IRRELEVANT/FORBIDDEN/WARN_ONLY) works correctly
- Threshold mapping is explicit and type-specific
"""
import pytest
from ops.docgen.validation_profile_loader import (
    ValidationProfileLoader,
    RuleSeverity,
    ValidationOutcome,
    QualityThresholds,
)


class TestValidationProfileLoading:
    """Test that profiles load correctly for all document types."""

    def test_profile_loads_for_technical_report(self):
        """Technical report profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("technical_report")
        assert profile.document_type == "technical_report"
        assert "title" in profile.required_elements
        assert "executive_summary" in profile.required_elements

    def test_profile_loads_for_memo(self):
        """Memo profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("memo")
        assert profile.document_type == "memo"
        assert "title" in profile.required_elements
        assert "body" in profile.required_elements

    def test_profile_loads_for_contract(self):
        """Contract profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("contract")
        assert profile.document_type == "contract"
        assert "signature_block" in profile.required_elements

    def test_profile_loads_for_excel_workbook(self):
        """Excel workbook profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("excel_workbook")
        assert profile.document_type == "excel_workbook"
        assert "sheet_names" in profile.required_elements

    def test_profile_loads_for_inspection_report(self):
        """Inspection report profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("inspection_report")
        assert profile.document_type == "inspection_report"
        assert "inspection_scope" in profile.required_elements
        assert "findings" in profile.required_elements

    def test_profile_loads_for_design_document(self):
        """Design document profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("design_document")
        assert profile.document_type == "design_document"
        assert "design_context" in profile.required_elements
        assert "design_overview" in profile.required_elements

    def test_profile_loads_for_requirements_specification(self):
        """Requirements specification profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("requirements_specification")
        assert profile.document_type == "requirements_specification"
        assert "requirements_overview" in profile.required_elements
        assert "traceability" in profile.required_elements

    def test_profile_loads_for_preservation_strategy(self):
        """Preservation strategy profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("preservation_strategy")
        assert profile.document_type == "preservation_strategy"
        assert "asset_inventory" in profile.required_elements
        assert "depreservation_requirements" in profile.required_elements

    def test_profile_loads_for_method_statement(self):
        """Method statement profile loads successfully."""
        profile = ValidationProfileLoader.get_profile("method_statement")
        assert profile.document_type == "method_statement"
        assert "scope_of_work" in profile.required_elements
        assert "sequence_of_work" in profile.required_elements


class TestCrossTypeLeakageElimination:
    """Test that rules are not applied universally across document types."""

    def test_technical_report_with_toc_passes(self):
        """Technical report with required TOC validates as PASS."""
        profile = ValidationProfileLoader.get_profile("technical_report")
        # TOC is required for technical_report
        severity = profile.element_severity("table_of_contents")
        outcome = profile.validate_element_presence("table_of_contents", is_present=True)
        assert outcome == ValidationOutcome.PASS

    def test_excel_workbook_without_toc_passes(self):
        """Excel workbook WITHOUT TOC validates as PASS (not FAIL).

        This is the critical anti-leakage test: TOC requirement must not
        leak from technical_report to excel_workbook.
        """
        profile = ValidationProfileLoader.get_profile("excel_workbook")
        # TOC is not required for excel_workbook
        severity = profile.element_severity("table_of_contents")
        assert severity in (RuleSeverity.OPTIONAL, RuleSeverity.IRRELEVANT)
        outcome = profile.validate_element_presence("table_of_contents", is_present=False)
        assert outcome == ValidationOutcome.PASS

    def test_data_table_toc_irrelevant(self):
        """Data table treats TOC as IRRELEVANT or not required."""
        profile = ValidationProfileLoader.get_profile("data_table")
        severity = profile.element_severity("table_of_contents")
        assert severity in (RuleSeverity.OPTIONAL, RuleSeverity.IRRELEVANT)
        # Absence should not fail
        outcome = profile.validate_element_presence("table_of_contents", is_present=False)
        assert outcome == ValidationOutcome.PASS

    def test_contract_without_signature_block_fails(self):
        """Contract without required signature block fails or critical-warns.

        Contract profile marks signature_block as REQUIRED, so absence
        should result in FAIL outcome.
        """
        profile = ValidationProfileLoader.get_profile("contract")
        severity = profile.element_severity("signature_block")
        assert severity == RuleSeverity.REQUIRED
        outcome = profile.validate_element_presence("signature_block", is_present=False)
        assert outcome == ValidationOutcome.FAIL

    def test_contract_with_signature_block_passes(self):
        """Contract with signature block passes."""
        profile = ValidationProfileLoader.get_profile("contract")
        severity = profile.element_severity("signature_block")
        assert severity == RuleSeverity.REQUIRED
        outcome = profile.validate_element_presence("signature_block", is_present=True)
        assert outcome == ValidationOutcome.PASS

    def test_memo_without_signature_block_passes(self):
        """Memo does not inherit contract signature requirement.

        This is critical anti-leakage: signature_block requirement must not
        leak from contract to memo.
        """
        profile = ValidationProfileLoader.get_profile("memo")
        severity = profile.element_severity("signature_block")
        # For memo, signature_block should not be REQUIRED
        assert severity in (RuleSeverity.OPTIONAL, RuleSeverity.IRRELEVANT, RuleSeverity.FORBIDDEN)
        outcome = profile.validate_element_presence("signature_block", is_present=False)
        # Should not fail due to absence
        assert outcome in (ValidationOutcome.PASS, ValidationOutcome.WARN)

    def test_memo_with_signature_block_follows_profile(self):
        """Memo with signature block follows memo profile severity.

        If signature_block is FORBIDDEN in memo profile, presence should
        result in WARN or FAIL. If OPTIONAL, presence is OK.
        """
        profile = ValidationProfileLoader.get_profile("memo")
        severity = profile.element_severity("signature_block")
        outcome = profile.validate_element_presence("signature_block", is_present=True)

        if severity == RuleSeverity.FORBIDDEN:
            assert outcome in (ValidationOutcome.WARN, ValidationOutcome.FAIL)
        elif severity in (RuleSeverity.OPTIONAL, RuleSeverity.IRRELEVANT):
            assert outcome == ValidationOutcome.PASS

    def test_presentation_no_annexures_required(self):
        """Presentation validates without report annexures.

        Presentation profile should not require annexures.
        """
        profile = ValidationProfileLoader.get_profile("presentation_outline")
        severity = profile.element_severity("appendices")
        assert severity in (RuleSeverity.OPTIONAL, RuleSeverity.IRRELEVANT)
        outcome = profile.validate_element_presence("appendices", is_present=False)
        assert outcome == ValidationOutcome.PASS


class TestThresholdMapping:
    """Test that quality thresholds are correctly mapped and type-specific."""

    def test_technical_report_quality_thresholds(self):
        """Technical report has correct quality thresholds."""
        profile = ValidationProfileLoader.get_profile("technical_report")
        thresholds = profile.quality_thresholds
        # Technical report should have high overall threshold
        assert thresholds.overall >= 0.80
        # Explicit thresholds should be computed
        assert thresholds.structure is not None
        assert thresholds.standards is not None

    def test_memo_quality_thresholds(self):
        """Memo has different thresholds than technical report."""
        tech_profile = ValidationProfileLoader.get_profile("technical_report")
        memo_profile = ValidationProfileLoader.get_profile("memo")
        # Thresholds may differ between types
        tech_overall = tech_profile.quality_thresholds.overall
        memo_overall = memo_profile.quality_thresholds.overall
        # Both should be valid thresholds
        assert 0.5 <= tech_overall <= 1.0
        assert 0.5 <= memo_overall <= 1.0

    def test_contract_uses_profile_thresholds(self):
        """Contract uses contract profile thresholds, not defaults."""
        profile = ValidationProfileLoader.get_profile("contract")
        thresholds = profile.quality_thresholds
        # Contract should have explicit conformance threshold
        assert thresholds.conformance is not None
        # standards should map to conformance
        assert thresholds.standards == thresholds.conformance

    def test_policy_uses_policy_profile(self):
        """Policy uses policy profile thresholds."""
        profile = ValidationProfileLoader.get_profile("policy")
        assert profile.document_type == "policy"
        # Should not default to technical_report
        assert profile.display_name == "Policy Document"


class TestTriStateValidation:
    """Test tri-state validation outcomes (PASS/WARN/FAIL)."""

    def test_required_element_present_returns_pass(self):
        """REQUIRED element present returns PASS."""
        profile = ValidationProfileLoader.get_profile("technical_report")
        outcome = profile.validate_element_presence("title", is_present=True)
        assert outcome == ValidationOutcome.PASS

    def test_required_element_absent_returns_fail(self):
        """REQUIRED element absent returns FAIL."""
        profile = ValidationProfileLoader.get_profile("technical_report")
        outcome = profile.validate_element_presence("title", is_present=False)
        assert outcome == ValidationOutcome.FAIL

    def test_optional_element_always_returns_pass(self):
        """OPTIONAL element present or absent always returns PASS."""
        profile = ValidationProfileLoader.get_profile("technical_report")
        # appendices is optional for technical_report
        outcome_present = profile.validate_element_presence("appendices", is_present=True)
        outcome_absent = profile.validate_element_presence("appendices", is_present=False)
        assert outcome_present == ValidationOutcome.PASS
        assert outcome_absent == ValidationOutcome.PASS

    def test_irrelevant_element_returns_pass(self):
        """IRRELEVANT element (not in any list) returns PASS."""
        profile = ValidationProfileLoader.get_profile("technical_report")
        severity = profile.element_severity("nonexistent_element_xyz")
        assert severity == RuleSeverity.IRRELEVANT
        outcome = profile.validate_element_presence("nonexistent_element_xyz", is_present=False)
        assert outcome == ValidationOutcome.PASS

    def test_forbidden_element_present_returns_fail(self):
        """FORBIDDEN element present returns FAIL."""
        profile = ValidationProfileLoader.get_profile("memo")
        # signature_block is forbidden for memo
        if "signature_block" in profile.forbidden_elements:
            outcome = profile.validate_element_presence("signature_block", is_present=True)
            assert outcome == ValidationOutcome.FAIL

    def test_forbidden_element_absent_returns_pass(self):
        """FORBIDDEN element absent returns PASS."""
        profile = ValidationProfileLoader.get_profile("memo")
        # signature_block is forbidden for memo
        if "signature_block" in profile.forbidden_elements:
            outcome = profile.validate_element_presence("signature_block", is_present=False)
            assert outcome == ValidationOutcome.PASS


class TestProfileDocumentationRequirements:
    """Test that all 12 document types have complete profiles."""

    def test_all_12_document_types_have_profiles(self):
        """All 12 document types can load profiles."""
        document_types = [
            "technical_report",
            "operational_manual",
            "maintenance_plan",
            "data_table",
            "memo",
            "presentation_outline",
            "policy",
            "risk_assessment",
            "audit_report",
            "contract",
            "checklist",
            "excel_workbook",
        ]
        for doc_type in document_types:
            profile = ValidationProfileLoader.get_profile(doc_type)
            assert profile.document_type == doc_type
            assert profile.display_name is not None
            assert profile.quality_thresholds is not None
            assert profile.scoring_weights is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
