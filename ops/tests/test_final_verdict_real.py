"""
Semantic validation tests for determine_final_verdict() routing logic.

Tests enforce corrected routing semantics:
- Critical issues → BLOCKED (terminal)
- Major/unresolved issues → NEEDS_MORE_REPAIR (repairable, NOT blocked)
- Warnings → never auto-blocked (degrade PASS to READY_WITH_WARNINGS only)
- Score thresholds: 0.90 (PASS), 0.70 (READY_WITH_WARNINGS), 0.50 (NEEDS_MORE_REPAIR)
- Training signal: BOTH training_readiness > 0 AND training_pairs_count > 0 (not either/or)
"""

from __future__ import annotations

import pytest
from ops.docgen.vertical_slice_main import determine_final_verdict


def _base_eval(
    score: float = 0.85,
    verdict: str = "MARGINAL",
    training_readiness: float = 0.7,
    pairs: int = 2,
) -> dict:
    """Helper fixture to create baseline eval dict with sensible defaults.

    Gates use PRODUCER names (from BaselineEvalMinimal), not canonical names.
    They will be normalized by determine_final_verdict() via normalize_gates().

    Note: training_pairs_available is a Phase 4 gate that doesn't come from
    BaselineEvalMinimal. Tests that need this gate should set it manually after
    calling _base_eval().
    """
    return {
        "baseline_score": score,
        "overall_verdict": verdict,
        "metrics": {"training_readiness": training_readiness},
        "gates": {
            # Producer gate names (BaselineEvalMinimal._build_gates() output)
            "required_blocks_present": True,  # Normalized to "all_required_blocks_generated"
            "render_success": True,
            "no_critical_issues": True,
            "no_duplicate_blocks": True,
            "no_placeholder_content": True,
            "evidence_complete": True,
            "audit_pass": False,
        },
    }


class TestDetermineFinalVerdictSemantics:
    """Semantic validation tests for corrected routing logic."""

    def test_critical_issue_blocks_terminal(self):
        """SEMANTIC: critical issues trigger hard BLOCKED (terminal state)."""
        eval_dict = _base_eval(score=0.95, verdict="PASS_QUALITY_GATE", pairs=3)
        # blocked_error=True simulates detection of critical issues at runtime
        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=True,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_major_issue_routes_to_repair_not_blocked(self):
        """SEMANTIC: major issues route to NEEDS_MORE_REPAIR (repairable, NOT BLOCKED)."""
        eval_dict = _base_eval(score=0.80)
        # Duplicate content is a Phase 2 repairable issue
        eval_dict["gates"]["no_duplicate_blocks"] = False

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"
        assert "BLOCKED" not in verdict

    def test_unresolved_issues_route_to_repair_not_blocked(self):
        """SEMANTIC: unresolved_issues=True routes to NEEDS_MORE_REPAIR (repairable, NOT BLOCKED)."""
        eval_dict = _base_eval(score=0.75)

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=True,  # Explicit unresolved flag
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"
        assert "BLOCKED" not in verdict

    def test_warning_does_not_auto_block(self):
        """SEMANTIC: warning issues never trigger BLOCKED; degrade to READY_WITH_WARNINGS instead."""
        eval_dict = _base_eval(score=0.78, verdict="READY_WITH_WARNINGS")
        # Score 0.78 is between 0.70 and 0.90, so routes to READY_WITH_WARNINGS
        # (no Phase 1 or Phase 2 issues, but not clean PASS)

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"
        assert "BLOCKED" not in verdict

    def test_score_above_070_routes_to_ready_with_warnings(self):
        """SEMANTIC: score ≥0.70 routes to READY_WITH_WARNINGS (adequate quality despite gaps)."""
        eval_dict = _base_eval(score=0.75, pairs=0)
        eval_dict["metrics"]["training_readiness"] = 0.0

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"

    def test_score_below_070_with_training_signal_routes_to_training(self):
        """SEMANTIC: score <0.70 PLUS BOTH training_readiness>0 AND training_pairs_available gate → NEEDS_TRAINING."""
        eval_dict = _base_eval(score=0.65, training_readiness=0.72, pairs=3)
        # Set the training_pairs_available gate (Phase 4) to indicate training data available
        eval_dict["gates"]["training_pairs_available"] = True

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_TRAINING"

    def test_score_below_070_without_training_signal_routes_to_repair_if_above_050(self):
        """SEMANTIC: score 0.50–0.70 without training signal → NEEDS_MORE_REPAIR."""
        eval_dict = _base_eval(score=0.55, training_readiness=0.0, pairs=0)

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"

    def test_score_below_050_without_training_signal_blocks(self):
        """SEMANTIC: score <0.50 without training/repair signals → fallback BLOCKED."""
        eval_dict = _base_eval(score=0.45, training_readiness=0.0, pairs=0)

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_repair_attempted_routes_to_repair_even_low_score(self):
        """SEMANTIC: repair_attempted=True routes to NEEDS_MORE_REPAIR even if score <0.50."""
        eval_dict = _base_eval(score=0.20, training_readiness=0.0, pairs=0)

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=True,  # Repair was already attempted
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"
        assert "BLOCKED" not in verdict

    def test_clean_pass_requires_all_pass_conditions(self):
        """SEMANTIC: PASS requires score≥0.90 + all gates + training_pairs_available + evidence_complete + verdict==PASS_QUALITY_GATE + no_warnings."""
        eval_dict = _base_eval(score=0.95, verdict="PASS_QUALITY_GATE", pairs=3)
        eval_dict["gates"]["audit_pass"] = True
        # evidence_complete is already True from _base_eval()
        # Set training_pairs_available gate (required for PASS)
        eval_dict["gates"]["training_pairs_available"] = True

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"

    def test_clean_pass_fails_to_ready_with_warnings_if_warning_exists(self):
        """SEMANTIC: warning issues degrade PASS → READY_WITH_WARNINGS (warning never blocks, only prevents PASS)."""
        eval_dict = _base_eval(score=0.93, verdict="READY_WITH_WARNINGS", pairs=3)
        # Verdict is READY_WITH_WARNINGS (warning detected at eval time), not PASS_QUALITY_GATE
        eval_dict["gates"]["audit_pass"] = True
        # Evidence complete is already True from _base_eval()

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"
        assert "PASS" not in verdict  # Degraded from PASS

    def test_training_signal_requires_both_conditions(self):
        """SEMANTIC: NEEDS_TRAINING requires BOTH training_readiness>0 AND training_pairs_available gate (not either/or)."""
        # Test: has training_readiness but no training_pairs_available gate → NOT NEEDS_TRAINING, falls through to READY_WITH_WARNINGS at score 0.65 >= 0.50
        eval_dict = _base_eval(score=0.65, training_readiness=0.8, pairs=0)
        # training_pairs_available defaults to False
        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        # Score 0.65 >= 0.50 → NEEDS_MORE_REPAIR (NOT READY_WITH_WARNINGS because score < 0.70)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"

        # Test: has training_pairs_available gate but no training_readiness → NOT NEEDS_TRAINING
        eval_dict = _base_eval(score=0.65, training_readiness=0.0, pairs=3)
        eval_dict["gates"]["training_pairs_available"] = True
        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        # training_readiness=0.0 fails BOTH condition → NEEDS_MORE_REPAIR
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"

    def test_duplicate_content_routes_to_repair(self):
        """SEMANTIC: no_duplicate_blocks=False (duplicate content) routes to NEEDS_MORE_REPAIR (repairable)."""
        eval_dict = _base_eval(score=0.80)
        eval_dict["gates"]["no_duplicate_blocks"] = False

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"

    def test_placeholder_content_routes_to_repair(self):
        """SEMANTIC: no_placeholder_content=False (placeholder present) routes to NEEDS_MORE_REPAIR (repairable)."""
        eval_dict = _base_eval(score=0.80)
        eval_dict["gates"]["no_placeholder_content"] = False

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"

    def test_blocked_error_flag_triggers_hard_block(self):
        """SEMANTIC: blocked_error=True (hard runtime error) → BLOCKED (terminal)."""
        eval_dict = _base_eval(score=0.95, verdict="PASS_QUALITY_GATE")

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=True,  # Hard runtime error
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_missing_render_success_gate_blocks(self):
        """SEMANTIC: render_success=False → Phase 1 hard blocker → BLOCKED."""
        eval_dict = _base_eval(score=0.95)
        eval_dict["gates"]["render_success"] = False

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_missing_blocks_gate_blocks(self):
        """SEMANTIC: required_blocks_present=False (all_required_blocks_generated=False after normalization) → Phase 1 hard blocker → BLOCKED."""
        eval_dict = _base_eval(score=0.95)
        eval_dict["gates"]["required_blocks_present"] = False

        verdict = determine_final_verdict(
            baseline_eval=eval_dict,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"
