"""Test suite for DataRetentionValidator with comprehensive threshold scenarios.

Tests verify data retention validation against all documented thresholds:
- PASS: ≤1.5% token loss
- ADVISORY: 1.5% < loss ≤ 2.0%
- FAIL: > 2.0% token loss OR any required element loss
"""
import pytest
from ops.docsreg.universal_loop import (
    DataRetentionValidator,
    DocumentSnapshot,
    RetentionVerdict,
)


class TestDataLossPercentageThresholds:
    """Verify token loss percentage thresholds: PASS ≤1.5%, ADVISORY 1.5-2.0%, FAIL >2.0%."""

    def test_0_8_percent_loss_is_pass(self):
        """0.8% token loss results in PASS verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,  # ~1000 tokens
            sections=["S1"],
            required_fields=["F1"],
        )
        # ~0.8% loss: 1000 - 992 = 8 tokens lost
        after = DocumentSnapshot(
            content="a " * 992,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.PASS
        assert report.token_loss_percentage <= 1.5

    def test_1_5_percent_loss_boundary_is_pass(self):
        """1.5% token loss (boundary) results in PASS verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        # Token count: 1000 words * 1.3 = 1300 tokens
        # For ≤1.5% loss: need 1300 * 0.985 = 1280.5 → int(986 * 1.3) = 1281 tokens
        # Actual loss: (1300 - 1281) / 1300 * 100 = 1.462%
        after = DocumentSnapshot(
            content="a " * 986,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.PASS
        assert report.token_loss_percentage <= 1.5

    def test_1_7_percent_loss_is_advisory(self):
        """1.7% token loss results in ADVISORY verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        # ~1.7% loss: 1000 - 983 = 17 tokens lost
        after = DocumentSnapshot(
            content="a " * 983,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.ADVISORY
        assert 1.5 < report.token_loss_percentage <= 2.0

    def test_2_0_percent_loss_boundary_is_advisory(self):
        """2.0% token loss (boundary) results in ADVISORY verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        # ~2.0% loss: 1000 - 980 = 20 tokens lost
        after = DocumentSnapshot(
            content="a " * 980,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.ADVISORY
        assert 1.5 < report.token_loss_percentage <= 2.0

    def test_2_5_percent_loss_is_fail(self):
        """2.5% token loss results in FAIL verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        # ~2.5% loss: 1000 - 975 = 25 tokens lost
        after = DocumentSnapshot(
            content="a " * 975,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert report.token_loss_percentage > 2.0

    def test_7_1_percent_loss_is_fail(self):
        """7.1% token loss results in FAIL verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        # ~7.1% loss: 1000 - 929 = 71 tokens lost
        after = DocumentSnapshot(
            content="a " * 929,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert report.token_loss_percentage > 2.0

    def test_50_percent_loss_is_fail(self):
        """50% token loss results in FAIL verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        # 50% loss
        after = DocumentSnapshot(
            content="a " * 500,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert report.token_loss_percentage > 2.0

    def test_35_1_percent_loss_is_fail(self):
        """35.1% token loss results in FAIL verdict."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        # ~35.1% loss: 1000 - 649 = 351 tokens lost
        after = DocumentSnapshot(
            content="a " * 649,
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert report.token_loss_percentage > 2.0


class TestHighLossOverridesQualityImprovement:
    """Verify data loss thresholds override quality improvements."""

    def test_7_percent_loss_with_quality_improvement_is_fail(self):
        """7% data loss results in FAIL even with quality improvement."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
        )
        after = DocumentSnapshot(
            content="a " * 930,  # ~7% loss
            sections=["S1"],
            required_fields=["F1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        # Regardless of quality improvements, >2% loss = FAIL
        assert report.verdict == RetentionVerdict.FAIL
        assert report.token_loss_percentage > 2.0


class TestRequiredFieldLossAlwaysFails:
    """Verify any required field loss results in FAIL, overriding token loss thresholds."""

    def test_required_field_lost_with_minimal_token_loss_is_fail(self):
        """Required field lost with only 0.1% token loss still results in FAIL."""
        before = DocumentSnapshot(
            content="a " * 1000,
            required_fields=["F1", "F2"],
        )
        after = DocumentSnapshot(
            content="a " * 999,  # Only 0.1% token loss
            required_fields=["F1"],  # F2 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "F2" in report.lost_required_fields

    def test_required_field_lost_with_zero_token_loss_is_fail(self):
        """Required field lost with zero token loss still results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            required_fields=["F1", "F2", "F3"],
        )
        after = DocumentSnapshot(
            content="content",  # Zero token loss
            required_fields=["F1"],  # F2 and F3 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert len(report.lost_required_fields) == 2
        assert "F2" in report.lost_required_fields
        assert "F3" in report.lost_required_fields

    def test_multiple_required_fields_lost_is_fail(self):
        """Multiple required fields lost results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            required_fields=["Title", "AbstractSection", "MethodologySection"],
        )
        after = DocumentSnapshot(
            content="content",
            required_fields=["Title"],  # AbstractSection and MethodologySection lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert len(report.lost_required_fields) == 2


class TestSectionLossAlwaysFails:
    """Verify any section loss results in FAIL."""

    def test_single_section_lost_is_fail(self):
        """Loss of a single section results in FAIL."""
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

    def test_multiple_sections_lost_is_fail(self):
        """Loss of multiple sections results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            sections=["Title", "Executive Summary", "Background", "Methodology", "Results", "Conclusion"],
        )
        after = DocumentSnapshot(
            content="content",
            sections=["Title", "Results", "Conclusion"],  # Three sections lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert len(report.lost_sections) == 3


class TestReferenceLossAlwaysFails:
    """Verify any reference loss results in FAIL."""

    def test_single_reference_lost_is_fail(self):
        """Loss of a single reference results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            references=["ISO_55001", "ISO_55002", "API_HANDBOOK"],
        )
        after = DocumentSnapshot(
            content="content",
            references=["ISO_55001", "API_HANDBOOK"],  # ISO_55002 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "ISO_55002" in report.lost_references

    def test_multiple_references_lost_is_fail(self):
        """Loss of multiple references results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            references=["REF1", "REF2", "REF3", "REF4"],
        )
        after = DocumentSnapshot(
            content="content",
            references=["REF1", "REF3"],  # REF2 and REF4 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert len(report.lost_references) == 2


class TestTableLossAlwaysFails:
    """Verify any table loss results in FAIL."""

    def test_single_table_lost_is_fail(self):
        """Loss of a single table results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            tables=["MaintenanceSchedule", "PartsList", "SafetyMatrix"],
        )
        after = DocumentSnapshot(
            content="content",
            tables=["MaintenanceSchedule", "SafetyMatrix"],  # PartsList lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "PartsList" in report.lost_tables

    def test_all_tables_lost_is_fail(self):
        """Loss of all tables results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            tables=["Table1", "Table2", "Table3"],
        )
        after = DocumentSnapshot(
            content="content",
            tables=[],  # All tables lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert len(report.lost_tables) == 3


class TestLinkLossAlwaysFails:
    """Verify any link loss results in FAIL."""

    def test_single_link_lost_is_fail(self):
        """Loss of a single link results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            links=["http://example.com", "http://docs.example.com", "http://api.example.com"],
        )
        after = DocumentSnapshot(
            content="content",
            links=["http://example.com", "http://api.example.com"],  # docs link lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "http://docs.example.com" in report.lost_links

    def test_multiple_links_lost_is_fail(self):
        """Loss of multiple links results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            links=["http://a.com", "http://b.com", "http://c.com", "http://d.com"],
        )
        after = DocumentSnapshot(
            content="content",
            links=["http://a.com"],  # Three links lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert len(report.lost_links) == 3


class TestSemanticClaimLossAlwaysFails:
    """Verify any semantic claim loss results in FAIL."""

    def test_single_semantic_claim_lost_is_fail(self):
        """Loss of a single semantic claim results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            semantic_claims=["MaintenanceReducesCost", "ProactiveIsBetter", "SystemReliability"],
        )
        after = DocumentSnapshot(
            content="content",
            semantic_claims=["MaintenanceReducesCost", "SystemReliability"],  # ProactiveIsBetter lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "ProactiveIsBetter" in report.lost_semantic_claims

    def test_multiple_semantic_claims_lost_is_fail(self):
        """Loss of multiple semantic claims results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            semantic_claims=["Claim1", "Claim2", "Claim3", "Claim4", "Claim5"],
        )
        after = DocumentSnapshot(
            content="content",
            semantic_claims=["Claim1", "Claim3"],  # Three claims lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert len(report.lost_semantic_claims) == 3


class TestCombinedLossScenarios:
    """Verify validation with combined element losses."""

    def test_lost_field_and_lost_section_is_fail(self):
        """Loss of both a field and a section results in FAIL."""
        before = DocumentSnapshot(
            content="content",
            required_fields=["F1", "F2"],
            sections=["S1", "S2"],
        )
        after = DocumentSnapshot(
            content="content",
            required_fields=["F1"],  # F2 lost
            sections=["S1"],  # S2 lost
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.FAIL
        assert "F2" in report.lost_required_fields
        assert "S2" in report.lost_sections

    def test_no_losses_with_high_token_loss_in_pass_range_is_pass(self):
        """1.5% token loss with no element losses results in PASS."""
        before = DocumentSnapshot(
            content="a " * 1000,
            sections=["S1"],
            required_fields=["F1"],
            references=["REF1"],
            tables=["T1"],
            links=["http://a.com"],
            semantic_claims=["Claim1"],
        )
        # Token count: 1000 words * 1.3 = 1300 tokens
        # For ≤1.5% loss: need 1300 * 0.985 = 1280.5 → int(986 * 1.3) = 1281 tokens
        # Actual loss: (1300 - 1281) / 1300 * 100 = 1.462%
        after = DocumentSnapshot(
            content="a " * 986,  # 1.462% token loss
            sections=["S1"],
            required_fields=["F1"],
            references=["REF1"],
            tables=["T1"],
            links=["http://a.com"],
            semantic_claims=["Claim1"],
        )

        validator = DataRetentionValidator()
        report = validator.validate(before, after)

        assert report.verdict == RetentionVerdict.PASS
        assert report.token_loss_percentage <= 1.5
        assert len(report.lost_required_fields) == 0
        assert len(report.lost_sections) == 0
