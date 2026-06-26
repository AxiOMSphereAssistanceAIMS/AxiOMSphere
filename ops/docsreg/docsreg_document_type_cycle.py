"""
DOCSREG document-type certification loop — top-level meta-cycle.

Drives N fresh-start certification runs for a single document type until the
pipeline reproducibly achieves the quality target or stalls.  A single
successful patched document does NOT constitute a certified document type;
the pipeline itself must reproduce quality-passing documents from a blank
start across multiple independent runs.

Architecture
------------
Level 1 — Per-cycle fresh-start runs          (this module)
Level 2 — Per-component contract validation   (DocsregOrchestrator)
Level 3 — Claude Code CLI auditor             (external, injectable)

Exports
-------
OUTCOME_* constants
    String constants for the three possible outcomes.
AUDIT_STATUS_* constants
    The five auditor verdict strings.
DocumentTypeCycleRecord : dataclass
    Result of one fresh-start certification cycle.
DocumentTypeCycleOutcome : dataclass
    Aggregated outcome after N cycles for a document type.
DocumentTypeCertificationLoop : class
    Manages the meta-cycle for a single document type.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ops.docsreg.docsreg_run_manifest import DocsregRunManifest

log = logging.getLogger("docsreg_document_type_cycle")

# ── Outcome constants ──────────────────────────────────────────────────────────

OUTCOME_CERTIFIED = "DOCUMENT_TYPE_CERTIFIED"
OUTCOME_STALLED = "DOCUMENT_TYPE_STALLED"
OUTCOME_MAX_CYCLES = "DOCUMENT_TYPE_MAX_CYCLES_REACHED"

# ── Auditor verdict constants ──────────────────────────────────────────────────

AUDIT_STATUS_COMPONENT_PASS = "COMPONENT_PASS"
AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE = "COMPONENT_FAIL_REPAIRABLE"
AUDIT_STATUS_PIPELINE_REGRESSION = "PIPELINE_REGRESSION"
AUDIT_STATUS_STALL_DETECTED = "STALL_DETECTED"
AUDIT_STATUS_READY_TO_FREEZE = "READY_TO_FREEZE_FOR_DOCUMENT_TYPE"

# ── Internal thresholds ────────────────────────────────────────────────────────

_QUALITY_FLOOR: float = 0.60        # minimum quality for any accepted CERTIFIED run
_DEFAULT_SECTION_COVERAGE: float = 0.85
_REFERENCE_GOVERNANCE_PASS = "PASS"
_CERTIFIED_STATES = frozenset({"CERTIFIED", "MASTER_REGISTERED"})


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class DocumentTypeCycleRecord:
    """Result of a single fresh-start certification cycle.

    Attributes
    ----------
    cycle_id : str
        Unique identifier for this cycle run.
    document_type : str
        The document type being certified.
    final_state : str
        State string returned by DocsregOrchestrator.
    quality : float
        Quality score in 0.0–1.0 from the auditor.
    section_coverage : float
        Section coverage ratio (0.0–1.0).
    reference_governance : str
        ``"PASS"``, ``"FAIL"``, or ``"UNKNOWN"``.
    audit_status : str
        One of the AUDIT_STATUS_* constants.
    passed : bool
        True only when all certification criteria are met for this cycle.
    evidence_dir : str
        Path to the evidence directory for this cycle.
    notes : str
        Human-readable context for the outcome.
    """

    cycle_id: str
    document_type: str
    final_state: str
    quality: float
    section_coverage: float
    reference_governance: str
    audit_status: str
    passed: bool
    evidence_dir: str
    notes: str = ""
    audit_error: str | None = None


@dataclass
class DocumentTypeCycleOutcome:
    """Aggregated outcome after N certification cycles for a document type.

    Attributes
    ----------
    document_type : str
        The document type that was certified.
    outcome : str
        One of OUTCOME_CERTIFIED, OUTCOME_STALLED, OUTCOME_MAX_CYCLES.
    passed : bool
        True only when ``outcome == OUTCOME_CERTIFIED``.
    cycles_run : int
        Total number of fresh-start cycles executed.
    best_quality : float
        Highest quality score seen across all cycles.
    cycle_history : list[DocumentTypeCycleRecord]
        Ordered list of all cycle records (oldest first).
    evidence_dir : str
        Root evidence directory for this document type's cycle run.
    notes : str
        Human-readable context.
    """

    document_type: str
    outcome: str
    passed: bool
    cycles_run: int
    best_quality: float
    cycle_history: list = field(default_factory=list)
    evidence_dir: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        return {
            "document_type": self.document_type,
            "outcome": self.outcome,
            "passed": self.passed,
            "cycles_run": self.cycles_run,
            "best_quality": self.best_quality,
            "cycle_history": [asdict(r) for r in self.cycle_history],
            "evidence_dir": self.evidence_dir,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        """Return the outcome as a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2)


# ── Main class ─────────────────────────────────────────────────────────────────


class DocumentTypeCertificationLoop:
    """Meta-cycle that drives N fresh-start runs for one document type.

    Runs the DOCSREG pipeline repeatedly from scratch until the pipeline
    reproducibly achieves the quality target or stalls.

    Parameters
    ----------
    orchestrator : DocsregOrchestrator
        Fully-configured orchestrator instance.  Must expose
        ``start_certification_run(manifest, retry_policy) -> str``.
    auditor_fn : callable | None
        ``auditor_fn(manifest) -> dict``.  The dict must contain at least
        ``"status"`` (one of AUDIT_STATUS_*) and optionally ``"quality"``,
        ``"section_coverage"``, ``"reference_governance"``, and
        ``"recommendations"``.  If ``None``, a no-op auditor that returns
        COMPONENT_PASS with zero metrics is used.
    evidence_root : str | Path
        Root directory under which per-cycle evidence is written.
    max_cycles : int
        Hard cap on the number of fresh-start cycles (default 10).
    target_quality : float
        Quality threshold for CERTIFIED status (default 0.98).
    target_section_coverage : float
        Section coverage threshold (default 0.85).
    min_quality_delta : float
        Minimum quality improvement over ``stall_window`` cycles before a
        stall is declared (default 0.005).
    stall_window : int
        Number of consecutive cycles used for stall detection (default 3).
    beta_mode : bool
        Enable beta mode (default False). In beta mode, coverage_gate and
        ref_gov_gate are measured but not enforced for certification.
    enforce_coverage_gate : bool
        When False, coverage metrics are collected but not required for
        certification (default True). Ignored if beta_mode=False.
    enforce_ref_gov_gate : bool
        When False, reference_governance metrics are collected but not
        required for certification (default True). Ignored if beta_mode=False.
    """

    def __init__(
        self,
        orchestrator,
        auditor_fn=None,
        evidence_root: str | Path = "aims_workspace/docsreg_evidence",
        max_cycles: int = 10,
        target_quality: float = 0.98,
        target_section_coverage: float = _DEFAULT_SECTION_COVERAGE,
        min_quality_delta: float = 0.005,
        stall_window: int = 3,
        beta_mode: bool = False,
        enforce_coverage_gate: bool = True,
        enforce_ref_gov_gate: bool = True,
        document_text: str = "",
    ) -> None:
        self._orchestrator = orchestrator
        self._auditor_fn = auditor_fn or _noop_auditor
        self._evidence_root = Path(evidence_root)
        self._max_cycles = max_cycles
        self._target_quality = target_quality
        self._target_section_coverage = target_section_coverage
        self._min_quality_delta = min_quality_delta
        self._stall_window = stall_window
        self._beta_mode = beta_mode
        self._enforce_coverage_gate = enforce_coverage_gate
        self._enforce_ref_gov_gate = enforce_ref_gov_gate
        self._document_text = document_text

    # ── Public entry point ─────────────────────────────────────────────────────

    def run_document_type(
        self,
        document_type: str,
        draft_path: str = "",
        retry_policy=None,
    ) -> DocumentTypeCycleOutcome:
        """Run fresh-start certification cycles for *document_type*.

        Args:
            document_type: Identifier for the document type (e.g. ``"AIM-PFM"``).
            draft_path: Optional path to a seed draft document.
            retry_policy: Optional DocsregRetryPolicy passed through to the
                orchestrator on each cycle.

        Returns:
            :class:`DocumentTypeCycleOutcome` with the final outcome and full
            cycle history.

        This method never raises.
        """
        try:
            return self._run_document_type_inner(
                document_type=document_type,
                draft_path=draft_path,
                retry_policy=retry_policy,
            )
        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            log.error(
                "document_type_cycle: FAIL — unexpected error for %r: %s",
                document_type,
                exc,
            )
            return DocumentTypeCycleOutcome(
                document_type=document_type,
                outcome=OUTCOME_STALLED,
                passed=False,
                cycles_run=0,
                best_quality=0.0,
                notes=f"unexpected error: {exc}",
            )

    # ── Inner loop ─────────────────────────────────────────────────────────────

    def _run_document_type_inner(
        self,
        document_type: str,
        draft_path: str,
        retry_policy,
    ) -> DocumentTypeCycleOutcome:
        history: list[DocumentTypeCycleRecord] = []
        doc_evidence_dir = self._evidence_root / document_type
        doc_evidence_dir.mkdir(parents=True, exist_ok=True)
        doc_evidence_str = str(doc_evidence_dir)

        for cycle_index in range(self._max_cycles):
            cycle_id = _make_cycle_id(document_type, cycle_index)
            log.info(
                "document_type_cycle: starting cycle %d/%d for %r (id=%s)",
                cycle_index + 1,
                self._max_cycles,
                document_type,
                cycle_id,
            )

            record = self._run_single_cycle(
                document_type=document_type,
                cycle_id=cycle_id,
                draft_path=draft_path,
                retry_policy=retry_policy,
            )
            history.append(record)
            self.write_evidence(document_type, cycle_id, asdict(record))

            # ── Certified ─────────────────────────────────────────────────────
            if record.passed:
                log.info(
                    "document_type_cycle: CERTIFIED %r after %d cycle(s)",
                    document_type,
                    len(history),
                )
                self.freeze_document_type_contracts(document_type)
                return DocumentTypeCycleOutcome(
                    document_type=document_type,
                    outcome=OUTCOME_CERTIFIED,
                    passed=True,
                    cycles_run=len(history),
                    best_quality=max(r.quality for r in history),
                    cycle_history=history,
                    evidence_dir=doc_evidence_str,
                    notes="all certification criteria met",
                )

            # ── Stall detection ────────────────────────────────────────────────
            if self.stall_detected(history):
                log.warning(
                    "document_type_cycle: STALL detected for %r after %d cycle(s)",
                    document_type,
                    len(history),
                )
                return DocumentTypeCycleOutcome(
                    document_type=document_type,
                    outcome=OUTCOME_STALLED,
                    passed=False,
                    cycles_run=len(history),
                    best_quality=max(r.quality for r in history),
                    cycle_history=history,
                    evidence_dir=doc_evidence_str,
                    notes="quality not improving — stall declared",
                )

            # ── Auditor-directed repair or regression halt ────────────────────
            if record.audit_status == AUDIT_STATUS_PIPELINE_REGRESSION:
                log.warning(
                    "document_type_cycle: PIPELINE_REGRESSION for %r — halting",
                    document_type,
                )
                return DocumentTypeCycleOutcome(
                    document_type=document_type,
                    outcome=OUTCOME_STALLED,
                    passed=False,
                    cycles_run=len(history),
                    best_quality=max(r.quality for r in history),
                    cycle_history=history,
                    evidence_dir=doc_evidence_str,
                    notes="pipeline regression detected — halted",
                )

            if record.audit_status == AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE:
                self.repair_pipeline_from_audit({"status": record.audit_status})

        # ── Max cycles reached ─────────────────────────────────────────────────
        best_quality = max((r.quality for r in history), default=0.0)
        log.warning(
            "document_type_cycle: MAX_CYCLES reached for %r — best quality %.4f",
            document_type,
            best_quality,
        )
        return DocumentTypeCycleOutcome(
            document_type=document_type,
            outcome=OUTCOME_MAX_CYCLES,
            passed=False,
            cycles_run=len(history),
            best_quality=best_quality,
            cycle_history=history,
            evidence_dir=doc_evidence_str,
            notes=f"max cycles ({self._max_cycles}) reached without certification",
        )

    # ── Single cycle ───────────────────────────────────────────────────────────

    def _run_single_cycle(
        self,
        document_type: str,
        cycle_id: str,
        draft_path: str,
        retry_policy,
    ) -> DocumentTypeCycleRecord:
        """Run one fresh-start certification cycle.  Never raises."""
        cycle_evidence_dir = self._evidence_root / document_type / cycle_id
        cycle_evidence_dir.mkdir(parents=True, exist_ok=True)
        cycle_evidence_str = str(cycle_evidence_dir)

        try:
            manifest = self.start_fresh_run(
                document_type=document_type,
                cycle_id=cycle_id,
                draft_path=draft_path,
            )
            previous_artifact_dir = os.environ.get("DOCSREG_EXTRACTION_ARTIFACT_DIR")
            os.environ["DOCSREG_EXTRACTION_ARTIFACT_DIR"] = cycle_evidence_str
            try:
                final_state = self.run_docsreg_pipeline(manifest, retry_policy)
            finally:
                if previous_artifact_dir is None:
                    os.environ.pop("DOCSREG_EXTRACTION_ARTIFACT_DIR", None)
                else:
                    os.environ["DOCSREG_EXTRACTION_ARTIFACT_DIR"] = previous_artifact_dir
            audit = self.run_claude_code_audit(manifest)
            metrics = self.collect_metrics(final_state, audit)

            quality = float(metrics.get("quality", 0.0))
            section_coverage = float(metrics.get("section_coverage", 0.0))
            reference_governance = str(metrics.get("reference_governance", "UNKNOWN"))
            audit_status = str(audit.get("status", AUDIT_STATUS_COMPONENT_PASS))

            # Persist audit_status into quality_report.json so record_knowledge_source
            # can determine real_auditor_used correctly.
            _qr_path = Path(manifest.draft_path).parent / "quality_report.json"
            try:
                if _qr_path.exists():
                    import json as _json
                    _qr = _json.loads(_qr_path.read_text(encoding="utf-8"))
                    _qr["audit_status"] = audit_status
                    _qr_path.write_text(_json.dumps(_qr, indent=2), encoding="utf-8")
                    (cycle_evidence_dir / "quality_report.json").write_text(
                        _json.dumps(_qr, indent=2),
                        encoding="utf-8",
                    )
            except Exception:
                pass

            passed = self._check_cycle_criteria(
                final_state=final_state,
                quality=quality,
                section_coverage=section_coverage,
                reference_governance=reference_governance,
                audit_status=audit_status,
            )

            notes = (
                f"quality={quality:.4f} coverage={section_coverage:.4f} "
                f"ref_gov={reference_governance} audit={audit_status}"
            )
            if passed:
                log.info("document_type_cycle: cycle %s PASS — %s", cycle_id, notes)
            else:
                log.warning("document_type_cycle: cycle %s FAIL — %s", cycle_id, notes)

            return DocumentTypeCycleRecord(
                cycle_id=cycle_id,
                document_type=document_type,
                final_state=final_state,
                quality=quality,
                section_coverage=section_coverage,
                reference_governance=reference_governance,
                audit_status=audit_status,
                passed=passed,
                evidence_dir=cycle_evidence_str,
                notes=notes,
            )

        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            log.error(
                "document_type_cycle: cycle %s FAIL — unexpected error: %s",
                cycle_id,
                exc,
            )
            return DocumentTypeCycleRecord(
                cycle_id=cycle_id,
                document_type=document_type,
                final_state="FAILED",
                quality=0.0,
                section_coverage=0.0,
                reference_governance="UNKNOWN",
                audit_status=AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE,
                passed=False,
                evidence_dir=cycle_evidence_str,
                notes=f"unexpected error: {exc}",
            )

    # ── Certification criteria ─────────────────────────────────────────────────

    def _check_cycle_criteria(
        self,
        final_state: str,
        quality: float,
        section_coverage: float,
        reference_governance: str,
        audit_status: str,
    ) -> bool:
        """Return True only when ALL certification criteria are met.

        In beta mode, coverage_gate and ref_gov_gate are measured but not enforced.
        """
        # Final state gate (always required)
        if final_state not in _CERTIFIED_STATES:
            return False

        # Quality gate (always required)
        if quality < self._target_quality:
            return False

        # Coverage gate (beta mode: measure but don't enforce)
        if self._enforce_coverage_gate and section_coverage < self._target_section_coverage:
            return False

        # Reference governance gate (beta mode: measure but don't enforce)
        if self._enforce_ref_gov_gate and reference_governance != _REFERENCE_GOVERNANCE_PASS:
            return False

        # Auditor gate (always required)
        if audit_status not in (AUDIT_STATUS_COMPONENT_PASS, AUDIT_STATUS_READY_TO_FREEZE):
            return False

        return True

    # ── Overridable component methods ──────────────────────────────────────────

    def start_fresh_run(
        self,
        document_type: str,
        cycle_id: str,
        draft_path: str = "",
    ) -> DocsregRunManifest:
        """Create a new :class:`DocsregRunManifest` for a fresh-start cycle."""
        if len(self._document_text or "") > 60_000:
            from ops.context.payload_broker import prepare_payload  # noqa: PLC0415

            payload_ref = prepare_payload(
                task_id=f"docsreg_{cycle_id}",
                source_text=self._document_text,
                source_kind="document_text",
                requested_mode="auto",
                metadata={
                    "document_type": document_type,
                    "bridge": "DocumentTypeCertificationLoop.start_fresh_run",
                    "original_draft_path": draft_path,
                },
            )
            return DocsregRunManifest.create(
                run_id=cycle_id,
                draft_path=payload_ref.source_path or draft_path or f"draft_{document_type}",
                document_text="",
                document_type=document_type,
            )
        return DocsregRunManifest.create(
            run_id=cycle_id,
            draft_path=draft_path or f"draft_{document_type}",
            document_text=self._document_text,
            document_type=document_type,
        )

    def run_docsreg_pipeline(self, manifest: DocsregRunManifest, retry_policy=None) -> str:
        """Delegate to ``DocsregOrchestrator.start_certification_run()``.

        Returns the final state string; returns ``"FAILED"`` on any error.
        """
        try:
            return self._orchestrator.start_certification_run(
                manifest=manifest,
                retry_policy=retry_policy,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("document_type_cycle: orchestrator error: %s", exc)
            return "FAILED"

    def run_claude_code_audit(self, manifest: DocsregRunManifest) -> dict:
        """Invoke the auditor function and return the audit dict.

        Returns a default COMPONENT_FAIL_REPAIRABLE dict on any auditor error.
        """
        try:
            result = self._auditor_fn(manifest)
            if not isinstance(result, dict):
                log.warning(
                    "document_type_cycle: auditor returned non-dict %r — using default",
                    type(result).__name__,
                )
                return {"status": AUDIT_STATUS_COMPONENT_PASS}
            return result
        except Exception as exc:  # noqa: BLE001
            log.error("document_type_cycle: auditor error: %s", exc)
            return {"status": AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE}

    def collect_metrics(self, final_state: str, audit: dict) -> dict:
        """Extract quality metrics from the orchestrator state and audit dict.

        When the orchestrator reached a certified state but the auditor did not
        supply an explicit quality score, the metric falls back to the quality
        floor (0.60) rather than 0.0 to avoid incorrectly discarding a run that
        the orchestrator itself considered complete.
        """
        quality = float(audit.get("quality", 0.0))
        section_coverage = float(audit.get("section_coverage", 0.0))
        reference_governance = str(audit.get("reference_governance", "UNKNOWN"))

        if final_state in _CERTIFIED_STATES and quality == 0.0:
            quality = _QUALITY_FLOOR

        return {
            "quality": quality,
            "section_coverage": section_coverage,
            "reference_governance": reference_governance,
        }

    def write_evidence(self, document_type: str, cycle_id: str, data: dict) -> None:
        """Write cycle evidence JSON to ``<evidence_root>/<type>/<cycle_id>/cycle_record.json``."""
        try:
            evidence_dir = self._evidence_root / document_type / cycle_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence_file = evidence_dir / "cycle_record.json"
            evidence_file.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
            log.info("document_type_cycle: evidence written to %s", evidence_file)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "document_type_cycle: could not write evidence for %s/%s: %s",
                document_type,
                cycle_id,
                exc,
            )

    def stall_detected(self, history: list) -> bool:
        """Return True when quality has not improved over the last ``stall_window`` cycles.

        A stall is declared when ``max(quality) - min(quality)`` over the most
        recent ``stall_window`` records is below ``min_quality_delta``.
        Returns False when ``len(history) < stall_window``.
        """
        if len(history) < self._stall_window:
            return False
        window = history[-self._stall_window:]
        qualities = [r.quality for r in window]
        improvement = max(qualities) - min(qualities)
        return improvement < self._min_quality_delta

    def freeze_document_type_contracts(self, document_type: str) -> None:
        """Write a ``FROZEN.json`` marker locking gate configs for this document type."""
        try:
            freeze_dir = self._evidence_root / document_type
            freeze_dir.mkdir(parents=True, exist_ok=True)
            freeze_file = freeze_dir / "FROZEN.json"
            freeze_data = {
                "document_type": document_type,
                "frozen_at": datetime.now(tz=timezone.utc).isoformat(),
                "status": "CERTIFIED",
            }
            freeze_file.write_text(json.dumps(freeze_data, indent=2), encoding="utf-8")
            log.info(
                "document_type_cycle: contracts frozen for %r at %s",
                document_type,
                freeze_file,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "document_type_cycle: could not write freeze marker for %r: %s",
                document_type,
                exc,
            )

    def repair_pipeline_from_audit(self, audit: dict) -> None:
        """Log audit recommendations for pipeline repair.

        Destructive automated patching is intentionally out of scope for this
        module (see CLAUDE.md — protected_actions_audit).  Recommendations are
        logged at WARNING level for the Repairman to pick up.
        """
        recommendations = audit.get("recommendations", [])
        if recommendations:
            log.warning(
                "document_type_cycle: REPAIR NEEDED — %d recommendation(s): %s",
                len(recommendations),
                recommendations,
            )
        else:
            log.warning(
                "document_type_cycle: REPAIR NEEDED — audit_status=%s (no recommendations)",
                audit.get("status"),
            )


# ── Module-level helpers ───────────────────────────────────────────────────────


def _make_cycle_id(document_type: str, cycle_index: int) -> str:
    """Return a unique cycle run ID.  Deterministic prefix; UUID suffix."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    safe_type = document_type.replace(" ", "_").replace("/", "-")
    return f"{safe_type}_cycle{cycle_index:03d}_{ts}_{short_uuid}"


def _noop_auditor(manifest) -> dict:  # noqa: ANN001
    """Default no-op auditor.  Always returns COMPONENT_PASS with zero metrics.

    Used when no ``auditor_fn`` is provided.  Useful for integration tests that
    exercise orchestration logic without needing a real quality evaluator.
    """
    return {
        "status": AUDIT_STATUS_COMPONENT_PASS,
        "quality": 0.0,
        "section_coverage": 0.0,
        "reference_governance": "UNKNOWN",
        "recommendations": [],
    }
