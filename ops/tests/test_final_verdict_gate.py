"""
Test suite for final verdict determination and three-phase routing.

⚠️ LEGACY MOCK SUITE — DO NOT COUNT TOWARD CERTIFICATION.

These tests validate a LOCAL reimplementation (``determine_final_verdict_test``
below), NOT the real ``ops.docgen.vertical_slice_main.determine_final_verdict``.
They are retained only as historical scenario examples. The local helper has
diverged from the real implementation (different gate keys, no canonical
normalization), so a green result here proves nothing about shipped behavior.

Real verdict semantics are certified by:
  - ops/tests/test_final_verdict_real.py        (imports the real function)
  - ops/tests/test_baseline_eval_to_verdict_e2e.py  (real producer → consumer)

Every test here is marked ``legacy_mock``. Certification runs MUST exclude it:
    python -m pytest ops/tests -m "not legacy_mock"
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from ops.docgen.document_block_graph import (
    DocumentBlock,
    DocumentBlockGraph,
    BlockType,
)

# Exclude this entire module from the certification test count. It validates a
# local fake, not the real verdict router. See module docstring.
pytestmark = pytest.mark.legacy_mock


def determine_final_verdict_test(baseline_eval, blocked_error=None, repair_attempted=False, unresolved_issues=False):
    """
    Test helper that mimics the determine_final_verdict logic from vertical_slice_main.py.

    Three-phase routing:
    1. Hard blockers → BLOCKED (terminal)
    2. PASS criteria met → PASS
    3. Degradation path → READY_WITH_WARNINGS / NEEDS_TRAINING / NEEDS_MORE_REPAIR
    """
    # Phase 1: Hard blockers
    if blocked_error:
        return "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    gates = baseline_eval.get("gates", {})
    if not gates.get("all_required_blocks_generated"):
        return "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    if not gates.get("render_success"):
        return "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    critical_issues = gates.get("critical_issue_count", 0)
    if critical_issues > 0:
        return "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    # Phase 2: PASS criteria
    baseline_score = baseline_eval.get("baseline_score", 0.0)
    if (baseline_score >= 0.90 and
        gates.get("audit_pass", False) and
        gates.get("render_success", False) and
        gates.get("visual_qa_passed", False) and
        baseline_eval.get("training_pairs_count", 0) >= 2 and
        not unresolved_issues):
        return "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"

    # Phase 3: Degradation path
    if baseline_score >= 0.70:
        return "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"

    if baseline_score >= 0.60 and baseline_eval.get("training_pairs_count", 0) >= 1:
        return "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_TRAINING"

    return "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"


class TestFinalVerdictGate:
    """Test suite for final verdict determination and routing."""

    def test_hard_blocker_missing_required_blocks(self):
        """Phase 1: missing required blocks → BLOCKED."""
        baseline_eval = {
            "gates": {
                "all_required_blocks_generated": False,
                "render_success": True,
            },
            "baseline_score": 0.85,
        }
        verdict = determine_final_verdict_test(baseline_eval)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_hard_blocker_render_failure(self):
        """Phase 1: render failure → BLOCKED."""
        baseline_eval = {
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": False,
            },
            "baseline_score": 0.85,
        }
        verdict = determine_final_verdict_test(baseline_eval)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_hard_blocker_critical_issues(self):
        """Phase 1: critical issues present → BLOCKED."""
        baseline_eval = {
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "critical_issue_count": 1,
            },
            "baseline_score": 0.85,
        }
        verdict = determine_final_verdict_test(baseline_eval)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_explicit_blocked_error(self):
        """Phase 1: explicit blocked_error parameter → BLOCKED."""
        baseline_eval = {
            "baseline_score": 0.95,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "critical_issue_count": 0,
            },
        }
        verdict = determine_final_verdict_test(
            baseline_eval,
            blocked_error="Assembly failed",
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_pass_criteria_all_gates_met(self):
        """Phase 2: all PASS criteria met → PASS."""
        baseline_eval = {
            "baseline_score": 0.92,
            "training_pairs_count": 3,
            "gates": {
                "audit_pass": True,
                "render_success": True,
                "visual_qa_passed": True,
                "all_required_blocks_generated": True,
                "critical_issue_count": 0,
                "major_issue_count": 0,
            },
        }
        verdict = determine_final_verdict_test(
            baseline_eval,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"

    def test_ready_with_warnings_score_between_70_90(self):
        """Phase 3: score 0.70–0.90 → READY_WITH_WARNINGS."""
        baseline_eval = {
            "baseline_score": 0.75,
            "training_pairs_count": 2,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "critical_issue_count": 0,
                "audit_pass": False,  # One gate failed
            },
        }
        verdict = determine_final_verdict_test(baseline_eval)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"

    def test_needs_training_score_60_70_with_pairs(self):
        """Phase 3: score 0.60–0.70 with ≥1 training pairs → NEEDS_TRAINING."""
        baseline_eval = {
            "baseline_score": 0.65,
            "training_pairs_count": 2,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "critical_issue_count": 0,
            },
        }
        verdict = determine_final_verdict_test(baseline_eval)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_TRAINING"

    def test_needs_more_repair_score_below_60(self):
        """Phase 3: score <0.60 → NEEDS_MORE_REPAIR."""
        baseline_eval = {
            "baseline_score": 0.55,
            "training_pairs_count": 0,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "critical_issue_count": 0,
            },
        }
        verdict = determine_final_verdict_test(baseline_eval)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"

    def test_five_verdict_categories_exhaustive(self):
        """Verify all 5 verdict categories are reachable."""
        scenarios = [
            # BLOCKED: explicit error
            ({"baseline_score": 0.9, "gates": {}}, {"blocked_error": "error"}, "BLOCKED"),
            # PASS: all gates
            ({
                "baseline_score": 0.95,
                "training_pairs_count": 3,
                "gates": {
                    "all_required_blocks_generated": True,
                    "render_success": True,
                    "visual_qa_passed": True,
                    "audit_pass": True,
                    "critical_issue_count": 0,
                }
            }, {"unresolved_issues": False}, "PASS"),
            # READY_WITH_WARNINGS: 70–90
            ({"baseline_score": 0.78, "gates": {"all_required_blocks_generated": True, "render_success": True, "critical_issue_count": 0}}, {}, "READY_WITH_WARNINGS"),
            # NEEDS_TRAINING: 60–70 with pairs
            ({"baseline_score": 0.63, "training_pairs_count": 1, "gates": {"all_required_blocks_generated": True, "render_success": True, "critical_issue_count": 0}}, {}, "NEEDS_TRAINING"),
            # NEEDS_MORE_REPAIR: <60
            ({"baseline_score": 0.50, "gates": {"all_required_blocks_generated": True, "render_success": True, "critical_issue_count": 0}}, {}, "NEEDS_MORE_REPAIR"),
        ]

        for baseline_eval, kwargs, expected_suffix in scenarios:
            verdict = determine_final_verdict_test(baseline_eval, **kwargs)
            assert verdict.endswith(expected_suffix), f"Expected {expected_suffix} in {verdict}"
