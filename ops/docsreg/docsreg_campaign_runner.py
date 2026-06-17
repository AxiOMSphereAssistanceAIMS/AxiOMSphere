"""
DOCSREG certification campaign runner — iterates all enabled document types.

Drives a :class:`DocumentTypeCertificationLoop` sequentially for every enabled
document type registered in the YAML config.  Sequential execution is required
because the underlying pipeline loads large GPU models that cannot run
concurrently on the DGX hardware (VRAM constraint).

Design constraints:
  - Fail-closed per type: an exception in one type's loop is caught and
    recorded as a failed result; the campaign continues for remaining types.
  - Never raises from :meth:`CampaignRunner.run_campaign`.
  - Writes ``campaign_summary.json`` to ``<evidence_root>/<campaign_id>/``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ops.docsreg.docsreg_document_type_registry import get_enabled_document_type_ids
from ops.docsreg.docsreg_document_type_cycle import (
    OUTCOME_CERTIFIED,
    OUTCOME_STALLED,
    DocumentTypeCertificationLoop,
    DocumentTypeCycleOutcome,
)

log = logging.getLogger("docsreg_campaign_runner")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CampaignResult:
    """Result for a single document type within a campaign.

    Attributes
    ----------
    document_type : str
        The document type identifier (e.g. ``"procedure"``).
    outcome : str
        One of the OUTCOME_* constants from
        :mod:`ops.docsreg.docsreg_document_type_cycle`.
    passed : bool
        True when the document type was certified.
    cycles_run : int
        Number of fresh-start cycles executed for this type.
    best_quality : float
        Highest quality score achieved across all cycles.
    evidence_dir : str
        Path to the per-type evidence directory.
    notes : str
        Human-readable context for the outcome.
    """

    document_type: str
    outcome: str
    passed: bool
    cycles_run: int
    best_quality: float
    evidence_dir: str
    notes: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        return {
            "document_type": self.document_type,
            "outcome": self.outcome,
            "passed": self.passed,
            "cycles_run": self.cycles_run,
            "best_quality": self.best_quality,
            "evidence_dir": self.evidence_dir,
            "notes": self.notes,
        }


@dataclass
class CampaignOutcome:
    """Aggregated outcome after running all document types in a campaign.

    Attributes
    ----------
    campaign_id : str
        Unique identifier of the form ``campaign_YYYYMMDD_HHMMSS``.
    started_at : str
        ISO-8601 UTC timestamp when the campaign started.
    finished_at : str
        ISO-8601 UTC timestamp when the campaign finished.
    total_types : int
        Number of document types attempted.
    certified_count : int
        Number of document types that were certified.
    failed_count : int
        Number of document types that were not certified.
    results : list[CampaignResult]
        Per-type results in the order they were run.
    evidence_root : str
        Root evidence directory for this campaign.
    notes : str
        Human-readable context for the overall campaign outcome.
    """

    campaign_id: str
    started_at: str
    finished_at: str
    total_types: int
    certified_count: int
    failed_count: int
    results: list[CampaignResult] = field(default_factory=list)
    evidence_root: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        return {
            "campaign_id": self.campaign_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_types": self.total_types,
            "certified_count": self.certified_count,
            "failed_count": self.failed_count,
            "results": [r.to_dict() for r in self.results],
            "evidence_root": self.evidence_root,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        """Return the outcome as a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def all_certified(self) -> bool:
        """Return True only when every attempted type was certified.

        Returns ``False`` when ``total_types == 0`` (no types were attempted).
        """
        return self.certified_count == self.total_types and self.total_types > 0


# ---------------------------------------------------------------------------
# Campaign runner
# ---------------------------------------------------------------------------


class CampaignRunner:
    """Runs a certification campaign across all enabled document types.

    Iterates enabled document types sequentially — one type at a time — to
    respect the GPU VRAM constraint (no two large models loaded in parallel).

    For each type the runner:
    1. Routes the certification loop's evidence to
       ``<evidence_root>/<campaign_id>/<document_type>/`` by mutating
       ``_loop._evidence_root``.
    2. Delegates to :meth:`DocumentTypeCertificationLoop.run_document_type`.
    3. Records the result in the campaign outcome.

    After all types are processed, writes ``campaign_summary.json`` to
    ``<evidence_root>/<campaign_id>/``.

    Parameters
    ----------
    certification_loop : DocumentTypeCertificationLoop
        Pre-configured loop instance.  Its ``_evidence_root`` attribute is
        mutated for each campaign run.
    evidence_root : str | Path
        Root directory under which campaign evidence is written.  A
        ``<campaign_id>/`` sub-directory is created automatically.
    config_path : str | Path | None
        Override path to the YAML config file.  When ``None``, the default
        path from :func:`get_enabled_document_type_ids` is used.
    """

    def __init__(
        self,
        certification_loop: DocumentTypeCertificationLoop,
        evidence_root: str | Path = "aims_workspace/docsreg_campaign_evidence",
        config_path: str | Path | None = None,
    ) -> None:
        self._loop = certification_loop
        self._evidence_root = Path(evidence_root)
        self._config_path = config_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_campaign(
        self,
        document_types: list[str] | None = None,
    ) -> CampaignOutcome:
        """Run a certification campaign for all enabled document types.

        Parameters
        ----------
        document_types : list[str] | None
            Explicit list of document type IDs to certify.  When ``None``,
            loads the enabled types from the YAML registry via
            :func:`get_enabled_document_type_ids`.

        Returns
        -------
        CampaignOutcome
            Full campaign outcome with per-type results.  Never raises.
        """
        try:
            return self._run_campaign_inner(document_types)
        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            log.error("CampaignRunner.run_campaign: unexpected error: %s", exc)
            ts = _utc_now_iso()
            return CampaignOutcome(
                campaign_id=_make_campaign_id(),
                started_at=ts,
                finished_at=ts,
                total_types=0,
                certified_count=0,
                failed_count=0,
                notes=f"unexpected error: {exc}",
            )

    # ------------------------------------------------------------------
    # Inner implementation
    # ------------------------------------------------------------------

    def _run_campaign_inner(
        self,
        document_types: list[str] | None,
    ) -> CampaignOutcome:
        campaign_id = _make_campaign_id()
        started_at = _utc_now_iso()
        campaign_run_dir = self._evidence_root / campaign_id

        log.info("CampaignRunner: starting campaign %s", campaign_id)

        # Resolve types to certify
        if document_types is None:
            types_to_run = get_enabled_document_type_ids(self._config_path)
        else:
            types_to_run = list(document_types)

        if not types_to_run:
            finished_at = _utc_now_iso()
            log.warning("CampaignRunner: no enabled document types found — campaign skipped")
            return CampaignOutcome(
                campaign_id=campaign_id,
                started_at=started_at,
                finished_at=finished_at,
                total_types=0,
                certified_count=0,
                failed_count=0,
                evidence_root=str(campaign_run_dir),
                notes="no enabled document types found",
            )

        # Route loop evidence to campaign sub-directory
        self._loop._evidence_root = campaign_run_dir

        results: list[CampaignResult] = []

        for doc_type in types_to_run:
            log.info("CampaignRunner: certifying document type %r", doc_type)
            result = self._certify_one_type(doc_type)
            results.append(result)

        certified_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - certified_count
        finished_at = _utc_now_iso()

        outcome = CampaignOutcome(
            campaign_id=campaign_id,
            started_at=started_at,
            finished_at=finished_at,
            total_types=len(results),
            certified_count=certified_count,
            failed_count=failed_count,
            results=results,
            evidence_root=str(campaign_run_dir),
            notes=(
                "all types certified"
                if certified_count == len(results)
                else f"{certified_count}/{len(results)} types certified"
            ),
        )

        _write_campaign_summary(campaign_run_dir, outcome)

        log.info(
            "CampaignRunner: campaign %s complete — %d/%d certified",
            campaign_id,
            certified_count,
            len(results),
        )
        return outcome

    def _certify_one_type(self, doc_type: str) -> CampaignResult:
        """Run the certification loop for one document type.  Never raises."""
        try:
            cycle_outcome: DocumentTypeCycleOutcome = self._loop.run_document_type(
                document_type=doc_type,
            )
            return CampaignResult(
                document_type=doc_type,
                outcome=cycle_outcome.outcome,
                passed=cycle_outcome.passed,
                cycles_run=cycle_outcome.cycles_run,
                best_quality=cycle_outcome.best_quality,
                evidence_dir=cycle_outcome.evidence_dir,
                notes=cycle_outcome.notes,
            )
        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            log.error(
                "CampaignRunner: unexpected error certifying %r: %s", doc_type, exc
            )
            return CampaignResult(
                document_type=doc_type,
                outcome=OUTCOME_STALLED,
                passed=False,
                cycles_run=0,
                best_quality=0.0,
                evidence_dir="",
                notes=f"unexpected error: {exc}",
            )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _make_campaign_id() -> str:
    """Return a unique campaign identifier of the form ``campaign_YYYYMMDD_HHMMSS``."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"campaign_{ts}"


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _write_campaign_summary(campaign_run_dir: Path, outcome: CampaignOutcome) -> None:
    """Write ``campaign_summary.json`` to *campaign_run_dir*.  Never raises."""
    try:
        campaign_run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = campaign_run_dir / "campaign_summary.json"
        summary_path.write_text(outcome.to_json(), encoding="utf-8")
        log.info("CampaignRunner: campaign summary written to %s", summary_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("CampaignRunner: could not write campaign summary: %s", exc)
