"""
Integration tests for DOCGEN Phase B.5 quality cycle improvement.

Validates that the repair cycle can make measurable progress toward the 0.95
quality target using content-signal scoring and repair-guided content injection.
PHASE 5 validation suite.
"""

import pytest
from ops.docgen.block_generator_minimal import (
    BlockGeneratorMinimal,
    DocumentBlock,
    estimate_repair_guided_quality,
    build_repair_guided_appendix,
    extract_repair_dimensions_from_context,
    VALID_REPAIR_DIMENSIONS,
)
from ops.docgen.repair_loop_policy import should_continue_repair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(block_id: str = "test_block") -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id,
        block_type="section",
        document_type="technical_report",
        content_requirements="Describe the system reliability approach.",
    )


def _plain_context() -> str:
    """Document context with no repair guidance."""
    return "Background: This is a reliability report for the production system."


def _repair_context(dimensions) -> str:
    """Document context that includes a Previous Iteration Repair Guidance section."""
    lines = ["Background: This is a reliability report for the production system.", ""]
    lines.append("Previous Iteration Repair Guidance:")
    for dim in sorted(dimensions):
        lines.append(f"  - [{dim}] Improve {dim} in the document")
    return "\n".join(lines)


def _fully_guided_content(base_words: int = 300) -> str:
    """Content that contains explicit repair markers for all 9 dimensions."""
    base = " ".join(["content"] * base_words)
    return base + """

## Phase 1: Foundation
## Phase 2: Integration

Owner: Jane Smith
Responsible: Lead Engineer
Success criteria: 95% uptime achieved
Timeline: Q3 2026
Deadline: 2026-09-30
Action items: Configure monitoring

Data source: Production logs
Verification method: Automated audit trail
Source: Operations database
References: RFC 2119

Metric: 95% availability
Threshold: 500ms latency
Performance: 99.5%

Because this approach enables reliability, therefore we proceed.
As a result, the system achieves target SLA.

```bash
./monitor.sh --threshold 500
```

All sections are complete and finalized.
"""


# ---------------------------------------------------------------------------
# PHASE 5 Tests
# ---------------------------------------------------------------------------

class TestQualityCycleImprovement:
    """Validate that the repair cycle makes measurable quality progress."""

    def test_plain_content_baseline_quality(self):
        """Plain content with no guidance produces a baseline quality score."""
        text = " ".join(["word"] * 300)
        score = estimate_repair_guided_quality(text, set())
        # Acceptable-length plain text → 0.75 baseline
        assert score == 0.75

    def test_iteration_2_quality_exceeds_iteration_1(self):
        """Quality improves when repair-guided content is injected in iteration 2."""
        # Iteration 1: plain content, no repair guidance
        plain_text = " ".join(["word"] * 300)
        iter1_quality = estimate_repair_guided_quality(plain_text, set())

        # Iteration 2: same base text + repair-guided markers added
        guided_text = plain_text + "\nOwner: Jane Smith\nSuccess criteria: 95% uptime\nTimeline: Q3 2026"
        iter2_quality = estimate_repair_guided_quality(guided_text, {"actionability"})

        assert iter2_quality > iter1_quality, (
            f"Iteration 2 quality ({iter2_quality}) should exceed "
            f"iteration 1 quality ({iter1_quality})"
        )

    def test_fully_guided_content_reaches_target_band(self):
        """Fully repair-guided content (all 9 dimensions addressed) reaches >= 0.88."""
        text = _fully_guided_content()
        score = estimate_repair_guided_quality(text, VALID_REPAIR_DIMENSIONS)

        # Fully guided content: base 0.75 + up to 0.15 bonus = 0.90 max from scorer
        assert score >= 0.88, (
            f"Fully guided content should score >= 0.88, got {score}"
        )
        assert score <= 0.98, f"Score should not exceed cap 0.98, got {score}"

    def test_quality_progression_across_3_iterations(self):
        """Quality score increases monotonically across 3 simulated iterations."""
        base = " ".join(["word"] * 300)

        # Iteration 1: no guidance
        score_1 = estimate_repair_guided_quality(base, set())

        # Iteration 2: add actionability
        text_2 = base + "\nOwner: Alice\nSuccess criteria: Complete\nTimeline: Q2"
        score_2 = estimate_repair_guided_quality(text_2, {"actionability"})

        # Iteration 3: add evidence + specificity on top
        text_3 = text_2 + "\nData source: Prod logs\nVerification method: Audit\nMetric: 95%\nThreshold: 500ms"
        score_3 = estimate_repair_guided_quality(text_3, {"actionability", "evidence", "specificity"})

        assert score_2 > score_1, f"Iter 2 ({score_2}) should exceed iter 1 ({score_1})"
        assert score_3 > score_2, f"Iter 3 ({score_3}) should exceed iter 2 ({score_2})"

    def test_repair_cycle_continues_until_target_met(self):
        """should_continue_repair() correctly drives the iteration loop."""
        # Below target → cycle continues
        assert should_continue_repair(best_quality_ratio=0.75, target_ratio=0.95) is True
        assert should_continue_repair(best_quality_ratio=0.89, target_ratio=0.95) is True
        assert should_continue_repair(best_quality_ratio=0.90, target_ratio=0.95) is True

        # At or above target → cycle terminates
        assert should_continue_repair(best_quality_ratio=0.95, target_ratio=0.95) is False
        assert should_continue_repair(best_quality_ratio=0.97, target_ratio=0.95) is False
        assert should_continue_repair(best_quality_ratio=1.00, target_ratio=0.95) is False

    def test_repair_guidance_context_parsed_and_improves_quality(self):
        """End-to-end: guidance in context is parsed → appendix built → quality improves."""
        context = _repair_context({"actionability", "evidence", "specificity"})

        # Extract dimensions from the context
        dims = extract_repair_dimensions_from_context(context)
        assert "actionability" in dims
        assert "evidence" in dims
        assert "specificity" in dims

        # Build appendix
        appendix = build_repair_guided_appendix(dims)
        assert len(appendix) > 0

        # Simulate document text that incorporates the appendix guidance
        base_text = " ".join(["word"] * 300) + "\n" + appendix
        score = estimate_repair_guided_quality(base_text, dims)

        # Score should be above the plain baseline of 0.75
        assert score > 0.75, (
            f"Repair-guided content should exceed baseline 0.75, got {score}"
        )

    def test_no_regression_from_phases_1_3_changes(self):
        """Core quality estimation behavior unchanged — no regression from Phases 1–3."""
        # Short text baseline
        assert estimate_repair_guided_quality("Hi", set()) == 0.2

        # Empty text
        assert estimate_repair_guided_quality("", set()) == 0.0

        # Placeholder text → low score
        placeholder = " ".join(["word"] * 300) + "\n[TBD] Insert details here"
        assert estimate_repair_guided_quality(placeholder, set()) <= 0.2

        # Acceptable-length plain text → 0.75
        plain = " ".join(["word"] * 300)
        assert estimate_repair_guided_quality(plain, set()) == 0.75

        # Long text baseline → 0.5
        long_text = " ".join(["word"] * 1500)
        assert estimate_repair_guided_quality(long_text, set()) == 0.5
