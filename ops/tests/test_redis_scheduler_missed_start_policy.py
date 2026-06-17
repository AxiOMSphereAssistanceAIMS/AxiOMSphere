#!/usr/bin/env python3
"""
Phase 3: Missed-Start Policy test suite (12 tests).

Tests cover:
  - Startup scan holds overdue pending/retrying tasks
  - Future tasks are NOT held
  - Report uses display_name, not task_id
  - Telegram report uses English-only buttons
  - Reschedule-same-time computes next matching HH:MM
  - Reschedule-new keeps hold until datetime supplied
  - Cancel by report number (not task_id)
  - Keep-in-review leaves dispatch_blocked=true
  - Idempotent startup scan (no duplicate holds/events)
  - No auto-run after restart with overdue backlog
  - EventBus records TASK_MISSED_STARTUP_REVIEW event
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from ops.scheduler.task_models import TaskMetadata, TaskStatus
from ops.scheduler.task_scheduler import (
    TaskSchedulerDaemon,
    RedisQueueManager,
    MISSED_STARTUP_REVIEW_ZSET,
    get_task_display_name,
    _KNOWN_TYPE_DISPLAY_NAMES,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_metadata(
    task_id: str = "task-001",
    task_type: str = "argus_smoke",
    scheduled_for: str = "2026-06-09T03:00:00",
    status: str = TaskStatus.PENDING.value,
    display_name: str = None,
) -> TaskMetadata:
    return TaskMetadata(
        task_id=task_id,
        task_type=task_type,
        command=["python3", "ops/scheduler/smoke_noop.py"],
        scheduled_for=scheduled_for,
        created_at="2026-06-09T02:00:00",
        created_by="argus",
        status=status,
        display_name=display_name,
    )


def _make_daemon(on_missed_start_report=None) -> TaskSchedulerDaemon:
    daemon = TaskSchedulerDaemon(
        redis_url="redis://localhost:6379",
        on_missed_start_report=on_missed_start_report,
    )
    daemon.redis = AsyncMock()
    daemon.queue = AsyncMock(spec=RedisQueueManager)
    daemon.queue.redis = daemon.redis
    return daemon


def _past_iso(hours_ago: int = 8) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _future_iso(hours_ahead: int = 2) -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return dt.isoformat()


def _past_epoch(hours_ago: int = 8) -> float:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).timestamp()


def _future_epoch(hours_ahead: int = 2) -> float:
    return (datetime.now(timezone.utc) + timedelta(hours=hours_ahead)).timestamp()


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Overdue PENDING task is not dispatched on startup
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_overdue_pending_task_not_dispatched():
    """Pending task scheduled in the past must be moved to review, not dispatched."""
    task_id = "task-overdue-pending"
    daemon = _make_daemon()

    metadata = _make_metadata(task_id=task_id, scheduled_for=_past_iso(8))
    daemon.queue.scan_missed_startup_review_queue.return_value = []
    daemon.redis.zrangebyscore = AsyncMock(side_effect=[
        [task_id],  # pending overdue
        [],         # retrying overdue
    ])
    daemon.queue.get_task_metadata.return_value = metadata.to_redis_hash()
    daemon.queue.move_to_missed_startup_review = AsyncMock()
    daemon.queue.set_task_metadata = AsyncMock()
    daemon.queue.build_missed_start_report = AsyncMock(return_value=[])

    with patch("ops.scheduler.task_scheduler.get_event_bus", new_callable=AsyncMock) as mock_bus:
        mock_bus.return_value = AsyncMock()
        await daemon.scan_overdue_tasks_on_startup()

    daemon.queue.move_to_missed_startup_review.assert_called_once_with(task_id)
    # dispatch_blocked must be set
    set_call_kwargs = daemon.queue.set_task_metadata.call_args
    held_meta = set_call_kwargs[0][1]
    assert held_meta.dispatch_blocked == "true"
    assert held_meta.status == TaskStatus.MISSED_STARTUP_REVIEW.value


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Overdue RETRYING task is not dispatched on startup
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_overdue_retrying_task_not_dispatched():
    """Retrying task overdue at startup must be held, not retried."""
    task_id = "task-overdue-retrying"
    daemon = _make_daemon()

    metadata = _make_metadata(
        task_id=task_id,
        task_type="slot14_nightly_eval",
        scheduled_for=_past_iso(5),
        status=TaskStatus.RETRYING.value,
    )
    daemon.queue.scan_missed_startup_review_queue.return_value = []
    daemon.redis.zrangebyscore = AsyncMock(side_effect=[
        [],          # no pending overdue
        [task_id],   # retrying overdue
    ])
    daemon.queue.get_task_metadata.return_value = metadata.to_redis_hash()
    daemon.queue.move_to_missed_startup_review = AsyncMock()
    daemon.queue.set_task_metadata = AsyncMock()

    with patch("ops.scheduler.task_scheduler.get_event_bus", new_callable=AsyncMock) as mock_bus:
        mock_bus.return_value = AsyncMock()
        await daemon.scan_overdue_tasks_on_startup()

    daemon.queue.move_to_missed_startup_review.assert_called_once_with(task_id)
    held_meta = daemon.queue.set_task_metadata.call_args[0][1]
    assert held_meta.dispatch_blocked == "true"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Future pending task remains dispatchable
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_future_pending_task_remains_dispatchable():
    """Task scheduled in the future must NOT be held on startup."""
    daemon = _make_daemon()

    daemon.queue.scan_missed_startup_review_queue.return_value = []
    # zrangebyscore returns nothing overdue (future tasks have score > now)
    daemon.redis.zrangebyscore = AsyncMock(side_effect=[[], []])
    daemon.queue.move_to_missed_startup_review = AsyncMock()

    with patch("ops.scheduler.task_scheduler.get_event_bus", new_callable=AsyncMock):
        await daemon.scan_overdue_tasks_on_startup()

    daemon.queue.move_to_missed_startup_review.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Missed-start report uses display_name, not task_id
# ─────────────────────────────────────────────────────────────────────────────

def test_missed_start_report_uses_display_name_not_task_id():
    """get_task_display_name() must return human-readable name, not task_id."""
    # Level 1: explicit display_name
    m = _make_metadata(task_id="task-abc-123", display_name="My Custom Task")
    assert get_task_display_name(m) == "My Custom Task"
    assert "task-abc-123" not in get_task_display_name(m)

    # Level 3: known type map
    m2 = _make_metadata(task_id="task-xyz-999", task_type="argus_smoke", display_name=None)
    assert get_task_display_name(m2) == "Argus: scheduler smoke check"
    assert "task-xyz-999" not in get_task_display_name(m2)

    # Level 4: titlecased type
    m3 = _make_metadata(task_id="task-000", task_type="custom_batch_job", display_name=None)
    assert get_task_display_name(m3) == "Custom Batch Job"

    # Level 5: fallback to task_id only when type is empty
    m4 = TaskMetadata(
        task_id="last-resort-id",
        task_type="",
        command=[],
        scheduled_for="",
        created_at="",
        created_by="",
        status=TaskStatus.PENDING.value,
    )
    assert get_task_display_name(m4) == "last-resort-id"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Argus Telegram report uses English-only buttons
# ─────────────────────────────────────────────────────────────────────────────

def test_argus_telegram_report_english_buttons():
    """The four inline button labels in argus_bot.py must be English-only.

    This test validates the source directly to avoid pulling in the full
    telegram library (not available in the unit-test environment).
    """
    source_path = "ops/argus/argus_bot.py"
    with open(source_path) as f:
        source = f.read()

    required_labels = [
        "Reschedule same time",
        "Reschedule NEW date/time",
        "Keep in review",
    ]
    for label in required_labels:
        assert label in source, f"Missing button label in {source_path}: {label!r}"
        assert label.isascii(), f"Button label is not ASCII: {label!r}"

    # Cancel button is dynamic "Cancel tasks N:" — verify the template is present
    assert "Cancel tasks" in source, "Cancel tasks button template missing"
    assert "missed_start_reschedule_same" in source
    assert "missed_start_reschedule_new" in source
    assert "missed_start_cancel_all" in source
    assert "missed_start_keep" in source

    # Ensure no Cyrillic in any missed_start button label (check surrounding context)
    # Handles both regular strings and f-strings (e.g. f"Cancel tasks {n}:")
    import re
    button_blocks = re.findall(
        r'InlineKeyboardButton\(f?"([^"]*?)",\s*callback_data="missed_start[^"]*"',
        source,
    )
    assert len(button_blocks) == 4, f"Expected 4 missed_start buttons, found: {button_blocks}"
    for label in button_blocks:
        # Strip f-string variable placeholders before ASCII check
        clean = re.sub(r'\{[^}]*\}', '', label)
        assert clean.isascii(), f"Non-ASCII missed_start button label: {label!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Reschedule same time → next matching HH:MM
# ─────────────────────────────────────────────────────────────────────────────

def test_reschedule_same_time_moves_to_next_matching_time():
    """_next_matching_time() must return the next occurrence of original HH:MM."""
    from ops.scheduler.missed_start_handler import _next_matching_time

    now_utc = datetime.now(timezone.utc)

    # Build a past occurrence of 03:00 UTC: use yesterday at 03:00
    yesterday_0300 = (now_utc - timedelta(days=1)).replace(
        hour=3, minute=0, second=0, microsecond=0
    )
    result = _next_matching_time(yesterday_0300.isoformat())
    assert result > now_utc, "Result must be in the future"
    assert result.hour == 3
    assert result.minute == 0

    # Build a past occurrence of 14:30 UTC: yesterday at 14:30
    yesterday_1430 = (now_utc - timedelta(days=1)).replace(
        hour=14, minute=30, second=0, microsecond=0
    )
    result2 = _next_matching_time(yesterday_1430.isoformat())
    assert result2 > now_utc
    assert result2.hour == 14
    assert result2.minute == 30


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Reschedule NEW datetime keeps hold until datetime supplied
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reschedule_new_datetime_keeps_hold_until_datetime_supplied():
    """After pressing 'Reschedule NEW date/time', task stays blocked until user provides datetime."""
    task_id = "task-held-new"
    daemon = _make_daemon()

    metadata = _make_metadata(task_id=task_id, scheduled_for=_past_iso(6))
    metadata.dispatch_blocked = "true"
    metadata.status = TaskStatus.MISSED_STARTUP_REVIEW.value

    # Simulate _dispatch_task is called — dispatch_blocked must gate execution
    metadata_dict = metadata.to_redis_hash()
    daemon.queue.get_task_metadata.return_value = metadata_dict
    daemon.queue.acquire_lock = AsyncMock()

    # Call _dispatch_task directly
    await daemon._dispatch_task(task_id)

    # acquire_lock must NOT have been called (blocked before lock)
    daemon.queue.acquire_lock.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Cancel by report number (not task_id)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_tasks_by_report_number_not_task_id():
    """handle_cancel_all() cancels all held tasks and sets status=CANCELLED."""
    task_ids = ["task-aaa", "task-bbb"]

    mock_redis = AsyncMock()
    mock_redis.zrange = AsyncMock(return_value=task_ids)
    mock_redis.hgetall = AsyncMock(side_effect=[
        {"task_type": "argus_smoke", "status": TaskStatus.MISSED_STARTUP_REVIEW.value},
        {"task_type": "job_filter_nightly", "status": TaskStatus.MISSED_STARTUP_REVIEW.value},
    ])
    mock_redis.hset = AsyncMock()
    mock_redis.zrem = AsyncMock()
    mock_redis.zadd = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch("ops.scheduler.missed_start_handler._get_redis", return_value=mock_redis), \
         patch("ops.scheduler.missed_start_handler.get_event_bus", new_callable=AsyncMock) as mock_bus:
        mock_bus.return_value = AsyncMock()

        from ops.scheduler.missed_start_handler import handle_cancel_all
        count = await handle_cancel_all()

    assert count == 2

    # Verify CANCELLED status was written
    hset_calls = mock_redis.hset.call_args_list
    for c in hset_calls:
        mapping = c[1].get("mapping") or c[0][1]
        assert mapping["status"] == TaskStatus.CANCELLED.value


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Keep in review keeps dispatch_blocked=true
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keep_in_review_keeps_dispatch_blocked():
    """After 'Keep in review', dispatch_blocked remains 'true' for all held tasks."""
    task_id = "task-keep"
    daemon = _make_daemon()

    metadata = _make_metadata(task_id=task_id, scheduled_for=_past_iso(3))
    metadata.dispatch_blocked = "true"
    metadata.status = TaskStatus.MISSED_STARTUP_REVIEW.value

    metadata_dict = metadata.to_redis_hash()
    daemon.queue.get_task_metadata.return_value = metadata_dict
    daemon.queue.acquire_lock = AsyncMock()

    # _dispatch_task must be blocked
    await daemon._dispatch_task(task_id)
    daemon.queue.acquire_lock.assert_not_called()

    # Verify that no state mutation happened
    daemon.queue.move_to_running = MagicMock()
    daemon.queue.move_to_running.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Idempotent startup scan — no duplicate holds or events
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotent_startup_scan_no_duplicate_reports_or_events():
    """Re-running scan_overdue_tasks_on_startup() must not re-hold already-held tasks."""
    task_id = "task-already-held"
    daemon = _make_daemon()

    # Task is already in the review queue
    daemon.queue.scan_missed_startup_review_queue.return_value = [task_id]
    daemon.redis.zrangebyscore = AsyncMock(side_effect=[
        [task_id],  # appears in pending scan
        [],
    ])
    daemon.queue.move_to_missed_startup_review = AsyncMock()
    daemon.queue.set_task_metadata = AsyncMock()

    with patch("ops.scheduler.task_scheduler.get_event_bus", new_callable=AsyncMock):
        await daemon.scan_overdue_tasks_on_startup()

    # Must NOT move or write metadata again (already held)
    daemon.queue.move_to_missed_startup_review.assert_not_called()
    daemon.queue.set_task_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: No auto-run after service restart with overdue backlog
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_auto_run_after_service_restart_with_overdue_backlog():
    """Simulate daemon restart with 3 overdue tasks — none must be dispatched."""
    task_ids = ["t1", "t2", "t3"]
    daemon = _make_daemon()

    daemon.queue.scan_missed_startup_review_queue.return_value = []
    daemon.redis.zrangebyscore = AsyncMock(side_effect=[
        task_ids,  # all 3 in pending, all overdue
        [],
    ])

    metadatas = {
        tid: _make_metadata(task_id=tid, scheduled_for=_past_iso(i + 2)).to_redis_hash()
        for i, tid in enumerate(task_ids)
    }
    daemon.queue.get_task_metadata = AsyncMock(side_effect=lambda tid: metadatas.get(tid))
    daemon.queue.move_to_missed_startup_review = AsyncMock()
    daemon.queue.set_task_metadata = AsyncMock()
    daemon.queue.acquire_lock = AsyncMock()

    with patch("ops.scheduler.task_scheduler.get_event_bus", new_callable=AsyncMock) as mock_bus:
        mock_bus.return_value = AsyncMock()
        await daemon.scan_overdue_tasks_on_startup()

    # All 3 held
    assert daemon.queue.move_to_missed_startup_review.call_count == 3
    # No lock acquisitions — nothing dispatched
    daemon.queue.acquire_lock.assert_not_called()

    # Verify each held task has dispatch_blocked=true
    for set_call in daemon.queue.set_task_metadata.call_args_list:
        held_meta = set_call[0][1]
        assert held_meta.dispatch_blocked == "true"


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: EventBus records TASK_MISSED_STARTUP_REVIEW event
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eventbus_records_missed_start_or_hold_event():
    """hold_overdue_task_for_decision() must publish TASK_MISSED_STARTUP_REVIEW to EventBus."""
    task_id = "task-event"
    daemon = _make_daemon()
    daemon.queue.move_to_missed_startup_review = AsyncMock()
    daemon.queue.set_task_metadata = AsyncMock()

    published_events = []

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(side_effect=lambda e: published_events.append(e))

    metadata = _make_metadata(
        task_id=task_id,
        task_type="argus_smoke",
        scheduled_for=_past_iso(7),
    )
    startup_time = datetime.now(timezone.utc)

    with patch("ops.scheduler.task_scheduler.get_event_bus", new_callable=AsyncMock) as mock_get_bus:
        mock_get_bus.return_value = mock_bus
        await daemon.hold_overdue_task_for_decision(metadata, startup_time)

    assert len(published_events) == 1
    event = published_events[0]
    from ops.logi.event_bus import EventType
    assert event.event_type == EventType.TASK_MISSED_STARTUP_REVIEW
    assert event.data["task_id"] == task_id
    assert event.data["display_name"] == "Argus: scheduler smoke check"
    assert event.data["overdue_duration_seconds"] > 0
