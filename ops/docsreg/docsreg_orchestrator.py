"""
DOCSREG orchestrator — top-level entry point for certification runs.
"""
from __future__ import annotations

import logging
from typing import Any

from ops.docsreg.docsreg_evidence_checkpoint import DocsregEvidenceCheckpoint
from ops.docsreg.docsreg_retry_policy import STANDARD_RETRY, DocsregRetryPolicy
from ops.docsreg.docsreg_run_manifest import DocsregRunManifest
from ops.docsreg.docsreg_scheduler import DocsregRedisScheduler
from ops.docsreg.docsreg_state_machine import DocsregState
from ops.docsreg.docsreg_worker import run_worker

logger = logging.getLogger(__name__)


class DocsregOrchestrator:
    """
    Top-level coordinator for DOCSREG certification runs.

    Constructs a scheduler and evidence checkpoint, seeds the initial
    pipeline state, and delegates execution to :func:`run_worker`.

    Parameters
    ----------
    redis_client:
        Any object providing the Redis duck-typed interface used by
        :class:`DocsregRedisScheduler`.
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def start_certification_run(
        self,
        manifest: DocsregRunManifest,
        retry_policy: DocsregRetryPolicy = STANDARD_RETRY,
    ) -> str:
        """
        Execute a full certification run described by *manifest*.

        Creates a run-scoped scheduler and evidence checkpoint, seeds the
        ``CREATED`` state, then runs all stages via :func:`run_worker`.

        Parameters
        ----------
        manifest:
            Immutable run configuration.
        retry_policy:
            Retry policy forwarded to the worker.

        Returns
        -------
        str
            The final pipeline state after all stages have been processed
            or a terminal/block condition has been reached.
        """
        scheduler = DocsregRedisScheduler(self._redis, manifest.run_id)
        checkpoint = DocsregEvidenceCheckpoint(scheduler)

        scheduler.transition_to(DocsregState.CREATED)
        logger.info(
            "Certification run started: run_id=%s draft=%s",
            manifest.run_id,
            manifest.draft_path,
        )

        final_state = run_worker(manifest, scheduler, checkpoint, retry_policy)
        logger.info(
            "Certification run finished: run_id=%s final_state=%s",
            manifest.run_id,
            final_state,
        )
        return final_state
