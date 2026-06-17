"""
DOCSREG Best Draft Governance Sync Gate.

Provides BEST_DRAFT_GOVERNANCE_SYNC_GATE — a deterministic gate that detects
whether the best_draft.md file in a certification run contains fabricated
standards that were NOT stripped during the cyclic improvement loop.

This module is intentionally free of LLM calls, HTTP calls, and any file I/O
except for the load_best_draft() helper.

Usage::

    from ops.docsreg.docsreg_best_draft_sync import (
        check_best_draft_sync,
        apply_best_draft_sync,
        load_best_draft,
        BestDraftSyncResult,
    )

    result = check_best_draft_sync(best_draft_text)
    # result.gate_decision  → "PASS" | "SYNC_REQUIRED" | "CERTIFICATION_BLOCKER"
    # result.is_clean       → bool
    # result.fabricated_count → int
    # result.removed_lines  → list[str]
    # result.cleaned_text   → str
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ops.agents.skills.docsreg_reference_governance import (
    ReferenceGateDecision,
    run_reference_governance_gate,
    strip_fabricated_standards,
)

log = logging.getLogger("docsreg_best_draft_sync")

# ── Gate decision constants ────────────────────────────────────────────────────

GATE_PASS = "PASS"
GATE_SYNC_REQUIRED = "SYNC_REQUIRED"
GATE_CERTIFICATION_BLOCKER = "CERTIFICATION_BLOCKER"


# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class BestDraftSyncResult:
    """Outcome of a best_draft governance sync gate run."""

    is_clean: bool
    fabricated_count: int
    removed_lines: list[str]
    cleaned_text: str
    gate_decision: str  # "PASS" | "SYNC_REQUIRED" | "CERTIFICATION_BLOCKER"
    gate_version: str = "v1"


# ── Public API ─────────────────────────────────────────────────────────────────


def check_best_draft_sync(
    best_draft_text: str,
) -> BestDraftSyncResult:
    """Check if best_draft is already governance-clean.

    Runs strip_fabricated_standards() to collect any fabricated lines, then
    optionally re-runs run_reference_governance_gate() on the stripped text to
    confirm no residual blockers remain.

    Decision logic:
    - fabricated_count == 0 AND governance gate == PASS  → PASS
    - fabricated lines were removed                       → SYNC_REQUIRED
    - after stripping, governance gate still CERTIFICATION_BLOCKER → CERTIFICATION_BLOCKER

    Args:
        best_draft_text: Full text of the best_draft.md file.

    Returns:
        BestDraftSyncResult with is_clean, fabricated_count, removed_lines,
        cleaned_text, gate_decision, and gate_version.
    """
    cleaned_text, removed_lines = strip_fabricated_standards(best_draft_text)
    fabricated_count = len(removed_lines)

    if fabricated_count == 0:
        # No lines were stripped — check that governance gate also agrees
        gate_result = run_reference_governance_gate(best_draft_text)
        if gate_result.decision == ReferenceGateDecision.PASS:
            log.info("check_best_draft_sync: gate_decision=PASS (clean document)")
            return BestDraftSyncResult(
                is_clean=True,
                fabricated_count=0,
                removed_lines=[],
                cleaned_text=best_draft_text,
                gate_decision=GATE_PASS,
            )
        # Governance gate found something strip_fabricated_standards missed
        # (e.g. fabricated references inside headings, or other blockers).
        #
        # Fail-closed design: we intentionally escalate to CERTIFICATION_BLOCKER
        # here rather than returning PASS or SYNC_REQUIRED.  strip_fabricated_standards
        # only removes body lines it can positively match — but the governance gate has
        # independently detected references that cannot be verified against the approved
        # standards corpus.  When those two signals disagree (strip removed nothing, yet
        # gate is not PASS) the certification safety posture requires us to block, not to
        # silently approve.  Fail closed, not fail open.
        log.warning(
            "check_best_draft_sync: strip found 0 lines but governance gate=%s — "
            "escalating to CERTIFICATION_BLOCKER",
            gate_result.decision.value,
        )
        return BestDraftSyncResult(
            is_clean=False,
            fabricated_count=gate_result.fabricated_count,
            removed_lines=[],
            cleaned_text=best_draft_text,
            gate_decision=GATE_CERTIFICATION_BLOCKER,
        )

    # Lines were stripped — verify the cleaned text passes governance
    post_gate_result = run_reference_governance_gate(cleaned_text)
    if post_gate_result.decision == ReferenceGateDecision.CERTIFICATION_BLOCKER:
        log.warning(
            "check_best_draft_sync: gate_decision=CERTIFICATION_BLOCKER — "
            "%d line(s) stripped but %d fabricated refs remain in cleaned text",
            fabricated_count,
            post_gate_result.fabricated_count,
        )
        return BestDraftSyncResult(
            is_clean=False,
            fabricated_count=fabricated_count,
            removed_lines=removed_lines,
            cleaned_text=cleaned_text,
            gate_decision=GATE_CERTIFICATION_BLOCKER,
        )

    log.info(
        "check_best_draft_sync: gate_decision=SYNC_REQUIRED — %d line(s) stripped",
        fabricated_count,
    )
    return BestDraftSyncResult(
        is_clean=False,
        fabricated_count=fabricated_count,
        removed_lines=removed_lines,
        cleaned_text=cleaned_text,
        gate_decision=GATE_SYNC_REQUIRED,
    )


def apply_best_draft_sync(
    best_draft_text: str,
) -> tuple[str, BestDraftSyncResult]:
    """Apply governance cleaning to best_draft and return (cleaned_text, result).

    Always returns the cleaned text.  If the document is already clean this is
    a no-op and the original text is returned unchanged.

    Args:
        best_draft_text: Full text of the best_draft.md file.

    Returns:
        Tuple of (cleaned_text, BestDraftSyncResult).
    """
    result = check_best_draft_sync(best_draft_text)
    return result.cleaned_text, result


def load_best_draft(path: str | Path) -> str:
    """Load best_draft.md from disk.

    Args:
        path: Filesystem path to the best_draft.md file.

    Returns:
        File contents as a string (UTF-8).

    Raises:
        FileNotFoundError: If the file does not exist at *path*.
        OSError: On other I/O errors.
    """
    resolved = Path(path)
    log.debug("load_best_draft: reading %s", resolved)
    return resolved.read_text(encoding="utf-8")
