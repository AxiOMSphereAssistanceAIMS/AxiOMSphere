"""
DOCSREG run manifest — immutable configuration for one certification run.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from ops.docsreg.docsreg_state_machine import DocsregState

_HAPPY_PATH_STAGES: list[str] = [
    DocsregState.CREATED,
    DocsregState.INTAKE_READY,
    DocsregState.EXTRACTION_READY,
    DocsregState.FAMILY_MAP_READY,
    DocsregState.MASTER_DECISION_READY,
    DocsregState.STRUCTURE_REPAIR_READY,
    DocsregState.REFERENCE_GOVERNANCE_READY,
    DocsregState.BEST_DRAFT_SYNC_READY,
    DocsregState.TRACEABILITY_READY,
    DocsregState.QUALITY_VALIDATED,
    DocsregState.REGISTRATION_PRECHECK_READY,
    DocsregState.CERTIFIED_MASTER_READY,
    DocsregState.MASTER_REGISTERED,
]


@dataclass
class DocsregRunManifest:
    """
    Immutable configuration for a single DOCSREG certification run.

    Parameters
    ----------
    run_id:
        Unique identifier for this run (e.g. UUID or timestamp string).
    draft_path:
        Path to the source document being certified.
    stages:
        Ordered list of stage names to execute.
    write_policy:
        One of ``"OVERWRITE"``, ``"FAIL_IF_EXISTS"``, ``"SKIP_IF_EXISTS"``.
        Controls behaviour when a stage contract already exists in Redis.
    created_at:
        Epoch timestamp; set automatically by :meth:`create`.
    document_text:
        Source document text for auditor input contract validation.
    document_type:
        Document type identifier (e.g. ``"Procedure"``).
    """

    run_id: str
    draft_path: str
    stages: list[str]
    write_policy: str
    created_at: float
    document_text: str = ""
    document_type: str = ""

    @classmethod
    def create(
        cls,
        run_id: str,
        draft_path: str,
        stages: list[str] | None = None,
        write_policy: str = "FAIL_IF_EXISTS",
        document_text: str = "",
        document_type: str = "",
    ) -> "DocsregRunManifest":
        """
        Factory that builds a manifest with the current timestamp.

        If *stages* is ``None`` the full happy-path stage list is used.
        """
        return cls(
            run_id=run_id,
            draft_path=draft_path,
            stages=list(stages) if stages is not None else list(_HAPPY_PATH_STAGES),
            write_policy=write_policy,
            created_at=time.time(),
            document_text=document_text,
            document_type=document_type,
        )

    def to_json(self) -> str:
        """Serialise the manifest to a JSON string."""
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "DocsregRunManifest":
        """Deserialise a manifest from a JSON string produced by :meth:`to_json`."""
        data = json.loads(raw)
        return cls(**data)
