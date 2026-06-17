"""
DOCSREG task contracts — typed, serialisable handshake objects for each pipeline stage.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

TERMINAL_STATUSES: frozenset[str] = frozenset({"DONE", "FAILED"})


@dataclass
class DocsregTaskContract:
    """
    Immutable-ish record that tracks one pipeline stage for a given run.

    Lifecycle
    ---------
    1. Create with ``DocsregTaskContract.new(run_id, stage, input_artifacts)``.
    2. On success call ``mark_done(output_artifacts, metrics, gates)``.
    3. On soft block call ``mark_blocked(error)``.
    4. On hard failure call ``mark_failed(error)``.

    Serialisation
    -------------
    ``to_json()`` / ``from_json()`` give lossless round-trips.
    """

    run_id: str
    stage: str
    input_artifacts: dict[str, str]
    output_artifacts: dict[str, str]
    metrics: dict[str, Any]
    gates: dict[str, str]
    status: str  # "PENDING" | "DONE" | "BLOCKED" | "FAILED"
    error: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        """Serialise the contract to a pretty-printed JSON string."""
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "DocsregTaskContract":
        """Deserialise a contract from a JSON string produced by ``to_json``."""
        data = json.loads(raw)
        return cls(**data)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def new(
        run_id: str,
        stage: str,
        input_artifacts: dict[str, str],
    ) -> "DocsregTaskContract":
        """
        Create a fresh contract in PENDING status.

        ``output_artifacts``, ``metrics``, and ``gates`` are initialised as
        empty dicts; both timestamps are set to the current epoch time.
        """
        now = time.time()
        return DocsregTaskContract(
            run_id=run_id,
            stage=stage,
            input_artifacts=input_artifacts,
            output_artifacts={},
            metrics={},
            gates={},
            status="PENDING",
            error=None,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def mark_done(
        self,
        output_artifacts: dict[str, str] | None = None,
        metrics: dict[str, Any] | None = None,
        gates: dict[str, str] | None = None,
    ) -> None:
        """
        Mark this stage as successfully completed.

        Provided dicts are *merged* into the existing ones so callers can
        supply only the keys they want to update.
        """
        if output_artifacts:
            self.output_artifacts.update(output_artifacts)
        if metrics:
            self.metrics.update(metrics)
        if gates:
            self.gates.update(gates)
        self.status = "DONE"
        self.updated_at = time.time()

    def mark_blocked(self, error: str) -> None:
        """Mark this stage as blocked, requiring external action to resume."""
        self.status = "BLOCKED"
        self.error = error
        self.updated_at = time.time()

    def mark_failed(self, error: str) -> None:
        """Mark this stage as permanently failed."""
        self.status = "FAILED"
        self.error = error
        self.updated_at = time.time()
