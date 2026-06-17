#!/usr/bin/env python3
"""
get_scheduler_backpressure_detail() tests (8 tests).

Validates the backpressure-extended dashboard function in argus_orchestrator.py:

  1. All required backpressure keys always present (unavailable path)
  2. All slots free when no running tasks have model_slot set
  3. slot32 reported busy when a running task occupies it
  4. mutex_locked True when slot32 is occupied
  5. mutex_locked True when slot120 is occupied
  6. mutex_locked False when only slot14 is running
  7. queue_pressure CRITICAL when running >= global_limit
  8. active_resource_keys populated from running task metadata
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub optional runtime dependency before importing orchestrator ─────────────
sys.modules.setdefault("argus_code_agent", MagicMock())
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.argus.argus_orchestrator import get_scheduler_backpressure_detail  # noqa: E402

# ── Required keys for the backpressure extension ──────────────────────────────
BACKPRESSURE_KEYS = frozenset({
    "slot_states", "mutex_locked", "running_slots",
    "active_resource_keys", "global_limit", "queue_pressure",
})
# Combined: base status + detail + backpressure
ALL_REQUIRED_KEYS = frozenset({
    "available", "daemon_alive", "heartbeat_age_s", "stale",
    "pending", "running", "retrying", "failed", "held_for_review",
    "completed_total", "last_completed", "last_failed",
}) | BACKPRESSURE_KEYS


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fresh_hb() -> str:
    return str(int(time.time()) - 10)


def _base_client(*, heartbeat: str | None, pending: int = 0, running: int = 0) -> AsyncMock:
    """Mock Redis client for get_scheduler_status() — 5 zcard calls."""
    c = AsyncMock()
    c.get = AsyncMock(return_value=heartbeat)
    c.zcard = AsyncMock(side_effect=[pending, running, 0, 0, 0])
    c.aclose = AsyncMock()
    return c


def _detail_client(*, completed: int = 0) -> AsyncMock:
    """Mock Redis client for get_scheduler_detail() second connection."""
    c = AsyncMock()
    c.zcard = AsyncMock(return_value=completed)
    c.zrange = AsyncMock(return_value=[])
    c.hgetall = AsyncMock(return_value={})
    c.aclose = AsyncMock()
    return c


def _bp_client(running_tasks: list[dict]) -> AsyncMock:
    """Mock Redis client for get_scheduler_backpressure_detail() third connection.

    running_tasks: list of {task_id, task_type, model_slot?, resource_key?}
    """
    c = AsyncMock()
    task_ids = [t["task_id"] for t in running_tasks]
    c.zrange = AsyncMock(return_value=task_ids)

    hgetall_results = []
    for t in running_tasks:
        hgetall_results.append({
            "task_type": t.get("task_type", "unknown"),
            "model_slot": t.get("model_slot", ""),
            "resource_key": t.get("resource_key", ""),
        })
    c.hgetall = AsyncMock(side_effect=hgetall_results) if hgetall_results else AsyncMock(return_value={})
    c.aclose = AsyncMock()
    return c


def _make_call_seq(base_c, detail_c, bp_c):
    """Return a from_url side_effect that dispatches the three clients in order."""
    seq = [base_c, detail_c, bp_c]

    async def _from_url(url, **kw):
        return seq.pop(0)

    return _from_url


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_required_keys_present_when_unavailable():
    """Scheduler unavailable → all backpressure keys present with safe defaults."""
    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", False):
        result = await get_scheduler_backpressure_detail()

    missing = ALL_REQUIRED_KEYS - result.keys()
    assert not missing, f"Missing keys: {missing}"
    assert result["slot_states"] == {"slot14": "free", "slot32": "free", "slot120": "free"}
    assert result["mutex_locked"] is False
    assert result["running_slots"] == []
    assert result["active_resource_keys"] == []
    assert result["queue_pressure"] == "OK"


@pytest.mark.asyncio
async def test_all_slots_free_when_no_slotted_running_tasks():
    """Running tasks with no model_slot → all slot states remain free."""
    base_c   = _base_client(heartbeat=_fresh_hb(), running=1)
    detail_c = _detail_client()
    bp_c     = _bp_client(running_tasks=[{"task_id": "t1", "task_type": "argus_smoke"}])

    mock_redis = MagicMock()
    mock_redis.from_url = AsyncMock(side_effect=_make_call_seq(base_c, detail_c, bp_c))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
        result = await get_scheduler_backpressure_detail()

    ss = result["slot_states"]
    assert ss["slot14"]  == "free"
    assert ss["slot32"]  == "free"
    assert ss["slot120"] == "free"
    assert result["mutex_locked"] is False
    assert result["running_slots"] == []


@pytest.mark.asyncio
async def test_slot32_busy_when_task_running_on_it():
    """Task with model_slot=slot32 → slot32 reported busy, slot14/120 free."""
    base_c   = _base_client(heartbeat=_fresh_hb(), running=1)
    detail_c = _detail_client()
    bp_c     = _bp_client(running_tasks=[
        {"task_id": "t1", "task_type": "docbench_nightly", "model_slot": "slot32"},
    ])

    mock_redis = MagicMock()
    mock_redis.from_url = AsyncMock(side_effect=_make_call_seq(base_c, detail_c, bp_c))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
        result = await get_scheduler_backpressure_detail()

    ss = result["slot_states"]
    assert ss["slot32"]  == "busy"
    assert ss["slot14"]  == "free"
    assert ss["slot120"] == "free"
    assert len(result["running_slots"]) == 1
    assert result["running_slots"][0]["model_slot"] == "slot32"


@pytest.mark.asyncio
async def test_mutex_locked_when_slot32_running():
    """slot32 running → mutex_locked True (slot120 would be blocked)."""
    base_c   = _base_client(heartbeat=_fresh_hb(), running=1)
    detail_c = _detail_client()
    bp_c     = _bp_client(running_tasks=[
        {"task_id": "t1", "task_type": "slot32_nightly_eval", "model_slot": "slot32"},
    ])

    mock_redis = MagicMock()
    mock_redis.from_url = AsyncMock(side_effect=_make_call_seq(base_c, detail_c, bp_c))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
        result = await get_scheduler_backpressure_detail()

    assert result["mutex_locked"] is True


@pytest.mark.asyncio
async def test_mutex_locked_when_slot120_running():
    """slot120 running → mutex_locked True (slot32 would be blocked)."""
    base_c   = _base_client(heartbeat=_fresh_hb(), running=1)
    detail_c = _detail_client()
    bp_c     = _bp_client(running_tasks=[
        {"task_id": "t1", "task_type": "slot120_train", "model_slot": "slot120"},
    ])

    mock_redis = MagicMock()
    mock_redis.from_url = AsyncMock(side_effect=_make_call_seq(base_c, detail_c, bp_c))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
        result = await get_scheduler_backpressure_detail()

    assert result["mutex_locked"] is True
    assert result["slot_states"]["slot120"] == "busy"


@pytest.mark.asyncio
async def test_mutex_free_when_only_slot14_running():
    """Only slot14 running → mutex_locked False (slot32↔120 mutex unaffected)."""
    base_c   = _base_client(heartbeat=_fresh_hb(), running=1)
    detail_c = _detail_client()
    bp_c     = _bp_client(running_tasks=[
        {"task_id": "t1", "task_type": "slot14_nightly_eval", "model_slot": "slot14"},
    ])

    mock_redis = MagicMock()
    mock_redis.from_url = AsyncMock(side_effect=_make_call_seq(base_c, detail_c, bp_c))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
        result = await get_scheduler_backpressure_detail()

    assert result["mutex_locked"] is False
    assert result["slot_states"]["slot14"] == "busy"
    assert result["slot_states"]["slot32"] == "free"
    assert result["slot_states"]["slot120"] == "free"


@pytest.mark.asyncio
async def test_queue_pressure_critical_at_global_limit():
    """running >= global_limit (3) → queue_pressure CRITICAL."""
    base_c   = _base_client(heartbeat=_fresh_hb(), running=3)
    detail_c = _detail_client()
    bp_c     = _bp_client(running_tasks=[
        {"task_id": "t1", "task_type": "argus_smoke"},
        {"task_id": "t2", "task_type": "argus_smoke"},
        {"task_id": "t3", "task_type": "argus_smoke"},
    ])

    mock_redis = MagicMock()
    mock_redis.from_url = AsyncMock(side_effect=_make_call_seq(base_c, detail_c, bp_c))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
        result = await get_scheduler_backpressure_detail()

    assert result["queue_pressure"] == "CRITICAL"
    assert result["global_limit"] == 3


@pytest.mark.asyncio
async def test_active_resource_keys_populated():
    """resource_key set on running tasks → active_resource_keys list populated."""
    base_c   = _base_client(heartbeat=_fresh_hb(), running=1)
    detail_c = _detail_client()
    bp_c     = _bp_client(running_tasks=[
        {"task_id": "t1", "task_type": "ft_prepare_chain_run", "resource_key": "gpu_exclusive"},
    ])

    mock_redis = MagicMock()
    mock_redis.from_url = AsyncMock(side_effect=_make_call_seq(base_c, detail_c, bp_c))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
        result = await get_scheduler_backpressure_detail()

    assert "gpu_exclusive" in result["active_resource_keys"]
    assert len(result["active_resource_keys"]) == 1
