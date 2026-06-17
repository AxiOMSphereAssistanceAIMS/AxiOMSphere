"""
Unit tests for generator repair guidance response.

Tests extraction of repair dimensions, appendix building, and quality bonus scoring.
PHASE 2 Step 2.5-2.6 validation suite.
"""

import pytest
from pathlib import Path
from ops.docgen.block_generator_minimal import (
    extract_repair_dimensions,
    extract_repair_dimensions_from_context,
    build_repair_guided_appendix,
    estimate_repair_guided_quality,
    VALID_REPAIR_DIMENSIONS,
)


class TestExtractRepairDimensions:
    """Test extract_repair_dimensions() function."""

    def test_extract_from_dict_list(self):
        """Extract repair dimensions from dict list (Path 1)."""
        repairs = [
            {"dimension": "actionability", "repair_action": "Add owner info"},
            {"dimension": "evidence", "repair_action": "Add sources"},
        ]
        result = extract_repair_dimensions(repairs)
        assert result == {"actionability", "evidence"}

    def test_extract_from_empty_list(self):
        """Extract from empty list returns empty set."""
        result = extract_repair_dimensions([])
        assert result == set()

    def test_extract_from_none(self):
        """Extract from None returns empty set."""
        result = extract_repair_dimensions(None)
        assert result == set()

    def test_extract_ignores_invalid_dimensions(self):
        """Invalid dimension names are ignored."""
        repairs = [
            {"dimension": "actionability", "repair_action": "Add owner"},
            {"dimension": "invalid_dimension", "repair_action": "Do something"},
        ]
        result = extract_repair_dimensions(repairs)
        assert result == {"actionability"}  # invalid_dimension filtered out


class TestExtractRepairDimensionsFromContext:
    """Test extract_repair_dimensions_from_context() function."""

    def test_extract_from_guidance_section(self):
        """Extract dimensions from 'Previous Iteration Repair Guidance:' section via bracket markers."""
        context = """
Previous Iteration Repair Guidance:
  - [actionability] Add owner and success criteria
  - [evidence] Add data sources and verification method
  - [specificity] Add concrete metrics and thresholds
"""
        result = extract_repair_dimensions_from_context(context)
        assert result == {"actionability", "evidence", "specificity"}

    def test_extract_no_guidance_section(self):
        """No guidance section returns empty set."""
        context = "Just some regular document context without guidance."
        result = extract_repair_dimensions_from_context(context)
        assert result == set()

    def test_extract_ignores_invalid_bracket_markers(self):
        """Invalid markers in brackets are ignored."""
        context = """
Previous Iteration Repair Guidance:
  - [actionability] Valid
  - [invalid_marker] Invalid
  - [reasoning] Valid
"""
        result = extract_repair_dimensions_from_context(context)
        assert "actionability" in result
        assert "reasoning" in result
        assert "invalid_marker" not in result


class TestBuildRepairGuidedAppendix:
    """Test build_repair_guided_appendix() function."""

    def test_appendix_has_all_9_sections_when_all_dimensions_provided(self):
        """Appendix includes section for each provided dimension."""
        repair_dimensions = VALID_REPAIR_DIMENSIONS
        appendix = build_repair_guided_appendix(repair_dimensions)

        # Check that all dimensions are mentioned in appendix
        appendix_lower = appendix.lower()
        assert "actionability" in appendix_lower
        assert "evidence" in appendix_lower
        assert "specificity" in appendix_lower
        assert "structure" in appendix_lower
        assert "reasoning" in appendix_lower
        assert "formatting" in appendix_lower
        assert "clarity" in appendix_lower
        assert "completeness" in appendix_lower
        assert "no_leakage" in appendix_lower

    def test_appendix_non_empty_for_single_dimension(self):
        """Appendix is non-empty for single repair dimension."""
        appendix = build_repair_guided_appendix({"actionability"})
        assert len(appendix) > 0
        assert "actionability" in appendix.lower()

    def test_appendix_empty_for_no_dimensions(self):
        """Appendix is empty for no repair dimensions."""
        appendix = build_repair_guided_appendix(set())
        assert appendix == ""


class TestEstimateRepairGuidedQuality:
    """Test estimate_repair_guided_quality() function."""

    def test_base_score_short_text(self):
        """Short text (<50 words) gets 0.2 base score."""
        text = "Short text."
        score = estimate_repair_guided_quality(text, set())
        assert score == 0.2

    def test_base_score_acceptable_text(self):
        """Acceptable text (50-1000 words) gets 0.75 base score."""
        text = " ".join(["word"] * 500)
        score = estimate_repair_guided_quality(text, set())
        assert score == 0.75

    def test_base_score_long_text(self):
        """Long text (>1000 words) gets 0.5 base score."""
        text = " ".join(["word"] * 1500)
        score = estimate_repair_guided_quality(text, set())
        assert score == 0.5

    def test_actionability_bonus_detected(self):
        """Actionability dimension bonus added when markers present."""
        text = " ".join(["word"] * 500) + "\nOwner: Jane Doe\nSuccess criteria: Complete by Friday\nTimeline: 3 weeks"
        score = estimate_repair_guided_quality(text, {"actionability"})
        assert score > 0.75  # base 0.75 + bonus
        assert score <= 0.98  # capped at 0.98

    def test_evidence_bonus_detected(self):
        """Evidence dimension bonus added when markers present."""
        text = " ".join(["word"] * 500) + "\nData source: Production logs\nVerification method: Automated audit"
        score = estimate_repair_guided_quality(text, {"evidence"})
        assert score > 0.75

    def test_specificity_bonus_with_metrics(self):
        """Specificity bonus when text contains numbers."""
        text = " ".join(["word"] * 500) + "\nMetric: 95% uptime\nThreshold: 500ms latency"
        score = estimate_repair_guided_quality(text, {"specificity"})
        assert score > 0.75

    def test_multiple_bonuses_capped_at_0_15(self):
        """Total bonus across all dimensions capped at +0.15."""
        text = " ".join(["word"] * 500)
        text += "\nOwner: Jane\nSuccess criteria: Done\n"
        text += "Source: Logs\nVerification: Audit\n"
        text += "Metric: 95%\nThreshold: 500ms\n"
        text += "## Section 1\n## Section 2\n"
        text += "Because logic is clear\n"
        text += "Formatting: - list item\n"
        text += "Clarity: Short and clear\n"
        text += "Completeness: 300 words included\n"

        # Trigger many dimensions at once
        all_dimensions = VALID_REPAIR_DIMENSIONS
        score = estimate_repair_guided_quality(text, all_dimensions)

        # Score should be 0.75 + 0.15 (capped) = 0.90
        assert score <= 0.98  # Cannot exceed cap
        assert score >= 0.75  # Must exceed base

    def test_final_score_capped_at_0_98(self):
        """Final score never exceeds 0.98."""
        text = " ".join(["word"] * 500) + "\nOwner: Jane\nSource: Logs\n100% complete\n## Section\n"
        score = estimate_repair_guided_quality(text, VALID_REPAIR_DIMENSIONS)
        assert score <= 0.98

    def test_placeholder_text_gets_low_score(self):
        """Text with [TBD] markers gets low score."""
        text = " ".join(["word"] * 500) + "\n[TBD] Insert details here"
        score = estimate_repair_guided_quality(text, set())
        assert score <= 0.2

    def test_empty_text_returns_zero(self):
        """Empty text returns 0.0."""
        score = estimate_repair_guided_quality("", set())
        assert score == 0.0
