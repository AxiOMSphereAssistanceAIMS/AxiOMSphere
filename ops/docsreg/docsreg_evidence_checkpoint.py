"""
DOCSREG evidence checkpoint — creates, persists, and retrieves
:class:`DocsregTaskContract` instances as stage-level evidence records.

Each pipeline stage may call :meth:`DocsregEvidenceCheckpoint.record` to
atomically create a DONE contract, save it to Redis, and get it back.
Contracts can be reloaded later via :meth:`load` or tested for existence
via :meth:`exists`.
"""
from __future__ import annotations

from typing import Any

from ops.docsreg.docsreg_contracts import DocsregTaskContract
from ops.docsreg.docsreg_scheduler import DocsregRedisScheduler


class DocsregEvidenceCheckpoint:
    """
    Wraps the scheduler's contract persistence with a higher-level
    "record this stage as done" API.

    Parameters
    ----------
    scheduler:
        An initialised :class:`DocsregRedisScheduler` for the current run.
        The scheduler's ``_run_id`` is used as the contract's ``run_id``.
    """

    def __init__(self, scheduler: DocsregRedisScheduler) -> None:
        self._scheduler = scheduler

    def record(
        self,
        stage: str,
        input_artifacts: dict[str, str],
        output_artifacts: dict[str, str] | None = None,
        metrics: dict[str, Any] | None = None,
        gates: dict[str, str] | None = None,
    ) -> DocsregTaskContract:
        """
        Create a :class:`DocsregTaskContract` for *stage*, mark it DONE with
        the provided artifacts/metrics/gates, save it to Redis, and return it.

        Parameters
        ----------
        stage:
            Pipeline stage name (e.g. ``"INTAKE"``, ``"EXTRACTION"``).
        input_artifacts:
            Mapping of artifact labels to paths consumed by this stage.
        output_artifacts:
            Mapping of artifact labels to paths produced by this stage.
        metrics:
            Arbitrary key/value metrics recorded for this stage.
        gates:
            Gate name → verdict mapping (e.g. ``{"QUALITY_GATE": "PASS"}``).
        """
        contract = DocsregTaskContract.new(
            run_id=self._scheduler.run_id,
            stage=stage,
            input_artifacts=input_artifacts,
        )
        contract.mark_done(
            output_artifacts=output_artifacts,
            metrics=metrics,
            gates=gates,
        )
        self._scheduler.save_contract(contract)
        return contract

    def load(self, stage: str) -> DocsregTaskContract | None:
        """
        Load and return the saved contract for *stage*.

        Returns ``None`` if no contract has been recorded for that stage.
        """
        return self._scheduler.load_contract(stage)

    def exists(self, stage: str) -> bool:
        """Return ``True`` if a contract has been saved for *stage*."""
        return self._scheduler.load_contract(stage) is not None
