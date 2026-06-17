"""
DOCSREG fresh-start reproducibility evidence — computes and persists a
``reproducibility_metric`` for each certification cycle.

Each call to :func:`write_fresh_start_evidence` writes a single JSON file
``fresh_start_evidence.json`` into ``<cycle_dir>/evidence/`` so that downstream
gates and auditors can verify whether the cycle started from a truly clean state.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It uses only the Python standard library.

Exports
-------
FRESH_START_EVIDENCE_FILE    — filename constant: "fresh_start_evidence.json"
FreshStartEvidence           — dataclass capturing reproducibility_metric
compute_reproducibility_metric(result) -> float
    Pure function: 1.0 / 0.5 / 0.0 based on FreshStartResult state.
build_fresh_start_evidence(cycle_id, result) -> FreshStartEvidence
    Assembles a FreshStartEvidence from a cycle_id + FreshStartResult.
write_fresh_start_evidence(evidence, cycle_dir) -> bool
    Writes evidence as JSON to <cycle_dir>/evidence/fresh_start_evidence.json.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ops.docsreg.docsreg_fresh_start import FreshStartResult

log = logging.getLogger("docsreg_fresh_start_evidence")

# ── Module-level constant ─────────────────────────────────────────────────────

FRESH_START_EVIDENCE_FILE: str = "fresh_start_evidence.json"


# ── Evidence dataclass ────────────────────────────────────────────────────────


@dataclass
class FreshStartEvidence:
    """Reproducibility evidence record for a single certification cycle.

    Attributes
    ----------
    cycle_id:
        Human-readable cycle identifier, e.g. ``"cycle_001"``.
    cycle_dir:
        Absolute path string of the cycle working directory.
    reproducibility_metric:
        ``1.0`` — truly fresh (passed, no existing files, no missing subdirs).
        ``0.5`` — repaired (passed, but missing subdirs were created).
        ``0.0`` — dirty (passed=False).
    fresh_start_passed:
        Mirrors :attr:`FreshStartResult.passed`.
    existing_files_count:
        Number of stale files found in the cycle tree.
    missing_subdirs_count:
        Number of subdirectories that were absent and had to be created.
    notes:
        Human-readable annotation copied from :attr:`FreshStartResult.notes`.
    timestamp_utc:
        ISO-format UTC timestamp recorded at evidence-build time.
    """

    cycle_id: str
    cycle_dir: str
    reproducibility_metric: float
    fresh_start_passed: bool
    existing_files_count: int
    missing_subdirs_count: int
    notes: str = ""
    timestamp_utc: str = ""


# ── Pure metric computation ───────────────────────────────────────────────────


def compute_reproducibility_metric(result: FreshStartResult) -> float:
    """Return a reproducibility score derived from *result*.

    Scoring rules (evaluated in order):

    * ``0.0`` — ``result.passed`` is ``False`` (dirty or error state).
    * ``0.5`` — ``result.passed`` is ``True`` **and** ``result.missing_subdirs``
      is non-empty (subdirs were absent and had to be created/repaired).
    * ``1.0`` — ``result.passed`` is ``True``, ``result.missing_subdirs`` is
      empty, and ``result.existing_files`` is empty (truly fresh).

    Args:
        result: :class:`~ops.docsreg.docsreg_fresh_start.FreshStartResult`
            produced by :func:`~ops.docsreg.docsreg_fresh_start.assert_fresh_start_cycle`.

    Returns:
        ``float`` in ``{0.0, 0.5, 1.0}``.  Never raises.
    """
    if not result.passed:
        return 0.0
    if result.missing_subdirs:
        return 0.5
    return 1.0


# ── Evidence builder ──────────────────────────────────────────────────────────


def build_fresh_start_evidence(
    cycle_id: str,
    result: FreshStartResult,
) -> FreshStartEvidence:
    """Assemble a :class:`FreshStartEvidence` from *cycle_id* and *result*.

    The ``timestamp_utc`` field is set to the current UTC time in ISO 8601
    format at the moment this function is called.

    Args:
        cycle_id: Identifier for the cycle, e.g. ``"cycle_001"``.
        result: :class:`~ops.docsreg.docsreg_fresh_start.FreshStartResult`
            produced by
            :func:`~ops.docsreg.docsreg_fresh_start.assert_fresh_start_cycle`.

    Returns:
        :class:`FreshStartEvidence` — never raises.
    """
    metric = compute_reproducibility_metric(result)
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    return FreshStartEvidence(
        cycle_id=cycle_id,
        cycle_dir=result.cycle_dir,
        reproducibility_metric=metric,
        fresh_start_passed=result.passed,
        existing_files_count=len(result.existing_files),
        missing_subdirs_count=len(result.missing_subdirs),
        notes=result.notes,
        timestamp_utc=timestamp,
    )


# ── Evidence writer ───────────────────────────────────────────────────────────


def write_fresh_start_evidence(
    evidence: FreshStartEvidence,
    cycle_dir: str | Path,
) -> bool:
    """Write *evidence* as JSON to ``<cycle_dir>/evidence/fresh_start_evidence.json``.

    The ``evidence/`` subdirectory is created if it does not already exist.

    Args:
        evidence: :class:`FreshStartEvidence` instance to serialise.
        cycle_dir: Root cycle directory.  The file is written under the
            ``evidence/`` subdirectory inside it.

    Returns:
        ``True`` on success, ``False`` on any failure.  Never raises.
    """
    try:
        evidence_dir = Path(cycle_dir) / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        out_path = evidence_dir / FRESH_START_EVIDENCE_FILE
        payload = asdict(evidence)
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log.info(
            "fresh_start_evidence: written to %s (metric=%.1f)",
            str(out_path),
            evidence.reproducibility_metric,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.error(
            "fresh_start_evidence: failed to write evidence for cycle %r: %s",
            evidence.cycle_id,
            exc,
        )
        return False
