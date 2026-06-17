#!/usr/bin/env python3
"""
Integration tests for ArgusOrchestrator schedule_task Redis integration.

Tests:
  1. Valid params → enqueued successfully (task_id returned)
  2. Missing task_type → validation error
  3. Missing command → validation error
  4. Unknown task_type → not in allowlist
  5. Gated type (slot120_train) without gated_training_approved → blocked
  6. Gated type (slot120_train) with gated_training_approved=True → accepted
  7. Forbidden command pattern (rm -rf) → blocked
  8. scheduled_for >5 min in the past → rejected
  9. Redis integration — metadata hash + pending sorted set both verified
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ── Patch argus_code_agent before importing orchestrator ─────────────────────
# argus_code_agent is a runtime dependency not available in test environments.
sys.modules.setdefault("argus_code_agent", MagicMock())

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.argus.argus_orchestrator import ArgusOrchestrator  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_orch() -> ArgusOrchestrator:
    """Instantiate orchestrator without starting the background thread."""
    return ArgusOrchestrator()


def _future_ts(seconds: int = 120) -> str:
    """UTC ISO timestamp N seconds in the future (with Z suffix)."""
    return (
        (datetime.now(tz=timezone.utc) + timedelta(seconds=seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _past_ts(seconds: int = 400) -> str:
    """UTC ISO timestamp N seconds in the past (with Z suffix)."""
    return (
        (datetime.now(tz=timezone.utc) - timedelta(seconds=seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _valid_params(**overrides) -> dict:
    base = {
        "task_type": "training_ingest",
        "command": ["python", "ops/ft/scripts/ingest.py", "--source", "qdrant"],
        "scheduled_for": _future_ts(120),
    }
    base.update(overrides)
    return base


def _mock_redis_context():
    """Return context managers that patch out the Redis path."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()
    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(return_value=mock_client)

    mock_queue = AsyncMock()
    mock_queue.set_task_metadata = AsyncMock()
    mock_queue.schedule_task = AsyncMock()
    mock_qm_cls = MagicMock(return_value=mock_queue)

    return (
        patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True),
        patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod),
        patch("ops.argus.argus_orchestrator.RedisQueueManager", mock_qm_cls),
        mock_queue,
    )


# ── Validation tests (Redis mocked) ──────────────────────────────────────────

class TestExecScheduleTaskValidation:
    """Tests 1–8: param validation — Redis layer is fully mocked."""

    @pytest.mark.asyncio
    async def test_1_valid_params_accepted(self):
        """Test 1: Valid params → (True, 'task_id=argus-training_ingest-...')."""
        orch = _make_orch()
        p1, p2, p3, _ = _mock_redis_context()
        with p1, p2, p3:
            ok, detail = await orch._exec_schedule_task(_valid_params())
        assert ok is True, f"Expected True, got: {detail}"
        assert "task_id=" in detail
        assert "argus-training_ingest-" in detail

    @pytest.mark.asyncio
    async def test_2_missing_task_type(self):
        """Test 2: Missing task_type → validation error."""
        orch = _make_orch()
        params = _valid_params()
        del params["task_type"]
        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True):
            ok, detail = await orch._exec_schedule_task(params)
        assert ok is False
        assert "task_type" in detail

    @pytest.mark.asyncio
    async def test_3_missing_command(self):
        """Test 3: Missing command → validation error."""
        orch = _make_orch()
        params = _valid_params()
        del params["command"]
        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True):
            ok, detail = await orch._exec_schedule_task(params)
        assert ok is False
        assert "command" in detail

    @pytest.mark.asyncio
    async def test_4_unknown_task_type_rejected(self):
        """Test 4: task_type not in allowlist → blocked."""
        orch = _make_orch()
        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True):
            ok, detail = await orch._exec_schedule_task(
                _valid_params(task_type="arbitrary_evil_exec")
            )
        assert ok is False
        assert "allowlist" in detail

    @pytest.mark.asyncio
    async def test_5_gated_type_without_approval_blocked(self):
        """Test 5: slot120_train without gated_training_approved → blocked."""
        orch = _make_orch()
        params = _valid_params(
            task_type="slot120_train",
            command=["python", "ops/ft/train.py", "--slot", "120"],
        )
        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True):
            ok, detail = await orch._exec_schedule_task(params)
        assert ok is False
        assert "gated_training_approved" in detail

    @pytest.mark.asyncio
    async def test_6_gated_type_with_approval_accepted(self):
        """Test 6: slot120_train with gated_training_approved=True → accepted."""
        orch = _make_orch()
        params = _valid_params(
            task_type="slot120_train",
            command=["python", "ops/ft/train.py", "--slot", "120"],
            gated_training_approved=True,
        )
        p1, p2, p3, _ = _mock_redis_context()
        with p1, p2, p3:
            ok, detail = await orch._exec_schedule_task(params)
        assert ok is True, f"Expected True, got: {detail}"
        assert "task_id=" in detail

    @pytest.mark.asyncio
    async def test_7_forbidden_command_pattern_rejected(self):
        """Test 7: command containing 'rm -rf' → blocked."""
        orch = _make_orch()
        params = _valid_params(command=["bash", "-c", "rm -rf /tmp/evidence"])
        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True):
            ok, detail = await orch._exec_schedule_task(params)
        assert ok is False
        assert "forbidden" in detail

    @pytest.mark.asyncio
    async def test_8_past_timestamp_rejected(self):
        """Test 8: scheduled_for >5 min in the past → rejected."""
        orch = _make_orch()
        params = _valid_params(scheduled_for=_past_ts(400))
        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True):
            ok, detail = await orch._exec_schedule_task(params)
        assert ok is False
        assert "past" in detail


# ── Redis integration test ────────────────────────────────────────────────────

class TestExecScheduleTaskRedisIntegration:
    """Test 9: Full Redis round-trip — metadata hash + pending sorted set."""

    @pytest_asyncio.fixture
    async def redis_client(self):
        """Redis client for DB 1 with multi-URL fallback; auto-flush."""
        try:
            import redis.asyncio as aioredis
        except ImportError:
            pytest.skip("redis.asyncio not available")

        redis_urls = [
            os.getenv("AIMS_TEST_REDIS_URL", "redis://172.18.0.26:6379/1"),
            "redis://aims-redis:6379/1",
            "redis://localhost:6379/1",
        ]
        client = None
        for url in redis_urls:
            try:
                client = await aioredis.from_url(url, decode_responses=True)
                await client.ping()
                break
            except Exception:
                continue

        if client is None:
            pytest.skip("Redis not reachable on any known URL")

        await client.flushdb()
        yield client
        await client.flushdb()
        await client.close()

    @pytest.mark.asyncio
    async def test_9_redis_task_persisted_and_enqueued(self, redis_client):
        """Test 9: After _exec_schedule_task succeeds, verify Redis state.

        Checks:
        - scheduler:task:{task_id} hash exists with correct fields
        - task_id appears in scheduler:tasks:pending sorted set
        """
        import redis.asyncio as aioredis

        # Find the working Redis URL (same DB as fixture)
        redis_urls = [
            os.getenv("AIMS_TEST_REDIS_URL", "redis://172.18.0.26:6379/1"),
            "redis://aims-redis:6379/1",
            "redis://localhost:6379/1",
        ]
        working_url = None
        for url in redis_urls:
            try:
                tmp = await aioredis.from_url(url, decode_responses=True)
                await tmp.ping()
                await tmp.aclose()
                working_url = url
                break
            except Exception:
                continue

        if not working_url:
            pytest.skip("Redis not available for integration test")

        orch = _make_orch()
        scheduled_for = _future_ts(120)

        with patch.dict(os.environ, {"TASK_SCHEDULER_REDIS_URL": working_url}):
            ok, detail = await orch._exec_schedule_task(
                _valid_params(scheduled_for=scheduled_for)
            )

        assert ok is True, f"Expected success, got: {detail}"
        assert "task_id=" in detail
        task_id = detail.split("task_id=")[1].strip()

        # ── Verify metadata hash ──────────────────────────────────────────
        metadata = await redis_client.hgetall(f"scheduler:task:{task_id}")
        assert metadata, f"Expected metadata hash at scheduler:task:{task_id}"
        assert metadata.get("task_id") == task_id
        assert metadata.get("task_type") == "training_ingest"
        assert metadata.get("created_by") == "argus"
        assert metadata.get("status") == "PENDING"

        # ── Verify pending sorted set membership ──────────────────────────
        members = await redis_client.zrange("scheduler:tasks:pending", 0, -1)
        assert task_id in members, (
            f"task_id '{task_id}' not found in scheduler:tasks:pending; "
            f"found: {members}"
        )
