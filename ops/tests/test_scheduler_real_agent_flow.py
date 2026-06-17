#!/usr/bin/env python3
"""
Phase 9/10: Scheduler real agent flow tests (7 tests).

Validates the ArgusOrchestrator → Redis Scheduler enqueue pipeline end-to-end
with all Redis I/O mocked.  Focuses on:

  1. argus_smoke task type is in the security allowlist
  2. argus_smoke full enqueue → task_id in return value
  3. TaskMetadata created_by and status defaults are correct
  4. TaskMetadata param overrides (max_retries, priority, vram_sensitive)
  5. Custom task_id param is preserved (no UUID override)
  6. set_task_metadata called before schedule_task (ordering guarantee)
  7. Redis error during enqueue → (False, error message)

Validation-rejection tests live in test_argus_scheduler_integration.py (tests 1–8).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ── Stub optional runtime dependency before importing orchestrator ─────────────
sys.modules.setdefault("argus_code_agent", MagicMock())

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.argus.argus_orchestrator import (  # noqa: E402
    ArgusOrchestrator,
    _ALLOWED_TASK_TYPES,
)
from ops.scheduler.task_models import TaskStatus  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_orch() -> ArgusOrchestrator:
    return ArgusOrchestrator()


def _future_ts(seconds: int = 120) -> str:
    return (
        (datetime.now(tz=timezone.utc) + timedelta(seconds=seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _smoke_params(**overrides) -> dict:
    """Minimal valid params for an argus_smoke task (safe E2E no-op)."""
    base = {
        "task_type": "argus_smoke",
        "command": ["python", "-c", "print('smoke')"],
        "scheduled_for": _future_ts(60),
    }
    base.update(overrides)
    return base


def _mock_redis_with_capture():
    """Return (patches, mock_queue) where mock_queue records all calls."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()
    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(return_value=mock_client)

    mock_queue = AsyncMock()
    mock_queue.set_task_metadata = AsyncMock(return_value=None)
    mock_queue.schedule_task = AsyncMock(return_value=None)
    mock_qm_cls = MagicMock(return_value=mock_queue)

    patches = (
        patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True),
        patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod),
        patch("ops.argus.argus_orchestrator.RedisQueueManager", mock_qm_cls),
    )
    return patches, mock_queue


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_argus_smoke_in_allowlist():
    """argus_smoke must be in _ALLOWED_TASK_TYPES for E2E validation use."""
    assert "argus_smoke" in _ALLOWED_TASK_TYPES, (
        "argus_smoke missing from _ALLOWED_TASK_TYPES — E2E validation cannot proceed"
    )


@pytest.mark.asyncio
async def test_argus_smoke_enqueue_succeeds():
    """argus_smoke task enqueued without approval → (True, task_id=argus-argus_smoke-...)."""
    orch = _make_orch()
    (p1, p2, p3), _ = _mock_redis_with_capture()

    with p1, p2, p3:
        ok, detail = await orch._exec_schedule_task(_smoke_params())

    assert ok is True, f"Expected True, got: {detail}"
    assert "task_id=" in detail
    assert "argus-argus_smoke-" in detail


@pytest.mark.asyncio
async def test_task_metadata_defaults():
    """TaskMetadata built by _exec_schedule_task has correct Argus-owned defaults."""
    orch = _make_orch()
    (p1, p2, p3), mock_queue = _mock_redis_with_capture()

    with p1, p2, p3:
        ok, _ = await orch._exec_schedule_task(_smoke_params())

    assert ok is True
    # set_task_metadata receives (task_id, metadata) — inspect the metadata arg
    assert mock_queue.set_task_metadata.called
    _, metadata = mock_queue.set_task_metadata.call_args.args

    assert metadata.created_by == "argus"
    assert metadata.status == TaskStatus.PENDING.value
    assert metadata.retry_count == 0
    assert metadata.max_retries == 3        # default
    assert metadata.priority == 50          # default
    assert metadata.vram_sensitive is False  # default


@pytest.mark.asyncio
async def test_task_metadata_param_overrides():
    """max_retries, priority, and vram_sensitive flow through to TaskMetadata."""
    orch = _make_orch()
    (p1, p2, p3), mock_queue = _mock_redis_with_capture()
    params = _smoke_params(max_retries=5, priority=80, vram_sensitive=True)

    with p1, p2, p3:
        ok, _ = await orch._exec_schedule_task(params)

    assert ok is True
    _, metadata = mock_queue.set_task_metadata.call_args.args
    assert metadata.max_retries == 5
    assert metadata.priority == 80
    assert metadata.vram_sensitive is True


@pytest.mark.asyncio
async def test_custom_task_id_preserved():
    """When task_id is provided in params, it is used as-is (no UUID override)."""
    orch = _make_orch()
    (p1, p2, p3), mock_queue = _mock_redis_with_capture()
    custom_id = "argus-argus_smoke-test-e2e-001"
    params = _smoke_params(task_id=custom_id)

    with p1, p2, p3:
        ok, detail = await orch._exec_schedule_task(params)

    assert ok is True
    assert custom_id in detail
    # Confirm metadata was stored under the same custom id
    stored_id, _ = mock_queue.set_task_metadata.call_args.args
    assert stored_id == custom_id


@pytest.mark.asyncio
async def test_enqueue_call_order():
    """set_task_metadata must be called before schedule_task (persist then enqueue)."""
    orch = _make_orch()
    call_order: list[str] = []

    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()
    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(return_value=mock_client)

    mock_queue = AsyncMock()
    mock_queue.set_task_metadata = AsyncMock(
        side_effect=lambda *a, **kw: call_order.append("set_metadata")
    )
    mock_queue.schedule_task = AsyncMock(
        side_effect=lambda *a, **kw: call_order.append("schedule_task")
    )
    mock_qm_cls = MagicMock(return_value=mock_queue)

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod), \
         patch("ops.argus.argus_orchestrator.RedisQueueManager", mock_qm_cls):
        ok, _ = await orch._exec_schedule_task(_smoke_params())

    assert ok is True
    assert call_order == ["set_metadata", "schedule_task"], (
        f"Expected [set_metadata, schedule_task], got: {call_order}"
    )


@pytest.mark.asyncio
async def test_redis_error_during_enqueue():
    """Redis failure after validation → (False, schedule_task: Redis error: ...)."""
    orch = _make_orch()
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()
    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(return_value=mock_client)

    mock_queue = AsyncMock()
    mock_queue.set_task_metadata = AsyncMock(
        side_effect=ConnectionError("connection reset by peer")
    )
    mock_qm_cls = MagicMock(return_value=mock_queue)

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod), \
         patch("ops.argus.argus_orchestrator.RedisQueueManager", mock_qm_cls):
        ok, detail = await orch._exec_schedule_task(_smoke_params())

    assert ok is False
    assert "Redis error" in detail
    assert "connection reset" in detail
