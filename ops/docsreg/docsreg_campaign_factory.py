"""
DOCSREG Phase 11 — Campaign factory.

Provides ``build_production_campaign_runner()`` — a single entry point that
wires the Phase 10 production auditor, a :class:`DocumentTypeCertificationLoop`,
and a :class:`CampaignRunner` together.

Callers only need to supply a ``DocsregOrchestrator`` instance (or a duck-typed
equivalent); all internal wiring is handled here.

Typical usage::

    from ops.docsreg.docsreg_campaign_factory import build_production_campaign_runner

    runner = build_production_campaign_runner(
        orchestrator=my_orchestrator,
        evidence_root="aims_workspace/docsreg_campaign_evidence",
        auditor_threshold=0.90,
        max_cycles=10,
        document_text=document_content,
    )
    outcome = runner.run_campaign(document_types=["AIM-PFM", "inspection_procedure"])
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ops.docsreg.docsreg_campaign_runner import CampaignRunner
from ops.docsreg.docsreg_document_type_cycle import DocumentTypeCertificationLoop
from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn

log = logging.getLogger("docsreg_campaign_factory")

# Default evidence root — mirrors CampaignRunner default.
_DEFAULT_EVIDENCE_ROOT = "aims_workspace/docsreg_campaign_evidence"


def build_production_campaign_runner(
    orchestrator: Any,
    evidence_root: str | Path = _DEFAULT_EVIDENCE_ROOT,
    auditor_threshold: float = 0.90,
    max_cycles: int = 10,
    target_quality: float = 0.98,
    document_text: str = "",
) -> CampaignRunner:
    """Construct a fully-wired :class:`CampaignRunner` with the production auditor.

    Parameters
    ----------
    orchestrator:
        A :class:`~ops.docsreg.docsreg_orchestrator.DocsregOrchestrator` or
        any duck-typed equivalent that implements ``start_certification_run()``.
    evidence_root:
        Root directory for campaign evidence output.
    auditor_threshold:
        Completeness ratio required for ``COMPONENT_PASS`` verdict.
        Passed through to :func:`build_structure_auditor_fn`.
    max_cycles:
        Maximum certification cycles per document type before
        ``DOCUMENT_TYPE_MAX_CYCLES_REACHED`` is declared.
    target_quality:
        Quality target forwarded to :class:`DocumentTypeCertificationLoop`.
    document_text:
        Source document content embedded into every run manifest.
        Set to ``""`` when no seed document is available.

    Returns
    -------
    CampaignRunner
        Ready-to-use runner.  Call ``runner.run_campaign()`` to start.
    """
    evidence_root = Path(evidence_root)

    auditor_fn = build_structure_auditor_fn(threshold=auditor_threshold)
    log.info(
        "campaign_factory: auditor built (threshold=%.2f)",
        auditor_threshold,
    )

    loop = DocumentTypeCertificationLoop(
        orchestrator=orchestrator,
        auditor_fn=auditor_fn,
        evidence_root=evidence_root,
        max_cycles=max_cycles,
        target_quality=target_quality,
        document_text=document_text,
    )
    log.info(
        "campaign_factory: loop built (max_cycles=%d target_quality=%.2f)",
        max_cycles,
        target_quality,
    )

    runner = CampaignRunner(
        certification_loop=loop,
        evidence_root=evidence_root,
    )
    log.info("campaign_factory: CampaignRunner ready")
    return runner
