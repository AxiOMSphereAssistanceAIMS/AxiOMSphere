"""
DOCSREG quality-loop stop criteria — constants and check function.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("docsreg_stop_criteria")

# ── Constants ──────────────────────────────────────────────────────────────────

QUALITY_TARGET: float = 0.98
QUALITY_FLOOR: float = 0.60
MAX_REPAIR_CYCLES: int = 10
MIN_QUALITY_DELTA: float = 0.005
STALL_WINDOW: int = 3

STOP_REASON_TARGET_MET: str = "QUALITY_TARGET_MET"
STOP_REASON_STALL: str = "QUALITY_STALL_DETECTED"
STOP_REASON_MAX_CYCLES: str = "MAX_REPAIR_CYCLES_REACHED"
STOP_REASON_REGRESSION: str = "PIPELINE_REGRESSION"
STOP_REASON_FLOOR_FAILED: str = "QUALITY_FLOOR_NOT_MET"
STOP_REASON_NOT_STOPPED: str = "CONTINUE"


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class StopCriteriaResult:
    """Result returned by :func:`check_stop_criteria`."""

    stopped: bool
    reason: str       # one of STOP_REASON_* constants
    best_quality: float
    cycles_run: int
    notes: str = ""


# ── Public function ────────────────────────────────────────────────────────────


def check_stop_criteria(
    quality_history: list,
    max_cycles: int = MAX_REPAIR_CYCLES,
    target_quality: float = QUALITY_TARGET,
    min_quality_delta: float = MIN_QUALITY_DELTA,
    stall_window: int = STALL_WINDOW,
) -> StopCriteriaResult:
    """Evaluate stop criteria against the recorded quality history.

    Floor enforcement (QUALITY_FLOOR / STOP_REASON_FLOOR_FAILED) is
    handled by :mod:`docsreg_repair_rule`, not here.

    Parameters
    ----------
    quality_history:
        Ordered list of quality scores (oldest first).
    max_cycles:
        Hard cap on repair attempts.
    target_quality:
        Pipeline must reach this score to certify.
    min_quality_delta:
        Improvement below this across ``stall_window`` consecutive entries
        is treated as a stall.
    stall_window:
        Number of consecutive cycles checked for stall.

    Returns
    -------
    StopCriteriaResult
        Decision with ``stopped`` flag, ``reason``, ``best_quality``, and
        ``cycles_run``.  Never raises.
    """
    try:
        # Rule 1 — empty history
        if not quality_history:
            return StopCriteriaResult(
                stopped=False,
                reason=STOP_REASON_NOT_STOPPED,
                best_quality=0.0,
                cycles_run=0,
            )

        best = max(quality_history)
        cycles = len(quality_history)

        # Rule 2 — target met
        if best >= target_quality:
            return StopCriteriaResult(
                stopped=True,
                reason=STOP_REASON_TARGET_MET,
                best_quality=best,
                cycles_run=cycles,
            )

        # Rule 3 — max cycles reached
        if cycles >= max_cycles:
            return StopCriteriaResult(
                stopped=True,
                reason=STOP_REASON_MAX_CYCLES,
                best_quality=best,
                cycles_run=cycles,
            )

        # Rule 4 — stall detected
        if cycles >= stall_window:
            window = quality_history[-stall_window:]
            delta = max(window) - min(window)
            if delta < min_quality_delta:
                return StopCriteriaResult(
                    stopped=True,
                    reason=STOP_REASON_STALL,
                    best_quality=best,
                    cycles_run=cycles,
                )

        # Rule 5 — continue
        return StopCriteriaResult(
            stopped=False,
            reason=STOP_REASON_NOT_STOPPED,
            best_quality=best,
            cycles_run=cycles,
        )

    except Exception as exc:
        log.error("check_stop_criteria: unexpected error: %s", exc)
        return StopCriteriaResult(
            stopped=False,
            reason=STOP_REASON_NOT_STOPPED,
            best_quality=0.0,
            cycles_run=0,
            notes=f"error: {exc}",
        )
