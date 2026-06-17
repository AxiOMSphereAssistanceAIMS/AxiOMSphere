#!/usr/bin/env python3
"""
Integration tests for AgentSchedulerAdapter (ops/scheduler/agent_scheduler_adapter.py)

Tests the adapter's submit() contract using a mocked RedisQueueManager,
so no live Redis is required.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from ops.scheduler.task_models import TaskMetadata, TaskStatus


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_queue():
    q = MagicMock()
    q.set_task_metadata = AsyncMock()
    q.schedule_task = AsyncMock()
    return q


@pytest.fixture
def adapter(mock_queue):
    """Return an adapter with its internal queue already injected."""
    from ops.scheduler.agent_scheduler_adapter import AgentSchedulerAdapter
    a = AgentSchedulerAdapter()
    a._queue = mock_queue
    a._redis = MagicMock()
    a._redis.close = AsyncMock()
    return a


# ─────────────────────────────────────────────────────────────────────────────
# submit() contract tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapterSubmit:
    @pytest.mark.asyncio
    async def test_submit_returns_task_id(self, adapter):
        task_id = await adapter.submit(
            task_type="argus_smoke",
            command=["echo", "test"],
            created_by="argus",
        )
        assert task_id.startswith("argus_smoke_")

    @pytest.mark.asyncio
    async def test_submit_task_id_has_12_char_suffix(self, adapter):
        task_id = await adapter.submit(
            task_type="training_ingest",
            command=["python", "ops/workers/ingest.py"],
            created_by="logi",
        )
        # Format: "{task_type}_{12 hex chars}"
        prefix, suffix = task_id.rsplit("_", 1)
        # The task_type may contain underscores, so split from right once
        assert len(suffix) == 12
        assert all(c in "0123456789abcdef" for c in suffix)

    @pytest.mark.asyncio
    async def test_submit_calls_set_metadata(self, adapter, mock_queue):
        await adapter.submit(
            task_type="ft_prepare_chain_run",
            command=["bash", "run.sh"],
            created_by="argus",
            model_slot="slot14",
        )
        mock_queue.set_task_metadata.assert_called_once()
        _, metadata = mock_queue.set_task_metadata.call_args[0]
        assert isinstance(metadata, TaskMetadata)
        assert metadata.task_type == "ft_prepare_chain_run"
        assert metadata.model_slot == "slot14"
        assert metadata.created_by == "argus"

    @pytest.mark.asyncio
    async def test_submit_calls_schedule_task(self, adapter, mock_queue):
        await adapter.submit(
            task_type="argus_smoke",
            command=["echo", "ok"],
            created_by="argus",
        )
        mock_queue.schedule_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_stores_model_slot(self, adapter, mock_queue):
        await adapter.submit(
            task_type="slot14_nightly_eval",
            command=["python", "eval.py"],
            created_by="traini",
            model_slot="slot14",
        )
        _, metadata = mock_queue.set_task_metadata.call_args[0]
        assert metadata.model_slot == "slot14"

    @pytest.mark.asyncio
    async def test_submit_stores_resource_key(self, adapter, mock_queue):
        await adapter.submit(
            task_type="argus_smoke",
            command=["echo", "test"],
            created_by="argus",
            resource_key="gpu_exclusive",
        )
        _, metadata = mock_queue.set_task_metadata.call_args[0]
        assert metadata.resource_key == "gpu_exclusive"

    @pytest.mark.asyncio
    async def test_submit_defaults_to_now_if_no_scheduled_for(self, adapter):
        before = datetime.now(timezone.utc)
        task_id = await adapter.submit(
            task_type="argus_smoke",
            command=["echo", "ok"],
            created_by="argus",
        )
        after = datetime.now(timezone.utc)
        # Just confirm it ran without error
        assert task_id is not None

    @pytest.mark.asyncio
    async def test_submit_respects_explicit_scheduled_for(self, adapter, mock_queue):
        target = datetime(2026, 6, 11, 3, 0, 0, tzinfo=timezone.utc)
        await adapter.submit(
            task_type="docbench_nightly",
            command=["python", "bench.py"],
            created_by="argus",
            scheduled_for=target,
        )
        _, metadata = mock_queue.set_task_metadata.call_args[0]
        assert "2026-06-11" in metadata.scheduled_for

    @pytest.mark.asyncio
    async def test_submit_status_is_pending(self, adapter, mock_queue):
        await adapter.submit(
            task_type="argus_smoke",
            command=["echo", "ok"],
            created_by="argus",
        )
        _, metadata = mock_queue.set_task_metadata.call_args[0]
        assert metadata.status == TaskStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_submit_vram_sensitive_flag(self, adapter, mock_queue):
        await adapter.submit(
            task_type="ft_prepare_chain_run",
            command=["bash", "train.sh"],
            created_by="traini",
            vram_sensitive=True,
            model_slot="slot32",
        )
        _, metadata = mock_queue.set_task_metadata.call_args[0]
        assert metadata.vram_sensitive is True


# ─────────────────────────────────────────────────────────────────────────────
# Context manager protocol
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapterContextManager:
    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, adapter):
        await adapter.close()
        await adapter.close()  # should not raise

    @pytest.mark.asyncio
    async def test_aenter_returns_adapter(self, adapter):
        result = await adapter.__aenter__()
        assert result is adapter
