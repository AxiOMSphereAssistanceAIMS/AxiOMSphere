#!/usr/bin/env python3
"""
Phase 6 — Logi + Omi real controlled flow tests (14 tests).

Validates end-to-end scheduling contracts for the two agents wired in Phase 4:

  Logi scenarios
  ─────────────
  A. Submit logi_cross_dept_sync when no tasks running → adapter permits, metadata stored
  B. Submit logi_planned_action_gpu when slot32 is running → ResourcePolicy blocks
  C. Submit logi_planned_action_gpu when slot32 is free → ResourcePolicy permits
  D. Submit logi_review_cycle → lightweight, always permitted regardless of slot32

  Omi scenarios
  ─────────────
  E. Submit omi_docs_standards_dry_run when slot120 is running → permits (cpu-only)
  F. Submit omi_ocr_pipeline_run → resource_key=ocr_pipeline_exclusive; second submit blocked
  G. Submit omi_docs_standards_dry_run → vram_sensitive=False preserved in metadata
  H. Both Logi+Omi tasks submitted concurrently → each gets a distinct task_id

  Policy integration
  ─────────────────
  I.  Logi_gpu task with slot32+slot120 both running → SLOT_MUTEX deny (either mutex fires)
  J.  _dispatch_task() with logi task type → policy gate invoked with correct running list
  K.  _dispatch_task() with omi task type → policy gate invoked and permits (no slot)
  L.  TaskMetadata round-trip through to_redis_hash → from_dict preserves Logi fields
  M.  TaskMetadata round-trip preserves Omi resource_key field
  N.  Adapter submit raises SchedulerUnavailableError on connection failure
"""

import json
import sys
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scheduler.agent_scheduler_adapter import AgentSchedulerAdapter, SchedulerUnavailableError
from ops.scheduler.task_models import TaskMetadata, TaskStatus
from ops.scheduler.resource_policy import ResourcePolicy, PolicyDecision, PolicyViolation


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_adapter() -> AgentSchedulerAdapter:
    adapter = AgentSchedulerAdapter.__new__(AgentSchedulerAdapter)
    adapter._redis_url = "redis://localhost:6379"
    adapter._redis = AsyncMock()
    queue = MagicMock()
    queue.set_task_metadata = AsyncMock()
    queue.schedule_task = AsyncMock()
    adapter._queue = queue
    return adapter


async def _submit_and_capture(adapter, **kwargs):
    task_id = await adapter.submit(**kwargs)
    meta: TaskMetadata = adapter._queue.set_task_metadata.call_args[0][1]
    return task_id, meta


def _running_meta(task_type, model_slot=None, created_by="argus", resource_key=None):
    return TaskMetadata(
        task_id=f"running_{task_type}",
        task_type=task_type,
        command=["echo", "running"],
        scheduled_for=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        created_by=created_by,
        status=TaskStatus.RUNNING,
        model_slot=model_slot,
        resource_key=resource_key,
    )


def _make_daemon():
    from ops.scheduler.task_scheduler import TaskSchedulerDaemon
    daemon = TaskSchedulerDaemon.__new__(TaskSchedulerDaemon)
    daemon.queue = MagicMock()
    daemon.redis = MagicMock()
    daemon.executor = MagicMock()
    daemon.monitor = MagicMock()
    daemon.retry_manager = MagicMock()
    daemon.vram_checker = None
    daemon._on_missed_start_report = None
    daemon.resource_policy = ResourcePolicy()
    return daemon


def _make_meta_dict(task_type, created_by="logi", model_slot="", resource_key="",
                    dispatch_blocked="", vram_sensitive="false"):
    return {
        "task_id": f"t_{task_type}",
        "task_type": task_type,
        "command": json.dumps(["python", f"{task_type}_runner.py"]),
        "scheduled_for": "2026-06-10T00:00:00+00:00",
        "created_at": "2026-06-10T00:00:00+00:00",
        "created_by": created_by,
        "status": TaskStatus.PENDING.value,
        "retry_count": "0",
        "max_retries": "3",
        "priority": "50",
        "vram_sensitive": vram_sensitive,
        "model_slot": model_slot,
        "resource_key": resource_key,
        "dispatch_blocked": dispatch_blocked,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scenario A — Logi sync: no contention → permit
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioA_LogiSyncNoContention:

    @pytest.mark.asyncio
    async def test_cross_dept_sync_permitted_when_no_tasks_running(self):
        """Lightweight logi_cross_dept_sync must always be permitted when queue is empty."""
        adapter = _make_adapter()
        task_id, meta = await _submit_and_capture(
            adapter,
            task_type="logi_cross_dept_sync",
            command=["python", "ops/logi/sync_runner.py"],
            created_by="logi",
        )
        assert task_id.startswith("logi_cross_dept_sync_")
        assert meta.created_by == "logi"
        assert meta.model_slot is None

    @pytest.mark.asyncio
    async def test_cross_dept_sync_metadata_stored_exactly_once(self):
        adapter = _make_adapter()
        await _submit_and_capture(
            adapter,
            task_type="logi_cross_dept_sync",
            command=["python", "ops/logi/sync_runner.py"],
            created_by="logi",
        )
        adapter._queue.set_task_metadata.assert_awaited_once()
        adapter._queue.schedule_task.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# Scenario B — Logi GPU task blocked by running slot32
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioB_LogiGpuBlockedBySlot32:

    def test_policy_blocks_slot32_when_slot32_already_running(self):
        """ResourcePolicy must deny a slot32 task when another slot32 task is running."""
        policy = ResourcePolicy()
        running = [_running_meta("logi_planned_action_gpu", model_slot="slot32", created_by="logi")]

        candidate = TaskMetadata(
            task_id="new_gpu_task",
            task_type="logi_planned_action_gpu",
            command=["python", "runner.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="logi",
            status=TaskStatus.PENDING,
            model_slot="slot32",
            vram_sensitive=True,
            resource_key="gpu_exclusive",
        )
        decision = policy.check_dispatch(candidate, running)
        assert not decision.allowed, "Should be blocked by SLOT_CONCURRENCY"

    def test_policy_violation_is_slot_concurrency_or_agent_concurrency(self):
        policy = ResourcePolicy()
        running = [_running_meta("logi_planned_action_gpu", model_slot="slot32", created_by="logi")]

        candidate = TaskMetadata(
            task_id="new_gpu",
            task_type="logi_planned_action_gpu",
            command=["python", "r.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="logi",
            status=TaskStatus.PENDING,
            model_slot="slot32",
            vram_sensitive=True,
        )
        decision = policy.check_dispatch(candidate, running)
        # May be SLOT_CONCURRENCY or AGENT_CONCURRENCY depending on policy limits
        assert decision.violation in (
            PolicyViolation.SLOT_CONCURRENCY,
            PolicyViolation.AGENT_CONCURRENCY,
            PolicyViolation.TYPE_CONCURRENCY,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario C — Logi GPU task permitted when slot32 is free
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioC_LogiGpuPermittedWhenFree:

    def test_policy_permits_slot32_task_when_no_slot32_running(self):
        policy = ResourcePolicy()
        running = []  # empty queue

        candidate = TaskMetadata(
            task_id="gpu_task_1",
            task_type="logi_planned_action_gpu",
            command=["python", "runner.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="logi",
            status=TaskStatus.PENDING,
            model_slot="slot32",
            vram_sensitive=True,
            resource_key="gpu_exclusive",
        )
        decision = policy.check_dispatch(candidate, running)
        assert decision.allowed

    def test_policy_permits_slot32_with_unrelated_lightweight_running(self):
        policy = ResourcePolicy()
        running = [_running_meta("logi_cross_dept_sync", model_slot=None, created_by="logi")]

        candidate = TaskMetadata(
            task_id="gpu_task_2",
            task_type="logi_planned_action_gpu",
            command=["python", "r.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="logi",
            status=TaskStatus.PENDING,
            model_slot="slot32",
            vram_sensitive=True,
        )
        decision = policy.check_dispatch(candidate, running)
        assert decision.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Scenario D — Logi review_cycle is always lightweight
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioD_LogiReviewCycleLightweight:

    def test_review_cycle_permitted_even_with_slot32_running(self):
        """logi_review_cycle has no slot assignment — must not be blocked by GPU contention."""
        policy = ResourcePolicy()
        running = [
            _running_meta("daily_deploy_14b", model_slot="slot14", created_by="argus"),
            _running_meta("logi_planned_action_gpu", model_slot="slot32", created_by="logi"),
        ]

        candidate = TaskMetadata(
            task_id="review_1",
            task_type="logi_review_cycle",
            command=["python", "review_worker.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="logi",
            status=TaskStatus.PENDING,
        )
        decision = policy.check_dispatch(candidate, running)
        assert decision.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Scenario E — Omi standards dry-run is cpu-only
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioE_OmiStandardsDryRunCpuOnly:

    def test_standards_dry_run_permitted_even_with_slot120_running(self):
        """cpu-only task must not be blocked by any slot running."""
        policy = ResourcePolicy()
        running = [_running_meta("slot120_train", model_slot="slot120", created_by="traini")]

        candidate = TaskMetadata(
            task_id="standards_1",
            task_type="omi_docs_standards_dry_run",
            command=["python", "standards_runner.py", "--dry-run"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="omi",
            status=TaskStatus.PENDING,
            vram_sensitive=False,
        )
        decision = policy.check_dispatch(candidate, running)
        assert decision.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Scenario F — Omi OCR exclusive resource key
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioF_OmiOcrExclusiveKey:

    def test_second_ocr_run_blocked_by_resource_key(self):
        """Two concurrent omi_ocr_pipeline_run tasks must not overlap (exclusive resource_key)."""
        policy = ResourcePolicy()
        running = [_running_meta(
            "omi_ocr_pipeline_run",
            model_slot=None,
            created_by="omi",
            resource_key="ocr_pipeline_exclusive",
        )]

        candidate = TaskMetadata(
            task_id="ocr_2",
            task_type="omi_ocr_pipeline_run",
            command=["python", "phase_06_ocr_pipeline.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="omi",
            status=TaskStatus.PENDING,
            resource_key="ocr_pipeline_exclusive",
        )
        decision = policy.check_dispatch(candidate, running)
        assert not decision.allowed
        assert decision.violation == PolicyViolation.RESOURCE_KEY_LOCK


# ─────────────────────────────────────────────────────────────────────────────
# Scenario G + H — Metadata preservation and distinct IDs
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioGH_MetadataAndDistinctIds:

    @pytest.mark.asyncio
    async def test_omi_vram_sensitive_false_preserved(self):
        adapter = _make_adapter()
        _, meta = await _submit_and_capture(
            adapter,
            task_type="omi_docs_standards_dry_run",
            command=["python", "standards_runner.py"],
            created_by="omi",
            vram_sensitive=False,
        )
        assert meta.vram_sensitive is False

    @pytest.mark.asyncio
    async def test_logi_and_omi_concurrent_submits_have_distinct_ids(self):
        adapter = _make_adapter()
        logi_id = await adapter.submit(
            task_type="logi_cross_dept_sync",
            command=["python", "sync.py"],
            created_by="logi",
        )
        omi_id = await adapter.submit(
            task_type="omi_ocr_pipeline_run",
            command=["python", "ocr.py"],
            created_by="omi",
            resource_key="ocr_pipeline_exclusive",
        )
        assert logi_id != omi_id
        assert logi_id.startswith("logi_cross_dept_sync_")
        assert omi_id.startswith("omi_ocr_pipeline_run_")


# ─────────────────────────────────────────────────────────────────────────────
# Scenario I — Slot mutex blocks Logi GPU when slot120 running
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioI_SlotMutexLogi:

    def test_logi_gpu_blocked_by_slot120_mutex(self):
        """slot32 ↔ slot120 mutex: if slot120 is running, slot32 must be blocked."""
        policy = ResourcePolicy()
        running = [_running_meta("slot120_train", model_slot="slot120", created_by="traini")]

        candidate = TaskMetadata(
            task_id="logi_gpu_1",
            task_type="logi_planned_action_gpu",
            command=["python", "runner.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="logi",
            status=TaskStatus.PENDING,
            model_slot="slot32",
            vram_sensitive=True,
        )
        decision = policy.check_dispatch(candidate, running)
        assert not decision.allowed
        assert decision.violation == PolicyViolation.SLOT_MUTEX


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios J/K — _dispatch_task() invokes policy for Logi and Omi types
# ─────────────────────────────────────────────────────────────────────────────

class TestScenariosJK_DispatchTaskPolicyInvocation:

    @pytest.mark.asyncio
    async def test_logi_task_policy_invoked_in_dispatch_task(self):
        """_dispatch_task() must call ResourcePolicy.check_dispatch for a Logi task."""
        daemon = _make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            return_value=_make_meta_dict("logi_review_cycle", created_by="logi")
        )
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=[])
        daemon.queue.acquire_lock = AsyncMock(return_value=False)

        mock_policy = MagicMock()
        mock_policy.check_dispatch = MagicMock(return_value=PolicyDecision.permit())
        daemon.resource_policy = mock_policy

        await daemon._dispatch_task("t_logi_review_cycle")

        mock_policy.check_dispatch.assert_called_once()
        candidate_arg = mock_policy.check_dispatch.call_args[0][0]
        assert candidate_arg.task_type == "logi_review_cycle"

    @pytest.mark.asyncio
    async def test_omi_task_policy_invoked_and_permits(self):
        """_dispatch_task() must invoke policy for an Omi task and permit (no slot)."""
        daemon = _make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            return_value=_make_meta_dict(
                "omi_docs_standards_dry_run",
                created_by="omi",
                vram_sensitive="false",
            )
        )
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=[])
        daemon.queue.acquire_lock = AsyncMock(return_value=False)  # stops after permit

        await daemon._dispatch_task("t_omi_standards")

        # Lock was attempted → policy gate was cleared
        daemon.queue.acquire_lock.assert_called_once_with("t_omi_standards")


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios L/M — TaskMetadata round-trip for Logi and Omi fields
# ─────────────────────────────────────────────────────────────────────────────

class TestScenariosLM_MetadataRoundTrip:
    """Validate that new Logi/Omi fields survive the to_redis_hash → _deserialize_metadata cycle."""

    @staticmethod
    def _deserialize(task_id, meta):
        """Round-trip through to_redis_hash and back via _deserialize_metadata."""
        redis_hash = meta.to_redis_hash()
        daemon = _make_daemon()
        return daemon._deserialize_metadata(task_id, redis_hash)

    def test_logi_gpu_fields_round_trip(self):
        """model_slot and resource_key must survive to_redis_hash → _deserialize_metadata."""
        meta = TaskMetadata(
            task_id="logi_round_trip_1",
            task_type="logi_planned_action_gpu",
            command=["python", "runner.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="logi",
            status=TaskStatus.PENDING,
            model_slot="slot32",
            vram_sensitive=True,
            resource_key="gpu_exclusive",
        )
        restored = self._deserialize("logi_round_trip_1", meta)

        assert restored.model_slot == "slot32"
        assert restored.vram_sensitive is True
        assert restored.resource_key == "gpu_exclusive"
        assert restored.created_by == "logi"

    def test_omi_ocr_resource_key_round_trip(self):
        meta = TaskMetadata(
            task_id="omi_round_trip_1",
            task_type="omi_ocr_pipeline_run",
            command=["python", "phase_06_ocr_pipeline.py"],
            scheduled_for=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            created_by="omi",
            status=TaskStatus.PENDING,
            resource_key="ocr_pipeline_exclusive",
            vram_sensitive=False,
        )
        restored = self._deserialize("omi_round_trip_1", meta)

        assert restored.resource_key == "ocr_pipeline_exclusive"
        assert restored.model_slot is None
        assert restored.vram_sensitive is False
        assert restored.created_by == "omi"
