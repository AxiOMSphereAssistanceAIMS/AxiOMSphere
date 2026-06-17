"""
DOCSREG repair-to-pipeline rule — determines pipeline-level repair action
after a failed certification cycle.

This module handles pipeline-level repair decisions (change retry policy,
escalate to Repairman, halt, adjust model config).  It does NOT handle
document-level patching — that is PatchLedger's responsibility.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("docsreg_repair_rule")

# ── Constants ──────────────────────────────────────────────────────────────────

REPAIR_ACTION_RETRY: str = "RETRY_CYCLE"
REPAIR_ACTION_ADJUST_POLICY: str = "ADJUST_RETRY_POLICY"
REPAIR_ACTION_ESCALATE: str = "ESCALATE_TO_REPAIRMAN"
REPAIR_ACTION_HALT: str = "HALT_PIPELINE"


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class RepairDecision:
    """Pipeline-level repair decision returned by :func:`evaluate_repair_rule`."""

    action: str             # one of REPAIR_ACTION_* constants
    reason: str             # human-readable explanation
    escalate_to_repairman: bool   # True when action == REPAIR_ACTION_ESCALATE
    cycle_count: int        # cycles run so far
    best_quality: float     # best quality seen across all cycles
    notes: str = ""


# ── Public function ────────────────────────────────────────────────────────────


def evaluate_repair_rule(
    quality_history: list,
    regression_detected: bool = False,
    max_cycles: int = 10,
    quality_floor: float = 0.60,
    min_quality_delta: float = 0.005,
    stall_window: int = 3,
) -> RepairDecision:
    """Determine the pipeline-level repair action after a failed cycle.

    Parameters
    ----------
    quality_history:
        Ordered list of quality scores (oldest first).
    regression_detected:
        Whether a regression was detected in the pipeline.
    max_cycles:
        Hard cap on repair attempts.
    quality_floor:
        Minimum acceptable quality score.
    min_quality_delta:
        Improvement below this across ``stall_window`` entries is a stall.
    stall_window:
        Number of consecutive cycles used for stall detection.

    Returns
    -------
    RepairDecision
        Pipeline-level repair action with rationale.  Never raises.
    """
    try:
        best = max(quality_history) if quality_history else 0.0
        cycles = len(quality_history)

        # Rule 1 — regression detected
        if regression_detected:
            return RepairDecision(
                action=REPAIR_ACTION_HALT,
                reason="pipeline regression detected; halting to prevent data corruption",
                escalate_to_repairman=False,
                cycle_count=cycles,
                best_quality=best,
            )

        # Rule 2 — no cycles yet (must precede max-cycles check to avoid
        #           misclassifying an empty history when max_cycles=0)
        if not quality_history:
            return RepairDecision(
                action=REPAIR_ACTION_RETRY,
                reason="no cycles run yet; retrying",
                escalate_to_repairman=False,
                cycle_count=0,
                best_quality=0.0,
            )

        # Rule 3 — max cycles reached
        if cycles >= max_cycles:
            return RepairDecision(
                action=REPAIR_ACTION_ESCALATE,
                reason="max cycles reached without certification",
                escalate_to_repairman=True,
                cycle_count=cycles,
                best_quality=best,
            )

        # Rule 4 — quality below floor
        if best < quality_floor:
            return RepairDecision(
                action=REPAIR_ACTION_ESCALATE,
                reason="quality below floor; escalating to Repairman",
                escalate_to_repairman=True,
                cycle_count=cycles,
                best_quality=best,
            )

        # Rule 5 — stall detected
        if cycles >= stall_window:
            window = quality_history[-stall_window:]
            delta = max(window) - min(window)
            if delta < min_quality_delta:
                return RepairDecision(
                    action=REPAIR_ACTION_ESCALATE,
                    reason="quality stalled; escalating to Repairman",
                    escalate_to_repairman=True,
                    cycle_count=cycles,
                    best_quality=best,
                )

        # Rule 6 — quality improving
        if cycles >= 2 and quality_history[-1] > quality_history[-2]:
            return RepairDecision(
                action=REPAIR_ACTION_ADJUST_POLICY,
                reason="quality improving; adjusting retry policy",
                escalate_to_repairman=False,
                cycle_count=cycles,
                best_quality=best,
            )

        # Rule 7 — default
        return RepairDecision(
            action=REPAIR_ACTION_RETRY,
            reason="continuing with next cycle",
            escalate_to_repairman=False,
            cycle_count=cycles,
            best_quality=best,
        )

    except Exception as exc:
        log.error("evaluate_repair_rule: unexpected error: %s", exc)
        return RepairDecision(
            action=REPAIR_ACTION_HALT,
            reason=f"unexpected error: {exc}",
            escalate_to_repairman=False,
            cycle_count=0,
            best_quality=0.0,
        )
