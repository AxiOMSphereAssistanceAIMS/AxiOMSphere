"""
DOCSREG evidence gate — hard pre-certification gate.

Checks that all required evidence files are present in the evidence directory
before any certification step is allowed to proceed.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It inspects the filesystem only.

Exports
-------
REQUIRED_EVIDENCE_FILES : tuple[str, ...]
    Names (not paths) of all files that must be present.
EvidenceGateResult : dataclass
    Outcome of a single gate check.
check_evidence_gate(evidence_dir) -> EvidenceGateResult
    Public entry point — never raises.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("docsreg_evidence_gate")

# ── Required evidence files ────────────────────────────────────────────────────

REQUIRED_EVIDENCE_FILES: tuple[str, ...] = (
    "best_draft.md",
    "section_audit.json",
    "reference_governance_report.json",
    "repair_log.json",
    "quality_scores.json",
    "source_documents_manifest.json",
    "traceability_map.json",
    "patch_ledger.json",
    "model_output_contracts.json",
    "protected_actions_audit.json",
    "registration_precheck.json",
)


# ── Result dataclass ───────────────────────────────────────────────────────────


@dataclass
class EvidenceGateResult:
    """Outcome of a single evidence gate check."""

    passed: bool
    missing_files: list[str] = field(default_factory=list)
    present_files: list[str] = field(default_factory=list)
    evidence_dir: str = ""


# ── Public API ─────────────────────────────────────────────────────────────────


def check_evidence_gate(evidence_dir: str | Path) -> EvidenceGateResult:
    """Check whether all required evidence files exist in *evidence_dir*.

    Args:
        evidence_dir: Path to the directory that should contain all evidence
            files.  Accepts both ``str`` and :class:`pathlib.Path`.

    Returns:
        :class:`EvidenceGateResult` describing which files are present and
        which are missing.  ``result.passed`` is ``True`` only when every
        required file exists.

    This function never raises.  Any unexpected filesystem error is caught,
    logged at ERROR level, and returned as a fully-failed result.
    """
    dir_path = Path(evidence_dir)
    dir_str = str(dir_path)

    try:
        dir_exists = dir_path.is_dir()
    except Exception as exc:  # pragma: no cover — defensive
        log.error(
            "evidence_gate: unexpected error checking directory %r: %s",
            dir_str,
            exc,
        )
        return EvidenceGateResult(
            passed=False,
            missing_files=list(REQUIRED_EVIDENCE_FILES),
            present_files=[],
            evidence_dir=dir_str,
        )

    if not dir_exists:
        log.warning("evidence_gate: directory does not exist — %s", dir_str)
        return EvidenceGateResult(
            passed=False,
            missing_files=list(REQUIRED_EVIDENCE_FILES),
            present_files=[],
            evidence_dir=dir_str,
        )

    present: list[str] = []
    missing: list[str] = []
    for filename in REQUIRED_EVIDENCE_FILES:
        if (dir_path / filename).is_file():
            present.append(filename)
        else:
            missing.append(filename)

    passed = len(missing) == 0

    if passed:
        log.info(
            "evidence_gate: PASS — all %d files present in %s",
            len(present),
            dir_str,
        )
    else:
        log.warning(
            "evidence_gate: FAIL — %d/%d files missing in %s: %s",
            len(missing),
            len(REQUIRED_EVIDENCE_FILES),
            dir_str,
            missing,
        )

    return EvidenceGateResult(
        passed=passed,
        missing_files=missing,
        present_files=present,
        evidence_dir=dir_str,
    )
