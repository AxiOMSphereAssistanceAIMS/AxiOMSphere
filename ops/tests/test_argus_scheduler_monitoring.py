#!/usr/bin/env python3
"""
Phase 8/10: Argus scheduler monitoring tests (8 tests).

Validates get_scheduler_status() in argus_orchestrator.py across all code paths:

  1. Scheduler unavailable (_SCHEDULER_AVAILABLE=False)
  2. Redis connection error → error key present, daemon_alive=False
  3. Heartbeat key missing → daemon_alive=False, stale=True, queues present
  4. Fresh heartbeat (age < 150s) → daemon_alive=True, stale=False, correct age
  5. Stale heartbeat (age > 150s) → daemon_alive=False, stale=True
  6. Invalid heartbeat value (non-integer) → age=None, stale=True, daemon_alive=False
  7. All 5 queue ZCARDs returned with correct dict keys
  8. Required keys present in every return path
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub optional runtime dependency before importing orchestrator ─────────────
sys.modules.setdefault("argus_code_agent", MagicMock())

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.argus.argus_orchestrator import get_scheduler_status  # noqa: E402

# ── Required keys that every return path must include ─────────────────────────
REQUIRED_KEYS = frozenset(
    {"available", "daemon_alive", "heartbeat_age_s", "stale",
     "pending", "running", "retrying", "failed", "held_for_review"}
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_redis_mock(
    *,
    heartbeat: str | None,
    pending: int = 0,
    running: int = 0,
    retrying: int = 0,
    failed: int = 0,
    held: int = 0,
) -> tuple[MagicMock, MagicMock]:
    """Return (mock_redis_module, mock_client) with configured responses."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=heartbeat)
    mock_client.zcard = AsyncMock(side_effect=[pending, running, retrying, failed, held])
    mock_client.aclose = AsyncMock()

    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(return_value=mock_client)

    return mock_redis_mod, mock_client


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduler_unavailable_guard():
    """When _SCHEDULER_AVAILABLE=False, available=False with no Redis call."""
    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock()  # must NOT be called

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", False), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod):
        result = await get_scheduler_status()

    assert result["available"] is False
    assert result["daemon_alive"] is False
    mock_redis_mod.from_url.assert_not_called()
    assert REQUIRED_KEYS <= result.keys()


@pytest.mark.asyncio
async def test_redis_connection_error():
    """Redis connection failure → error key present, daemon_alive=False."""
    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(side_effect=ConnectionError("Redis refused"))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod):
        result = await get_scheduler_status()

    assert result["available"] is True
    assert result["daemon_alive"] is False
    assert result["stale"] is True
    assert "error" in result
    assert "Redis refused" in result["error"]
    assert REQUIRED_KEYS <= result.keys()


@pytest.mark.asyncio
async def test_missing_heartbeat_key():
    """Heartbeat key absent → daemon_alive=False, stale=True, queues populated."""
    mock_redis_mod, _ = _make_redis_mock(
        heartbeat=None, pending=3, running=1, retrying=0, failed=2, held=0
    )

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod):
        result = await get_scheduler_status()

    assert result["available"] is True
    assert result["daemon_alive"] is False
    assert result["stale"] is True
    assert result["heartbeat_age_s"] is None
    assert result["pending"] == 3
    assert result["running"] == 1
    assert result["failed"] == 2
    assert REQUIRED_KEYS <= result.keys()


@pytest.mark.asyncio
async def test_fresh_heartbeat():
    """Recent heartbeat (age < 150s) → daemon_alive=True, stale=False, correct age."""
    fresh_ts = str(int(time.time()) - 45)  # 45 seconds ago
    mock_redis_mod, _ = _make_redis_mock(heartbeat=fresh_ts)

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod):
        result = await get_scheduler_status()

    assert result["available"] is True
    assert result["daemon_alive"] is True
    assert result["stale"] is False
    assert result["heartbeat_age_s"] is not None
    # Allow ±5s for test execution drift
    assert 40 <= result["heartbeat_age_s"] <= 55
    assert REQUIRED_KEYS <= result.keys()


@pytest.mark.asyncio
async def test_stale_heartbeat():
    """Old heartbeat (age > 150s) → daemon_alive=False, stale=True."""
    stale_ts = str(int(time.time()) - 200)  # 200 seconds ago
    mock_redis_mod, _ = _make_redis_mock(heartbeat=stale_ts)

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod):
        result = await get_scheduler_status()

    assert result["available"] is True
    assert result["daemon_alive"] is False
    assert result["stale"] is True
    assert result["heartbeat_age_s"] >= 150
    assert REQUIRED_KEYS <= result.keys()


@pytest.mark.asyncio
async def test_invalid_heartbeat_value():
    """Non-integer heartbeat → age=None, stale=True, daemon_alive=False."""
    mock_redis_mod, _ = _make_redis_mock(heartbeat="not-a-timestamp")

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod):
        result = await get_scheduler_status()

    assert result["available"] is True
    assert result["daemon_alive"] is False
    assert result["stale"] is True
    assert result["heartbeat_age_s"] is None
    assert REQUIRED_KEYS <= result.keys()


@pytest.mark.asyncio
async def test_all_queue_counts_returned():
    """All 5 queue ZCARDs populate correct dict keys."""
    fresh_ts = str(int(time.time()) - 10)
    mock_redis_mod, _ = _make_redis_mock(
        heartbeat=fresh_ts,
        pending=7,
        running=2,
        retrying=1,
        failed=4,
        held=3,
    )

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", mock_redis_mod):
        result = await get_scheduler_status()

    assert result["pending"] == 7
    assert result["running"] == 2
    assert result["retrying"] == 1
    assert result["failed"] == 4
    assert result["held_for_review"] == 3


@pytest.mark.asyncio
async def test_all_required_keys_on_unavailable_path():
    """Even when scheduler unavailable, all required keys present (no KeyError risk)."""
    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", False):
        result = await get_scheduler_status()

    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"Missing keys on unavailable path: {missing}"
    # Queue counts must be 0, not None, so callers can safely do arithmetic
    for key in ("pending", "running", "retrying", "failed", "held_for_review"):
        assert result[key] == 0, f"{key} should be 0 on unavailable path, got {result[key]}"
