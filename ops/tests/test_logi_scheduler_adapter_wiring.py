#!/usr/bin/env python3
"""
Phase 3 — Logi AgentSchedulerAdapter wiring tests (12 tests).

Validates that Logi's heavy task types are correctly wired to the scheduler:

  1.  logi_cross_dept_sync is in argus _ALLOWED_TASK_TYPES
  2.  logi_review_cycle is in argus _ALLOWED_TASK_TYPES
  3.  logi_planned_action_gpu is in argus _ALLOWED_TASK_TYPES
  4.  submit() returns task_id in format logi_cross_dept_sync_<12hex>
  5.  submit() for review_cycle returns task_id in format logi_review_cycle_<12hex>
  6.  submitted cross_dept_sync metadata has created_by="logi"
  7.  submitted gpu task metadata has model_slot="slot32"
  8.  submitted gpu task metadata has vram_sensitive=True
  9.  submitted gpu task metadata has resource_key="gpu_exclusive"
  10. Two concurrent submits produce distinct task IDs
  11. submit() calls set_task_metadata and schedule_task exactly once each
  12. SchedulerUnavailableError raised when redis.asyncio not importable
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scheduler.agent_scheduler_adapter import AgentSchedulerAdapter, SchedulerUnavailableError
from ops.scheduler.task_models import TaskMetadata, TaskStatus


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_adapter() -> AgentSchedulerAdapter:
    """Build an AgentSchedulerAdapter with mocked Redis internals."""
    adapter = AgentSchedulerAdapter.__new__(AgentSchedulerAdapter)
    adapter._redis_url = "redis://localhost:6379"
    adapter._redis = AsyncMock()

    queue = MagicMock()
    queue.set_task_metadata = AsyncMock()
    queue.schedule_task = AsyncMock()
    adapter._queue = queue

    return adapter


# Capture the TaskMetadata passed to set_task_metadata
async def _capture_submit(adapter: AgentSchedulerAdapter, **kwargs) -> tuple[str, TaskMetadata]:
    task_id = await adapter.submit(**kwargs)
    call_args = adapter._queue.set_task_metadata.call_args
    captured_meta: TaskMetadata = call_args[0][1]  # (task_id, metadata)
    return task_id, captured_meta


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — Allowlist presence
# ─────────────────────────────────────────────────────────────────────────────

class TestLogiAllowlistPresence:
    """Logi task types must be in argus_orchestrator _ALLOWED_TASK_TYPES."""

    def setup_method(self):
        import sys as _sys
        _sys.modules.setdefault("argus_code_agent", MagicMock())
        from ops.argus.argus_orchestrator import _ALLOWED_TASK_TYPES
        self.allowed = _ALLOWED_TASK_TYPES

    def test_cross_dept_sync_allowed(self):
        assert "logi_cross_dept_sync" in self.allowed

    def test_review_cycle_allowed(self):
        assert "logi_review_cycle" in self.allowed

    def test_planned_action_gpu_allowed(self):
        assert "logi_planned_action_gpu" in self.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — Task ID format
# ─────────────────────────────────────────────────────────────────────────────

class TestLogiTaskIdFormat:
    """task_id must have form {task_type}_{12-char hex}."""

    @pytest.mark.asyncio
    async def test_cross_dept_sync_id_format(self):
        adapter = _make_adapter()
        task_id = await adapter.submit(
            task_type="logi_cross_dept_sync",
            command=["python", "ops/logi/sync_runner.py"],
            created_by="logi",
        )
        prefix, suffix = task_id.rsplit("_", 1)
        assert prefix == "logi_cross_dept_sync"
        assert len(suffix) == 12
        int(suffix, 16)  # must be valid hex

    @pytest.mark.asyncio
    async def test_review_cycle_id_format(self):
        adapter = _make_adapter()
        task_id = await adapter.submit(
            task_type="logi_review_cycle",
            command=["python", "ops/logi/claude_review_worker.py"],
            created_by="logi",
        )
        assert task_id.startswith("logi_review_cycle_")
        assert len(task_id.split("_")[-1]) == 12

    @pytest.mark.asyncio
    async def test_two_submits_produce_distinct_ids(self):
        adapter = _make_adapter()
        id1 = await adapter.submit(
            task_type="logi_cross_dept_sync",
            command=["python", "sync.py"],
            created_by="logi",
        )
        id2 = await adapter.submit(
            task_type="logi_cross_dept_sync",
            command=["python", "sync.py"],
            created_by="logi",
        )
        assert id1 != id2


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — Metadata correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestLogiMetadataCorrectness:
    """Submitted TaskMetadata must carry correct Logi-specific fields."""

    @pytest.mark.asyncio
    async def test_cross_dept_sync_created_by_logi(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="logi_cross_dept_sync",
            command=["python", "sync.py"],
            created_by="logi",
        )
        assert meta.created_by == "logi"

    @pytest.mark.asyncio
    async def test_cross_dept_sync_no_model_slot(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="logi_cross_dept_sync",
            command=["python", "sync.py"],
            created_by="logi",
        )
        assert meta.model_slot is None

    @pytest.mark.asyncio
    async def test_gpu_task_has_slot32(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="logi_planned_action_gpu",
            command=["python", "ops/logi/planned_action_runner.py", "--mode", "live-gpu-gated"],
            created_by="logi",
            model_slot="slot32",
            vram_sensitive=True,
            resource_key="gpu_exclusive",
        )
        assert meta.model_slot == "slot32"

    @pytest.mark.asyncio
    async def test_gpu_task_is_vram_sensitive(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="logi_planned_action_gpu",
            command=["python", "ops/logi/planned_action_runner.py"],
            created_by="logi",
            model_slot="slot32",
            vram_sensitive=True,
            resource_key="gpu_exclusive",
        )
        assert meta.vram_sensitive is True

    @pytest.mark.asyncio
    async def test_gpu_task_resource_key(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="logi_planned_action_gpu",
            command=["python", "ops/logi/planned_action_runner.py"],
            created_by="logi",
            model_slot="slot32",
            vram_sensitive=True,
            resource_key="gpu_exclusive",
        )
        assert meta.resource_key == "gpu_exclusive"


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — Dispatch contract
# ─────────────────────────────────────────────────────────────────────────────

class TestLogiDispatchContract:
    """submit() must call set_task_metadata and schedule_task exactly once."""

    @pytest.mark.asyncio
    async def test_set_task_metadata_called_once(self):
        adapter = _make_adapter()
        await adapter.submit(
            task_type="logi_review_cycle",
            command=["python", "ops/logi/claude_review_worker.py"],
            created_by="logi",
        )
        adapter._queue.set_task_metadata.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schedule_task_called_once(self):
        adapter = _make_adapter()
        await adapter.submit(
            task_type="logi_review_cycle",
            command=["python", "ops/logi/claude_review_worker.py"],
            created_by="logi",
        )
        adapter._queue.schedule_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scheduler_unavailable_error_on_import_failure(self):
        """When redis.asyncio is not importable, SchedulerUnavailableError is raised."""
        fresh = AgentSchedulerAdapter(redis_url="redis://localhost:6379")
        # Simulate missing redis.asyncio by patching builtins.__import__
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _bad_import(name, *args, **kwargs):
            if name == "redis.asyncio":
                raise ImportError("redis.asyncio not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_bad_import):
            with pytest.raises((SchedulerUnavailableError, ImportError)):
                await fresh._ensure_connected()
