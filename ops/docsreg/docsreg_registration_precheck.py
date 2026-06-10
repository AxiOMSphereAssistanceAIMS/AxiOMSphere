"""
DOCSREG registration precheck — MASTER_REGISTRATION_PRECHECK gate.

Aggregates three sub-gates before any certification step is allowed to proceed:

1. **Traceability** — every required section appears in the registered section
   map (required_sections ⊆ registered_sections).
2. **Evidence** — all required evidence files exist in the evidence directory
   (delegates to :func:`check_evidence_gate`).
3. **Write policy** — no write-policy violations are present.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It inspects data structures and the filesystem only.

Exports
-------
PrecheckResult : dataclass
    Aggregated outcome of all three sub-gate checks.
run_precheck(required_sections, registered_sections, evidence_dir,
             write_policy_violations) -> PrecheckResult
    Public entry point — never raises.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ops.docsreg.docsreg_evidence_gate import check_evidence_gate

log = logging.getLogger("docsreg_registration_precheck")

# ── Result dataclass ───────────────────────────────────────────────────────────


@dataclass
class PrecheckResult:
    """Aggregated outcome of the registration precheck gate.

    Attributes
    ----------
    passed:
        ``True`` only when *all three* sub-gates pass.
    traceability_passed:
        ``True`` when ``required_sections ⊆ registered_sections``.
    evidence_passed:
        ``True`` when all required evidence files are present.
    write_policy_passed:
        ``True`` when no write-policy violations were supplied.
    missing_sections:
        Sections that were required but not found in *registered_sections*.
    missing_evidence:
        Evidence filenames reported missing by :func:`check_evidence_gate`.
    write_policy_violations:
        Violation strings that were passed in (empty when gate passes).
    notes:
        Optional free-text annotation.
    """

    passed: bool
    traceability_passed: bool
    evidence_passed: bool
    write_policy_passed: bool
    missing_sections: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    write_policy_violations: list[str] = field(default_factory=list)
    notes: str = ""


# ── Public API ─────────────────────────────────────────────────────────────────


def run_precheck(
    required_sections: list[str],
    registered_sections: list[str],
    evidence_dir: str | Path,
    write_policy_violations: list[str] | None = None,
) -> PrecheckResult:
    """Run all three registration precheck gates.

    Gates
    -----
    1. **Traceability** — every item in *required_sections* must appear in
       *registered_sections*.  Missing items are collected into
       :attr:`PrecheckResult.missing_sections`.
    2. **Evidence** — calls :func:`~ops.docsreg.docsreg_evidence_gate.check_evidence_gate`
       on *evidence_dir*.  Missing filenames are propagated to
       :attr:`PrecheckResult.missing_evidence`.
    3. **Write policy** — passes when *write_policy_violations* is ``None``
       or an empty list.

    :attr:`PrecheckResult.passed` is ``True`` only when all three sub-gates
    pass simultaneously.

    Args:
        required_sections:
            Ordered list of section identifiers that *must* be traceable.
        registered_sections:
            Section identifiers that have been recorded in the traceability
            map so far.
        evidence_dir:
            Path to the directory that should contain all required evidence
            files.  Accepts both :class:`str` and :class:`pathlib.Path`.
        write_policy_violations:
            Optional list of write-policy violation strings.  Pass ``None``
            or an empty list when no violations exist.

    Returns:
        A :class:`PrecheckResult` describing the outcome of every sub-gate.

    This function never raises.  Any unexpected error is caught, logged at
    ERROR level, and returned as a fully-failed result with an explanatory
    note.
    """
    violations: list[str] = list(write_policy_violations or [])

    try:
        # ── Gate 1: traceability ───────────────────────────────────────────────
        registered_set: set[str] = set(registered_sections)
        missing_sections: list[str] = [
            s for s in required_sections if s not in registered_set
        ]
        traceability_passed = len(missing_sections) == 0

        if traceability_passed:
            log.info(
                "precheck/traceability: PASS — all %d required sections present",
                len(required_sections),
            )
        else:
            log.warning(
                "precheck/traceability: FAIL — %d section(s) missing: %s",
                len(missing_sections),
                missing_sections,
            )

        # ── Gate 2: evidence ──────────────────────────────────────────────────
        evidence_result = check_evidence_gate(evidence_dir)
        evidence_passed = evidence_result.passed
        missing_evidence: list[str] = list(evidence_result.missing_files)

        # check_evidence_gate already logs; add a precheck-level summary
        if evidence_passed:
            log.info("precheck/evidence: PASS")
        else:
            log.warning(
                "precheck/evidence: FAIL — %d file(s) missing",
                len(missing_evidence),
            )

        # ── Gate 3: write policy ──────────────────────────────────────────────
        write_policy_passed = len(violations) == 0

        if write_policy_passed:
            log.info("precheck/write_policy: PASS")
        else:
            log.warning(
                "precheck/write_policy: FAIL — %d violation(s): %s",
                len(violations),
                violations,
            )

    except Exception as exc:  # pragma: no cover — defensive
        log.error("precheck: unexpected error: %s", exc)
        return PrecheckResult(
            passed=False,
            traceability_passed=False,
            evidence_passed=False,
            write_policy_passed=False,
            notes=f"unexpected error: {exc}",
        )

    # ── Aggregate result ───────────────────────────────────────────────────────
    passed = traceability_passed and evidence_passed and write_policy_passed

    if passed:
        log.info("precheck: PASS — all three gates satisfied")
    else:
        gates_failed = [
            name
            for name, ok in (
                ("traceability", traceability_passed),
                ("evidence", evidence_passed),
                ("write_policy", write_policy_passed),
            )
            if not ok
        ]
        log.warning("precheck: FAIL — gate(s) failed: %s", gates_failed)

    return PrecheckResult(
        passed=passed,
        traceability_passed=traceability_passed,
        evidence_passed=evidence_passed,
        write_policy_passed=write_policy_passed,
        missing_sections=missing_sections,
        missing_evidence=missing_evidence,
        write_policy_violations=violations,
    )
