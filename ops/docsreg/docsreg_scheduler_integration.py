"""
DOCSREG scheduler integration — thin facade over DocsregRedisScheduler.

Wraps ``DocsregRedisScheduler`` with:
  - A module-level feature flag (``DOCSREG_USE_SCHEDULER``)
  - No-op disabled mode (all methods are safe to call; ``write_evidence``
    returns ``True`` without creating any files)
  - Internal key/gate/worker tracking for evidence export (the underlying
    scheduler offers only per-key access; this facade builds the full sets)
  - ``write_evidence()`` that persists 6 JSON artefacts to
    ``<cycle_dir>/evidence/``

This module deliberately has no hard dependency on ``redis`` — the scheduler
is lazy-imported and the class accepts any duck-typed redis client.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

log = logging.getLogger("docsreg_scheduler_integration")

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

DOCSREG_USE_SCHEDULER: bool = True
"""Module-level kill-switch.  Set to ``True`` to enable Redis scheduler wiring."""


# ---------------------------------------------------------------------------
# SchedulerIntegration
# ---------------------------------------------------------------------------


class SchedulerIntegration:
    """Thin facade over :class:`~ops.docsreg.docsreg_scheduler.DocsregRedisScheduler`.

    When ``enabled=False`` (default) every method is a no-op and
    :meth:`write_evidence` returns ``True`` without touching the filesystem.

    Parameters
    ----------
    redis_client:
        Any duck-typed Redis client (``redis.Redis``, ``fakeredis.FakeRedis``,
        or a test stub).  Ignored when ``enabled=False``.
    run_id:
        Unique identifier for this certification run.
    enabled:
        Whether to actually delegate to Redis.  Defaults to ``False`` so that
        callers that do not wire Redis receive safe no-op behaviour.
    """

    def __init__(self, redis_client: Any, run_id: str, enabled: bool = False) -> None:
        self._run_id = run_id
        self._enabled = enabled
        self._scheduler = None

        # Internal tracking lists — used for evidence export because the
        # underlying scheduler only supports per-key lookup (no "get all").
        self._metric_keys: list[str] = []
        self._gate_names: list[str] = []
        self._worker_ids: list[str] = []
        self._locks_acquired: list[str] = []
        self._locks_released: list[str] = []

        if self._enabled:
            try:
                from ops.docsreg.docsreg_scheduler import DocsregRedisScheduler  # noqa: PLC0415
                self._scheduler = DocsregRedisScheduler(redis_client, run_id=run_id)
            except Exception as exc:
                log.error(
                    "SchedulerIntegration: failed to create scheduler for run=%s: %s",
                    run_id,
                    exc,
                )
                self._enabled = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """``True`` when scheduler delegation is active."""
        return self._enabled

    @property
    def scheduler(self):
        """Underlying :class:`~ops.docsreg.docsreg_scheduler.DocsregRedisScheduler` or ``None``."""
        return self._scheduler

    # ------------------------------------------------------------------
    # Delegation methods — all no-ops when disabled
    # ------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        """Set the run state via the scheduler.  No-op when disabled."""
        if not self._enabled or self._scheduler is None:
            return
        try:
            self._scheduler.set_state(state)
        except Exception as exc:
            log.error("SchedulerIntegration.set_state: %s", exc)

    def set_metric(self, key: str, value: Any) -> None:
        """Store a metric and track the key for evidence export.  No-op when disabled."""
        if not self._enabled or self._scheduler is None:
            return
        try:
            self._scheduler.set_metric(key, value)
            if key not in self._metric_keys:
                self._metric_keys.append(key)
        except Exception as exc:
            log.error("SchedulerIntegration.set_metric key=%s: %s", key, exc)

    def set_gate(self, gate_name: str, verdict: str) -> None:
        """Record a gate verdict and track the name for evidence export.  No-op when disabled."""
        if not self._enabled or self._scheduler is None:
            return
        try:
            self._scheduler.set_gate(gate_name, verdict)
            if gate_name not in self._gate_names:
                self._gate_names.append(gate_name)
        except Exception as exc:
            log.error("SchedulerIntegration.set_gate gate=%s: %s", gate_name, exc)

    def record_error(self, error: str) -> None:
        """Append an error to the run error list.  No-op when disabled."""
        if not self._enabled or self._scheduler is None:
            return
        try:
            self._scheduler.record_error(error)
        except Exception as exc:
            log.error("SchedulerIntegration.record_error: %s", exc)

    def beat_heartbeat(self, worker_id: str) -> None:
        """Refresh the heartbeat for *worker_id* and track it for evidence export.  No-op when disabled."""
        if not self._enabled or self._scheduler is None:
            return
        try:
            self._scheduler.beat_heartbeat(worker_id)
            if worker_id not in self._worker_ids:
                self._worker_ids.append(worker_id)
        except Exception as exc:
            log.error("SchedulerIntegration.beat_heartbeat worker=%s: %s", worker_id, exc)

    def record_lock_acquired(self, lock_name: str) -> None:
        """Record that *lock_name* was acquired.  Safe to call even when disabled."""
        if lock_name not in self._locks_acquired:
            self._locks_acquired.append(lock_name)

    def record_lock_released(self, lock_name: str) -> None:
        """Record that *lock_name* was released.  Safe to call even when disabled."""
        if lock_name not in self._locks_released:
            self._locks_released.append(lock_name)

    # ------------------------------------------------------------------
    # Evidence export
    # ------------------------------------------------------------------

    def write_evidence(self, cycle_dir: Union[str, Path]) -> bool:
        """Write 6 scheduler evidence JSON files to ``<cycle_dir>/evidence/``.

        When disabled, returns ``True`` immediately without writing any files.

        Files produced
        --------------
        1. ``scheduler_run_summary.json``
        2. ``scheduler_metrics.json``
        3. ``scheduler_gates.json``
        4. ``scheduler_errors.json``
        5. ``scheduler_locks_manifest.json``
        6. ``scheduler_heartbeat.json``

        Returns
        -------
        bool
            ``True`` on success (or when disabled), ``False`` on any I/O
            error.  Never raises.
        """
        if not self._enabled or self._scheduler is None:
            return True

        try:
            evidence_dir = Path(cycle_dir) / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now(tz=timezone.utc).isoformat()

            # 1 — run summary
            (evidence_dir / "scheduler_run_summary.json").write_text(
                json.dumps(
                    {
                        "run_id": self._run_id,
                        "final_state": self._scheduler.get_state(),
                        "timestamp_utc": ts,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            # 2 — metrics
            metrics: dict[str, Any] = {}
            for key in self._metric_keys:
                metrics[key] = self._scheduler.get_metric(key)
            (evidence_dir / "scheduler_metrics.json").write_text(
                json.dumps({"metrics": metrics}, indent=2),
                encoding="utf-8",
            )

            # 3 — gates
            gates: dict[str, str | None] = {}
            for name in self._gate_names:
                gates[name] = self._scheduler.get_gate(name)
            (evidence_dir / "scheduler_gates.json").write_text(
                json.dumps({"gates": gates}, indent=2),
                encoding="utf-8",
            )

            # 4 — errors
            (evidence_dir / "scheduler_errors.json").write_text(
                json.dumps({"errors": self._scheduler.get_errors()}, indent=2),
                encoding="utf-8",
            )

            # 5 — locks manifest
            (evidence_dir / "scheduler_locks_manifest.json").write_text(
                json.dumps(
                    {
                        "locks_acquired": list(self._locks_acquired),
                        "locks_released": list(self._locks_released),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            # 6 — heartbeat
            workers: dict[str, str | None] = {}
            for wid in self._worker_ids:
                workers[wid] = self._scheduler.get_heartbeat(wid)
            (evidence_dir / "scheduler_heartbeat.json").write_text(
                json.dumps({"workers": workers, "timestamp_utc": ts}, indent=2),
                encoding="utf-8",
            )

            log.info(
                "SchedulerIntegration.write_evidence: 6 files written to %s",
                evidence_dir,
            )
            return True

        except Exception as exc:
            log.error("SchedulerIntegration.write_evidence: %s", exc)
            return False
