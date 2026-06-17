"""
DOCSREG task registry — maps pipeline stage names to executable task stubs
and defines the stage dependency graph.
"""
from __future__ import annotations

from typing import Callable

from ops.docsreg.docsreg_contracts import DocsregTaskContract
from ops.docsreg.docsreg_evidence_checkpoint import DocsregEvidenceCheckpoint
from ops.docsreg.docsreg_run_manifest import DocsregRunManifest
from ops.docsreg.docsreg_state_machine import DocsregState

# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

TASK_DEPENDENCIES: dict[str, list[str]] = {
    DocsregState.CREATED:                       [],
    DocsregState.INTAKE_READY:                  [DocsregState.CREATED],
    DocsregState.EXTRACTION_READY:              [DocsregState.INTAKE_READY],
    DocsregState.FAMILY_MAP_READY:              [DocsregState.EXTRACTION_READY],
    DocsregState.MASTER_DECISION_READY:         [DocsregState.FAMILY_MAP_READY],
    DocsregState.STRUCTURE_REPAIR_READY:        [DocsregState.MASTER_DECISION_READY],
    DocsregState.REFERENCE_GOVERNANCE_READY:    [DocsregState.STRUCTURE_REPAIR_READY],
    DocsregState.BEST_DRAFT_SYNC_READY:         [DocsregState.REFERENCE_GOVERNANCE_READY],
    DocsregState.TRACEABILITY_READY:            [DocsregState.BEST_DRAFT_SYNC_READY],
    DocsregState.QUALITY_VALIDATED:             [DocsregState.TRACEABILITY_READY],
    DocsregState.REGISTRATION_PRECHECK_READY:   [DocsregState.QUALITY_VALIDATED],
    DocsregState.CERTIFIED_MASTER_READY:        [DocsregState.REGISTRATION_PRECHECK_READY],
    DocsregState.MASTER_REGISTERED:             [DocsregState.CERTIFIED_MASTER_READY],
}

# Type alias for task callables
TaskFn = Callable[[DocsregRunManifest, DocsregEvidenceCheckpoint], DocsregTaskContract]


def dependencies_passed(
    stage: str,
    checkpoint: DocsregEvidenceCheckpoint,
) -> bool:
    """
    Return ``True`` if all dependency stages for *stage* have DONE contracts.

    Parameters
    ----------
    stage:
        The pipeline stage whose dependencies are being checked.
    checkpoint:
        Evidence checkpoint providing contract access.
    """
    for dep in TASK_DEPENDENCIES.get(stage, []):
        contract = checkpoint.load(dep)
        if contract is None or contract.status != "DONE":
            return False
    return True


# ---------------------------------------------------------------------------
# Task stub factory
# ---------------------------------------------------------------------------

def _make_stub(stage: str) -> TaskFn:
    """Return a no-op task function for *stage* that records a DONE contract."""

    def _stub(
        manifest: DocsregRunManifest,
        checkpoint: DocsregEvidenceCheckpoint,
    ) -> DocsregTaskContract:
        return checkpoint.record(
            stage=stage,
            input_artifacts={"draft_path": manifest.draft_path},
            metrics={"stub": True},
        )

    _stub.__name__ = f"task_{stage.lower()}"
    return _stub


# Concrete stubs for the first three stages (illustrate the pattern)
def task_created(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Stub task for the CREATED stage — seeds the run."""
    return checkpoint.record(
        stage=DocsregState.CREATED,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={"stub": True},
    )


def task_intake_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Stub task for the INTAKE_READY stage."""
    return checkpoint.record(
        stage=DocsregState.INTAKE_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={"stub": True},
    )


def task_extraction_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Stub task for the EXTRACTION_READY stage."""
    return checkpoint.record(
        stage=DocsregState.EXTRACTION_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={"stub": True},
    )


# ---------------------------------------------------------------------------
# TASK_REGISTRY — covers all 13 happy-path stages
# ---------------------------------------------------------------------------

TASK_REGISTRY: dict[str, TaskFn] = {
    DocsregState.CREATED:                     task_created,
    DocsregState.INTAKE_READY:                task_intake_ready,
    DocsregState.EXTRACTION_READY:            task_extraction_ready,
    DocsregState.FAMILY_MAP_READY:            _make_stub(DocsregState.FAMILY_MAP_READY),
    DocsregState.MASTER_DECISION_READY:       _make_stub(DocsregState.MASTER_DECISION_READY),
    DocsregState.STRUCTURE_REPAIR_READY:      _make_stub(DocsregState.STRUCTURE_REPAIR_READY),
    DocsregState.REFERENCE_GOVERNANCE_READY:  _make_stub(DocsregState.REFERENCE_GOVERNANCE_READY),
    DocsregState.BEST_DRAFT_SYNC_READY:       _make_stub(DocsregState.BEST_DRAFT_SYNC_READY),
    DocsregState.TRACEABILITY_READY:          _make_stub(DocsregState.TRACEABILITY_READY),
    DocsregState.QUALITY_VALIDATED:           _make_stub(DocsregState.QUALITY_VALIDATED),
    DocsregState.REGISTRATION_PRECHECK_READY: _make_stub(DocsregState.REGISTRATION_PRECHECK_READY),
    DocsregState.CERTIFIED_MASTER_READY:      _make_stub(DocsregState.CERTIFIED_MASTER_READY),
    DocsregState.MASTER_REGISTERED:           _make_stub(DocsregState.MASTER_REGISTERED),
}
