"""
DOCSREG ↔ DocGen bridge — thin adapter between cyclic_doc_generation_pipeline.py
keyword arguments and DocumentTypeCertificationLoop.

This module is intentionally minimal: it translates the flat keyword-argument
interface used by the pipeline coordinator into the constructor + run_document_type()
call required by DocumentTypeCertificationLoop, and normalises the dataclass
return into a plain dict for downstream consumers.

Usage
-----
from ops.docgen.docsreg_docgen_integration import run_docsreg_document_type_cycle

result = run_docsreg_document_type_cycle(
    document_type="AIM-PFM",
    evidence_root="aims_workspace/docsreg_evidence",
    target_quality=0.98,
    max_fresh_runs=7,
    stall_limit=3,
    min_progress_delta=0.001,
    write_policy="write_all",
    auditor_mode="noop",
)
# result["outcome"] -> OUTCOME_CERTIFIED | OUTCOME_STALLED | OUTCOME_MAX_CYCLES | "ERROR"
"""
from __future__ import annotations

import logging
from pathlib import Path

from ops.docsreg.docsreg_document_type_cycle import (
    OUTCOME_CERTIFIED,  # noqa: F401 — re-exported for callers
    OUTCOME_MAX_CYCLES,  # noqa: F401 — re-exported for callers
    OUTCOME_STALLED,  # noqa: F401 — re-exported for callers
    DocumentTypeCertificationLoop,
)
from ops.docsreg.docsreg_auditor_input_contract import (
    validate_manifest_for_auditor,
    rejection_result,
)

log = logging.getLogger("docsreg_docgen_integration")


# ── Internal stub orchestrator ─────────────────────────────────────────────────


class _NoopOrchestrator:
    """Minimal orchestrator stub used when no real orchestrator is wired in.

    Returns ``"CERTIFIED"`` unconditionally so that the certification loop can
    exercise its full cycle logic.  Replace with a real ``DocsregOrchestrator``
    instance by wiring ``orchestrator`` into the loop constructor externally.
    """

    def start_certification_run(self, manifest, retry_policy=None) -> str:  # noqa: ANN001
        """Return a stub final-state string."""
        return "CERTIFIED"


# ── Public bridge function ─────────────────────────────────────────────────────


def run_docsreg_document_type_cycle(
    *,
    document_type: str,
    evidence_root: str | Path,
    target_quality: float = 0.98,
    max_fresh_runs: int = 7,
    stall_limit: int = 3,
    min_progress_delta: float = 0.001,
    write_policy: str = "write_all",
    auditor_mode: str = "noop",
    auditor_fn=None,
    document_text: str = "",
) -> dict:
    """Run a DOCSREG document-type certification cycle.

    Thin bridge between the cyclic_doc_generation_pipeline.py keyword-argument
    interface and ``DocumentTypeCertificationLoop``.

    Parameters
    ----------
    document_type:
        Identifier for the document type (e.g. ``"AIM-PFM"``).
    evidence_root:
        Root directory under which per-cycle evidence is written.
    target_quality:
        Quality threshold for CERTIFIED status (default 0.98).
    max_fresh_runs:
        Hard cap on fresh-start certification cycles (default 7).
    stall_limit:
        Number of consecutive cycles used for stall detection (default 3).
    min_progress_delta:
        Minimum quality improvement over ``stall_limit`` cycles before a stall
        is declared (default 0.001).
    write_policy:
        Evidence write policy passed to the loop.  Currently informational;
        the loop always writes evidence.  Default ``"write_all"``.
    auditor_mode:
        ``"production"`` — use :func:`~ops.docsreg.docsreg_production_auditor.build_structure_auditor_fn`
        (pure text analysis, no LLM, deterministic).  **Default for production.**
        ``"noop"``  — use the built-in no-op auditor (COMPONENT_PASS, quality=1.0).
        ``"claude_code"`` — use a real :class:`ClaudeCodeRunnerAuditor`.  If
        *auditor_fn* is ``None``, calls
        :func:`build_default_claude_code_auditor` to obtain a fail-closed
        default (returns ``BLOCKED`` until a real runner is wired).
    auditor_fn : callable | None
        Dependency-injectable auditor callable
        ``(manifest: dict) -> dict {"status", "quality", "notes"}``.
        When provided, overrides any auditor selected by *auditor_mode*.
        Intended for testing (inject a mock) or custom production wiring.

    Returns
    -------
    dict with keys:
        outcome : str  — OUTCOME_CERTIFIED / OUTCOME_STALLED / OUTCOME_MAX_CYCLES / "ERROR"
        quality : float — best quality achieved across all cycles
        cycles_completed : int
        evidence_dir : str
        error : str | None — only present when outcome == "ERROR"
    """
    try:
        evidence_root_path = Path(evidence_root)

        # ── Auditor selection ──────────────────────────────────────────────────
        if auditor_mode == "noop":
            # Use a local noop that always returns COMPONENT_PASS with quality=1.0
            # so that noop-auditor cycles are not penalised for missing quality.
            def _local_noop_auditor(manifest) -> dict:  # noqa: ANN001
                return {"status": "COMPONENT_PASS", "quality": 1.0, "notes": "noop"}

            auditor_fn = _local_noop_auditor
        elif auditor_mode == "production":
            from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn  # noqa: PLC0415

            auditor_fn = build_structure_auditor_fn(threshold=0.90)
            log.info(
                "docsreg_docgen_integration: auditor_mode='production' — "
                "using build_structure_auditor_fn(threshold=0.90)",
            )
        elif auditor_mode == "claude_code":
            if auditor_fn is None:
                from ops.docgen.claude_code_auditor import (  # noqa: PLC0415
                    ClaudeCodeRunnerAuditor,
                    SubprocessClaudeCodeRunner,
                )

                # Wire the subprocess runner for production Claude Code audits.
                _subprocess_runner = SubprocessClaudeCodeRunner(
                    command="claude", timeout_seconds=300
                )
                _runner_auditor: ClaudeCodeRunnerAuditor = (
                    ClaudeCodeRunnerAuditor(_subprocess_runner)
                )

                def _claude_code_auditor_fn(manifest) -> dict:  # noqa: ANN001
                    from dataclasses import asdict

                    doc_text = ""
                    doc_type = document_type
                    if isinstance(manifest, dict):
                        doc_text = manifest.get("document_text", "")
                        doc_type = manifest.get("document_type", document_type)
                        manifest_dict = manifest
                    elif hasattr(manifest, "document_text"):
                        # DocsregRunManifest dataclass
                        doc_text = getattr(manifest, "document_text", "")
                        doc_type = getattr(manifest, "document_type", "") or document_type
                        manifest_dict = asdict(manifest) if hasattr(manifest, "__dataclass_fields__") else {}
                    else:
                        manifest_dict = {}

                    # F1 INSTRUMENTATION: Log input contract state
                    log.info(
                        "docsreg_docgen_integration._claude_code_auditor_fn: "
                        "document_type=%r document_text_len=%d manifest_keys=%r",
                        doc_type,
                        len(doc_text),
                        list(manifest_dict.keys()),
                    )

                    # F4 INPUT CONTRACT VALIDATION: Reject manifest with insufficient content
                    # Ensure manifest_dict has document_text for contract validation
                    if "document_text" not in manifest_dict:
                        manifest_dict["document_text"] = doc_text
                    if "document_type" not in manifest_dict:
                        manifest_dict["document_type"] = doc_type
                    is_valid, rejection_reason = validate_manifest_for_auditor(
                        manifest_dict, doc_type
                    )
                    if not is_valid:
                        log.warning(
                            "docsreg_docgen_integration._claude_code_auditor_fn: "
                            "INPUT_CONTRACT_REJECTION: %s",
                            rejection_reason,
                        )
                        return rejection_result(rejection_reason)

                    result = _runner_auditor.audit(
                        document_text=doc_text,
                        document_type=doc_type,
                        metadata=manifest_dict,
                    )
                    status = (
                        "COMPONENT_PASS" if result.is_pass_like() else "COMPONENT_FAIL"
                    )

                    # F1 INSTRUMENTATION: Log auditor result
                    log.info(
                        "docsreg_docgen_integration._claude_code_auditor_fn result: "
                        "status=%r quality_score=%r verdict=%r",
                        status,
                        result.quality_score,
                        result.verdict,
                    )

                    return {
                        "status": status,
                        "quality": result.quality_score,
                        "notes": result.verdict,
                        "error": result.error,
                    }

                auditor_fn = _claude_code_auditor_fn
            log.info(
                "docsreg_docgen_integration: auditor_mode='claude_code' — "
                "using subprocess ClaudeCodeRunner with injected auditor_fn=%r",
                auditor_fn,
            )
        else:
            log.warning(
                "docsreg_docgen_integration: unknown auditor_mode=%r, falling back to noop",
                auditor_mode,
            )

            def _fallback_noop(manifest) -> dict:  # noqa: ANN001
                return {"status": "COMPONENT_PASS", "quality": 1.0, "notes": "fallback-noop"}

            auditor_fn = _fallback_noop

        # ── Build and run the certification loop ───────────────────────────────
        loop = DocumentTypeCertificationLoop(
            orchestrator=_NoopOrchestrator(),
            auditor_fn=auditor_fn,
            evidence_root=evidence_root_path,
            max_cycles=max_fresh_runs,
            target_quality=target_quality,
            min_quality_delta=min_progress_delta,
            stall_window=stall_limit,
            document_text=document_text,
        )

        log.info(
            "docsreg_docgen_integration: starting cycle for %r "
            "(target=%.3f, max_runs=%d, stall_limit=%d, auditor=%s)",
            document_type,
            target_quality,
            max_fresh_runs,
            stall_limit,
            auditor_mode,
        )

        outcome_obj = loop.run_document_type(document_type=document_type)

        result: dict = {
            "outcome": outcome_obj.outcome,
            "quality": outcome_obj.best_quality,
            "cycles_completed": outcome_obj.cycles_run,
            "evidence_dir": outcome_obj.evidence_dir or str(evidence_root_path / document_type),
        }

        log.info(
            "docsreg_docgen_integration: %r → outcome=%s quality=%.4f cycles=%d",
            document_type,
            result["outcome"],
            result["quality"],
            result["cycles_completed"],
        )
        return result

    except Exception as exc:  # noqa: BLE001 — fail-closed: never propagate
        log.error(
            "docsreg_docgen_integration: unexpected error for %r: %s",
            document_type,
            exc,
        )
        return {
            "outcome": "ERROR",
            "quality": 0.0,
            "cycles_completed": 0,
            "evidence_dir": str(evidence_root),
            "error": str(exc),
        }


# ── Campaign runner (Phase 12) ─────────────────────────────────────────────────


def run_docsreg_campaign(
    *,
    document_types: list,
    evidence_root: str | Path,
    orchestrator=None,
    auditor_threshold: float = 0.90,
    max_cycles: int = 10,
    target_quality: float = 0.98,
    document_text: str = "",
) -> dict:
    """Run a full DOCSREG certification campaign using the production auditor.

    Uses :func:`~ops.docsreg.docsreg_campaign_factory.build_production_campaign_runner`
    (Phase 11) to wire the production structure auditor and run a multi-document-type
    certification campaign in a single call.

    Parameters
    ----------
    document_types:
        List of document type identifiers to certify (e.g. ``["AIM-PFM", "procedure"]``).
    evidence_root:
        Root directory for campaign evidence output.
    orchestrator:
        DocsregOrchestrator instance or duck-typed equivalent.  Defaults to
        :class:`_NoopOrchestrator` when ``None``.
    auditor_threshold:
        Completeness ratio required for COMPONENT_PASS (default 0.90).
    max_cycles:
        Maximum certification cycles per document type (default 10).
    target_quality:
        Quality target for :class:`DocumentTypeCertificationLoop` (default 0.98).
    document_text:
        Seed document content embedded into every run manifest (default ``""``).

    Returns
    -------
    dict with keys:
        campaign_id : str
        total_types : int
        certified_count : int
        failed_count : int
        all_certified : bool
        started_at : str
        finished_at : str
        results : list[dict]  — per-type outcome dicts
    """
    from ops.docsreg.docsreg_campaign_factory import (  # noqa: PLC0415
        build_production_campaign_runner,
    )

    if orchestrator is None:
        orchestrator = _NoopOrchestrator()

    runner = build_production_campaign_runner(
        orchestrator=orchestrator,
        evidence_root=evidence_root,
        auditor_threshold=auditor_threshold,
        max_cycles=max_cycles,
        target_quality=target_quality,
        document_text=document_text,
    )

    outcome = runner.run_campaign(document_types=document_types)

    log.info(
        "run_docsreg_campaign: campaign_id=%s total=%d certified=%d failed=%d",
        outcome.campaign_id,
        outcome.total_types,
        outcome.certified_count,
        outcome.failed_count,
    )

    return {
        "campaign_id": outcome.campaign_id,
        "total_types": outcome.total_types,
        "certified_count": outcome.certified_count,
        "failed_count": outcome.failed_count,
        "all_certified": outcome.all_certified(),
        "started_at": outcome.started_at,
        "finished_at": outcome.finished_at,
        "results": [
            {
                "document_type": r.document_type,
                "outcome": r.outcome,
                "passed": r.passed,
                "best_quality": r.best_quality,
                "cycles_run": r.cycles_run,
                "evidence_dir": r.evidence_dir,
            }
            for r in outcome.results
        ],
    }
