"""
DOCSREG worker — main execution loop that drives the certification pipeline.
"""
from __future__ import annotations

import logging
import time

from ops.docsreg.docsreg_evidence_checkpoint import DocsregEvidenceCheckpoint
from ops.docsreg.docsreg_retry_policy import STANDARD_RETRY, DocsregRetryPolicy
from ops.docsreg.docsreg_run_manifest import DocsregRunManifest
from ops.docsreg.docsreg_scheduler import DocsregRedisScheduler
from ops.docsreg.docsreg_state_machine import DocsregState
from ops.docsreg.docsreg_tasks import TASK_REGISTRY, dependencies_passed

logger = logging.getLogger(__name__)


def run_worker(
    manifest: DocsregRunManifest,
    scheduler: DocsregRedisScheduler,
    checkpoint: DocsregEvidenceCheckpoint,
    retry_policy: DocsregRetryPolicy = STANDARD_RETRY,
    *,
    max_stall_seconds: float = 120.0,
) -> str:
    """
    Execute all stages in *manifest* in order, returning the final state string.

    Parameters
    ----------
    manifest:
        Run configuration including stage list and write policy.
    scheduler:
        Redis scheduler for state transitions and error recording.
    checkpoint:
        Evidence checkpoint for contract persistence.
    retry_policy:
        Retry policy used on task exceptions.
    max_stall_seconds:
        Reserved for future stall detection integration.

    Returns
    -------
    str
        The final state string after processing all stages or encountering
        a terminal failure/block condition.
    """
    last_state: str = scheduler.get_state() or DocsregState.CREATED

    for stage in manifest.stages:
        # --- Write-policy gate ---
        if checkpoint.exists(stage):
            if manifest.write_policy == "SKIP_IF_EXISTS":
                logger.debug("Skipping existing stage: %s", stage)
                last_state = stage
                continue
            if manifest.write_policy == "FAIL_IF_EXISTS":
                msg = f"Stage {stage!r} already recorded; write_policy=FAIL_IF_EXISTS"
                scheduler.record_error(msg)
                scheduler.transition_to(DocsregState.FAILED)
                logger.warning(msg)
                return DocsregState.FAILED

        # --- Dependency gate ---
        if not dependencies_passed(stage, checkpoint):
            msg = f"Dependencies not met for stage {stage!r}"
            scheduler.record_error(msg)
            scheduler.transition_to(DocsregState.BLOCKED_REQUIRES_RESOURCE)
            logger.warning(msg)
            return DocsregState.BLOCKED_REQUIRES_RESOURCE

        # --- Task lookup ---
        task_fn = TASK_REGISTRY.get(stage)
        if task_fn is None:
            msg = f"No task registered for stage {stage!r}"
            scheduler.record_error(msg)
            scheduler.transition_to(DocsregState.FAILED)
            logger.error(msg)
            return DocsregState.FAILED

        # --- Execution with retry ---
        attempt = 1
        while True:
            try:
                task_fn(manifest, checkpoint)
                scheduler.transition_to(stage)
                last_state = stage
                logger.debug("Stage completed: %s", stage)
                break
            except Exception as exc:  # noqa: BLE001
                decision = retry_policy.decide(attempt, str(exc))
                logger.warning(
                    "Stage %s failed (attempt %d): %s — %s",
                    stage, attempt, exc, decision.reason,
                )
                if decision.should_retry:
                    time.sleep(decision.delay_seconds)
                    attempt += 1
                else:
                    scheduler.record_error(decision.reason)
                    scheduler.transition_to(DocsregState.FAILED)
                    return DocsregState.FAILED

    return last_state
