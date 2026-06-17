"""
Integration tests for DOCGEN Phase B.5 repair feedback response.

Tests that generator responds to previous iteration repair recommendations
by incorporating repair-guided content and improving quality scores.
PHASE 2 Step 2.6 validation suite.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from ops.docgen.block_generator_minimal import (
    DocumentBlock,
    BlockGeneratorMinimal,
    extract_repair_dimensions,
    extract_repair_dimensions_from_context,
    build_repair_guided_appendix,
    estimate_repair_guided_quality,
)


class TestGeneratorRespondsToRepairGuidance:
    """Test that generator incorporates repair guidance into content."""

    def test_generator_appends_repair_appendix_when_guidance_present(self):
        """Generator appends repair-guided appendix when repair dimensions detected."""
        # Simulate block with repair guidance in context
        block = DocumentBlock(
            block_id="test_block_001",
            block_type="section",
            document_type="technical_report",
            content_requirements="main content",
        )

        # Create mock generator context with repair guidance
        document_context = """
        Previous Iteration Repair Guidance:
          - [actionability] Add owner and success criteria
          - [evidence] Add data sources
          - [specificity] Add concrete metrics
        """

        # Extract repair dimensions from context
        repair_dimensions = extract_repair_dimensions_from_context(document_context)

        # Verify extraction succeeded
        assert repair_dimensions == {"actionability", "evidence", "specificity"}

        # Build appendix
        appendix = build_repair_guided_appendix(repair_dimensions)

        # Verify appendix is non-empty and contains dimension sections
        assert len(appendix) > 0
        assert "actionability" in appendix.lower()
        assert "evidence" in appendix.lower()
        assert "specificity" in appendix.lower()

    def test_quality_score_increases_with_repair_guided_content(self):
        """Quality score increases when repair-guided markers are detected."""
        # Generic content without repair guidance
        plain_text = " ".join(["word"] * 100)
        plain_score = estimate_repair_guided_quality(plain_text, set())

        # Same content with actionability markers
        guided_text = plain_text + "\nOwner: Jane Doe\nSuccess criteria: Complete by Friday"
        guided_score = estimate_repair_guided_quality(
            guided_text, {"actionability"}
        )

        # Repair-guided score should be higher
        assert guided_score > plain_score
        assert guided_score <= 0.98  # Still capped

    def test_repair_guidance_extracted_from_previous_iteration_format(self):
        """Repair guidance in standard 'Previous Iteration Repair Guidance:' format is extracted."""
        context_with_guidance = """
        Some background content here.

        Previous Iteration Repair Guidance:
          - [actionability] Add owner information
          - [evidence] Add verification methods

        End of context.
        """

        # Extract dimensions
        dimensions = extract_repair_dimensions_from_context(context_with_guidance)

        # Should find both dimensions
        assert "actionability" in dimensions
        assert "evidence" in dimensions

    def test_multiple_repair_dimensions_generate_distinct_appendix_sections(self):
        """Each repair dimension generates distinct appendix content."""
        dimensions = {"actionability", "evidence", "specificity", "structure"}
        appendix = build_repair_guided_appendix(dimensions)

        # Appendix should be substantial
        assert len(appendix) > 500  # Expect multi-section output

        # Each section should appear
        for dimension in dimensions:
            # Check that dimension is mentioned (case-insensitive)
            assert dimension in appendix.lower() or dimension.replace("_", " ") in appendix.lower()


class TestRepairFeedbackIntegration:
    """Test integration of repair feedback through quality iteration cycle."""

    def test_iteration_n_recommendations_flow_to_iteration_n_plus_1_context(self):
        """Recommendations from iteration N flow to iteration N+1 as enhanced_context."""
        # Simulate iteration N recommendations
        iteration_n_recommendations = [
            {
                "dimension": "actionability",
                "repair_action": "Add owner information",
                "gap_description": "Missing responsible party"
            },
            {
                "dimension": "evidence",
                "repair_action": "Add data sources",
                "gap_description": "No verification method"
            }
        ]

        # Extract dimensions from recommendations
        dimensions = extract_repair_dimensions(iteration_n_recommendations)

        # Should extract canonical dimensions
        assert "actionability" in dimensions
        assert "evidence" in dimensions

        # Build appendix that would be used in iteration N+1
        appendix = build_repair_guided_appendix(dimensions)

        # Appendix should contain guidance for next iteration
        assert len(appendix) > 0
        assert "actionability" in appendix.lower() or "action" in appendix.lower()

    def test_repair_bonus_scoring_prevents_quality_plateau(self):
        """Repair bonus scoring enables quality improvement across iterations."""
        # Baseline text (no repair guidance)
        baseline_text = " ".join(["content"] * 200)
        baseline_score = estimate_repair_guided_quality(baseline_text, set())

        # Same text with all 9 repair dimensions addressed
        enhanced_text = baseline_text + """
        ## Action Plan
        Owner: Implementation Lead
        Success criteria: 95% uptime achieved
        Timeline: Q3 2026

        ## Evidence & Verification
        Data source: Production monitoring logs
        Verification method: Automated audit trail

        ## Specific Parameters
        Target metric: 95% availability
        Threshold: <500ms latency

        ## Structure & Logic
        Phase 1: Foundation
        Phase 2: Integration

        Because: Technical foundation enables reliability

        - Code formatting consistent
        - Markdown structure clear

        All sections included with real data.
        """

        enhanced_score = estimate_repair_guided_quality(
            enhanced_text,
            {
                "actionability", "evidence", "specificity", "structure",
                "reasoning", "formatting", "clarity", "completeness", "no_leakage"
            }
        )

        # Enhanced score must exceed baseline
        assert enhanced_score > baseline_score
        # But still capped at 0.98
        assert enhanced_score <= 0.98

    def test_no_regression_when_repair_dimensions_empty(self):
        """Quality estimation works normally when repair_dimensions is empty."""
        text = " ".join(["word"] * 300)

        # Score with empty dimensions
        score_no_repair = estimate_repair_guided_quality(text, set())

        # Should be baseline (0.75 for acceptable length)
        assert score_no_repair == 0.75

        # Should not be degraded by repair dimensions presence
        score_none_repair = estimate_repair_guided_quality(text, None) if hasattr(estimate_repair_guided_quality, '__code__') else 0.75
