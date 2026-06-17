"""
DOCSREG stall detector — checks whether worker heartbeats are still alive.

A worker is considered stalled when its heartbeat key has expired (or was
never set).  The TTL-based expiry is handled by Redis automatically; this
module simply reads the value and treats ``None`` as "stalled".
"""
from __future__ import annotations

from dataclasses import dataclass

from ops.docsreg.docsreg_scheduler import DocsregRedisScheduler


@dataclass
class StallResult:
    """Heartbeat check result for a single worker."""

    worker_id: str
    is_stalled: bool
    """True when the heartbeat key returned None (expired or never set)."""


class DocsregStallDetector:
    """
    Detects stalled DOCSREG workers using the TTL-based heartbeat from
    :class:`DocsregRedisScheduler`.

    Parameters
    ----------
    scheduler:
        An initialised :class:`DocsregRedisScheduler` instance for the run
        whose workers are being monitored.
    """

    def __init__(self, scheduler: DocsregRedisScheduler) -> None:
        self._scheduler = scheduler

    def check(self, worker_id: str) -> StallResult:
        """
        Check whether *worker_id* has a live heartbeat.

        Returns
        -------
        StallResult
            ``is_stalled=True`` when the heartbeat is absent (expired or
            never set); ``False`` when the heartbeat value is present.
        """
        heartbeat = self._scheduler.get_heartbeat(worker_id)
        return StallResult(worker_id=worker_id, is_stalled=(heartbeat is None))

    def check_any(self, worker_ids: list[str]) -> list[StallResult]:
        """
        Check all *worker_ids* and return results in the same order.

        Parameters
        ----------
        worker_ids:
            Ordered list of worker identifiers to check.
        """
        return [self.check(wid) for wid in worker_ids]

    def any_stalled(self, worker_ids: list[str]) -> bool:
        """
        Return ``True`` if at least one worker in *worker_ids* is stalled.
        """
        return any(result.is_stalled for result in self.check_any(worker_ids))
