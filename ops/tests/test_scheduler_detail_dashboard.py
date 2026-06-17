#!/usr/bin/env python3
"""
get_scheduler_detail() dashboard tests (9 tests).

Validates the extended scheduler detail function in argus_orchestrator.py:

  1. Scheduler unavailable → default detail keys present, no Redis calls
  2. Redis error on base status → detail defaults present, no extra query
  3. Happy path — no completed/failed tasks → last_completed/last_failed = None
  4. Happy path — completed task present → last_completed dict with required fields
  5. Happy path — failed task present → last_failed dict with error field truncated
  6. Both last_completed and last_failed populated simultaneously
  7. zrange returns ID but hgetall returns empty dict → last_* = None
  8. Extra Redis error during detail query → base status intact, detail defaults
  9. completed_total always present regardless of path
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub optional runtime dependency before importing orchestrator ─────────────
sys.modules.setdefault("argus_code_agent", MagicMock())

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.argus.argus_orchestrator import get_scheduler_detail  # noqa: E402

# ── Keys that must always be present in detail output ─────────────────────────
DETAIL_KEYS = frozenset(
    {"available", "daemon_alive", "heartbeat_age_s", "stale",
     "pending", "running", "retrying", "failed", "held_for_review",
     "completed_total", "last_completed", "last_failed"}
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_base_redis_mock(
    *,
    heartbeat: str | None,
    pending: int = 0,
    running: int = 0,
    retrying: int = 0,
    failed: int = 0,
    held: int = 0,
) -> tuple[MagicMock, MagicMock]:
    """Mock for get_scheduler_status() — exactly 5 zcard calls."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=heartbeat)
    mock_client.zcard = AsyncMock(side_effect=[pending, running, retrying, failed, held])
    mock_client.aclose = AsyncMock()
    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(return_value=mock_client)
    return mock_redis_mod, mock_client


def _make_detail_redis_mock(
    *,
    completed_total: int = 0,
    last_completed_ids: list | None = None,
    last_failed_ids: list | None = None,
    completed_meta: dict | None = None,
    failed_meta: dict | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Mock for the second connection in get_scheduler_detail()."""
    mock_client = AsyncMock()

    # zcard returns completed_total; zrange returns ID lists; hgetall returns metadata
    zcard_results = [completed_total]
    zrange_results = [last_completed_ids or [], last_failed_ids or []]

    hgetall_results = []
    if last_completed_ids:
        hgetall_results.append(completed_meta or {})
    if last_failed_ids:
        hgetall_results.append(failed_meta or {})

    mock_client.zcard = AsyncMock(side_effect=zcard_results)
    mock_client.zrange = AsyncMock(side_effect=zrange_results)
    mock_client.hgetall = AsyncMock(side_effect=hgetall_results) if hgetall_results else AsyncMock(return_value={})
    mock_client.aclose = AsyncMock()

    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url = AsyncMock(return_value=mock_client)
    return mock_redis_mod, mock_client


def _fresh_hb() -> str:
    return str(int(time.time()) - 10)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detail_keys_always_present_scheduler_unavailable():
    """When scheduler is unavailable, all detail keys are present with defaults."""
    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", False):
        result = await get_scheduler_detail()
    assert DETAIL_KEYS.issubset(result.keys()), (
        f"Missing keys: {DETAIL_KEYS - result.keys()}"
    )
    assert result["available"] is False
    assert result["completed_total"] == 0
    assert result["last_completed"] is None
    assert result["last_failed"] is None


@pytest.mark.asyncio
async def test_detail_keys_present_on_redis_connection_error():
    """Redis error on base query → detail keys still present, error key present."""
    base_mock = MagicMock()
    base_mock.from_url = AsyncMock(side_effect=ConnectionError("refused"))

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", base_mock):
        result = await get_scheduler_detail()

    assert DETAIL_KEYS.issubset(result.keys()), (
        f"Missing keys: {DETAIL_KEYS - result.keys()}"
    )
    assert "error" in result
    assert result["completed_total"] == 0
    assert result["last_completed"] is None


@pytest.mark.asyncio
async def test_detail_empty_queues_no_last_tasks():
    """Fresh daemon with no completed/failed tasks → last_* = None, total = 0."""
    base_mock, _ = _make_base_redis_mock(heartbeat=_fresh_hb())
    detail_mock, _ = _make_detail_redis_mock(completed_total=0)

    call_count = 0

    def _from_url(url, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return base_mock.from_url.return_value
        return detail_mock.from_url.return_value

    combined_mock = MagicMock()
    combined_mock.from_url = AsyncMock(side_effect=_from_url)
    # Patch base client responses
    combined_mock.from_url.side_effect = None

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", base_mock):
        # Override: second call should use detail_mock
        original_from_url = base_mock.from_url
        call_seq = [base_mock.from_url.return_value, detail_mock.from_url.return_value]

        async def _multi_from_url(url, **kw):
            return call_seq.pop(0)

        base_mock.from_url.side_effect = _multi_from_url
        result = await get_scheduler_detail()

    assert result["daemon_alive"] is True
    assert result["completed_total"] == 0
    assert result["last_completed"] is None
    assert result["last_failed"] is None


@pytest.mark.asyncio
async def test_detail_last_completed_populated():
    """Last completed task returns correct fields from TaskMetadata hash."""
    meta = {
        "task_id": "argus-argus_smoke-abc123",
        "task_type": "argus_smoke",
        "display_name": "Argus Smoke Test",
        "created_at": "2026-06-09T20:00:00Z",
        "status": "completed",
    }
    base_mock, _ = _make_base_redis_mock(heartbeat=_fresh_hb())
    detail_mock, _ = _make_detail_redis_mock(
        completed_total=5,
        last_completed_ids=["argus-argus_smoke-abc123"],
        completed_meta=meta,
    )

    call_seq = [base_mock.from_url.return_value, detail_mock.from_url.return_value]

    async def _multi(url, **kw):
        return call_seq.pop(0)

    base_mock.from_url.side_effect = _multi

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", base_mock):
        result = await get_scheduler_detail()

    assert result["completed_total"] == 5
    lc = result["last_completed"]
    assert lc is not None
    assert lc["task_id"] == "argus-argus_smoke-abc123"
    assert lc["task_type"] == "argus_smoke"
    assert lc["display_name"] == "Argus Smoke Test"
    assert lc["created_at"] == "2026-06-09T20:00:00Z"


@pytest.mark.asyncio
async def test_detail_last_failed_truncates_error():
    """last_failed error field is truncated to 120 characters."""
    long_error = "x" * 200
    meta = {
        "task_id": "argus-argus_smoke-fail001",
        "task_type": "argus_smoke",
        "error": long_error,
        "created_at": "2026-06-09T21:00:00Z",
    }
    base_mock, _ = _make_base_redis_mock(heartbeat=_fresh_hb(), failed=1)
    detail_mock, _ = _make_detail_redis_mock(
        completed_total=0,
        last_failed_ids=["argus-argus_smoke-fail001"],
        failed_meta=meta,
    )

    call_seq = [base_mock.from_url.return_value, detail_mock.from_url.return_value]

    async def _multi(url, **kw):
        return call_seq.pop(0)

    base_mock.from_url.side_effect = _multi

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", base_mock):
        result = await get_scheduler_detail()

    lf = result["last_failed"]
    assert lf is not None
    assert len(lf["error"]) == 120
    assert lf["task_id"] == "argus-argus_smoke-fail001"


@pytest.mark.asyncio
async def test_detail_both_last_tasks_populated():
    """Both last_completed and last_failed can be returned simultaneously."""
    cmp_meta = {
        "task_id": "argus-argus_smoke-cmp",
        "task_type": "argus_smoke",
        "display_name": "Smoke OK",
        "created_at": "2026-06-09T19:00:00Z",
    }
    fail_meta = {
        "task_id": "argus-argus_smoke-fail",
        "task_type": "argus_smoke",
        "error": "connection refused",
        "created_at": "2026-06-09T20:00:00Z",
    }
    base_mock, _ = _make_base_redis_mock(heartbeat=_fresh_hb(), failed=1)
    detail_mock, _ = _make_detail_redis_mock(
        completed_total=3,
        last_completed_ids=["argus-argus_smoke-cmp"],
        last_failed_ids=["argus-argus_smoke-fail"],
        completed_meta=cmp_meta,
        failed_meta=fail_meta,
    )

    call_seq = [base_mock.from_url.return_value, detail_mock.from_url.return_value]

    async def _multi(url, **kw):
        return call_seq.pop(0)

    base_mock.from_url.side_effect = _multi

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", base_mock):
        result = await get_scheduler_detail()

    assert result["last_completed"] is not None
    assert result["last_failed"] is not None
    assert result["last_completed"]["task_id"] == "argus-argus_smoke-cmp"
    assert result["last_failed"]["task_id"] == "argus-argus_smoke-fail"


@pytest.mark.asyncio
async def test_detail_empty_hgetall_returns_none():
    """zrange returns a task ID but hgetall returns {} → last_* remains None."""
    base_mock, _ = _make_base_redis_mock(heartbeat=_fresh_hb())
    detail_mock, _ = _make_detail_redis_mock(
        completed_total=1,
        last_completed_ids=["orphan-task-id"],
        completed_meta={},   # empty hash → treat as None
    )

    call_seq = [base_mock.from_url.return_value, detail_mock.from_url.return_value]

    async def _multi(url, **kw):
        return call_seq.pop(0)

    base_mock.from_url.side_effect = _multi

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", base_mock):
        result = await get_scheduler_detail()

    assert result["completed_total"] == 1
    assert result["last_completed"] is None  # empty hgetall → None


@pytest.mark.asyncio
async def test_detail_redis_error_on_detail_query_preserves_base():
    """If detail Redis query fails, base status is returned intact with detail defaults."""
    base_mock, _ = _make_base_redis_mock(heartbeat=_fresh_hb(), pending=2)

    detail_client = AsyncMock()
    detail_client.zcard = AsyncMock(side_effect=ConnectionError("timeout"))
    detail_client.aclose = AsyncMock()
    detail_mock = MagicMock()
    detail_mock.from_url = AsyncMock(return_value=detail_client)

    call_seq = [base_mock.from_url.return_value, detail_client]

    async def _multi(url, **kw):
        return call_seq.pop(0)

    base_mock.from_url.side_effect = _multi

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", base_mock):
        result = await get_scheduler_detail()

    # Base fields intact
    assert result["available"] is True
    assert result["daemon_alive"] is True
    assert result["pending"] == 2
    # Detail fields at defaults
    assert result["completed_total"] == 0
    assert result["last_completed"] is None
    assert result["last_failed"] is None


@pytest.mark.asyncio
async def test_detail_completed_total_always_present():
    """completed_total key is present in every code path."""
    paths = [
        # unavailable
        {"_SCHEDULER_AVAILABLE": False},
    ]

    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", False):
        result = await get_scheduler_detail()
    assert "completed_total" in result

    # Redis error
    err_mock = MagicMock()
    err_mock.from_url = AsyncMock(side_effect=OSError("unreachable"))
    with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
         patch("ops.argus.argus_orchestrator._aioredis", err_mock):
        result = await get_scheduler_detail()
    assert "completed_total" in result
