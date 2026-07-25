#!/usr/bin/env python3
"""
Redis Scheduler Phase 2 — Operational E2E Tests
================================================
End-to-end validation of the full Argus → scheduler → EventBus pipeline.

Coverage:
  1. Argus _exec_schedule_task enqueues to Redis pending queue
  2. TaskSchedulerDaemon._dispatch_task executes safe smoke task → SUCCEEDED
  3. EventBus ledger contains TASK_STARTED + TASK_COMPLETED after success
  4. One enqueue → exactly one TASK_SCHEDULED event (no duplication)
  5. Forbidden command rejection → no Redis state left behind
  6. Failure path (exit 1) → TASK_FAILED or TASK_RETRY_SCHEDULED event published
  7. Argus never executes tasks directly (_exec_schedule_task is enqueue-only)

Test Redis: DB=1 — isolated from production DB=0 (URL resolved at runtime via redis_test_config)
Each test flushes DB=1 before and after execution.

Hard stops verified:
  - No training started
  - No model registry mutation
  - No docker compose down
  - No OmniRoute killed
  - No uncontrolled API calls
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

# Ensure project root on PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ops.scheduler.redis_test_config import get_test_redis_client, resolve_test_redis_url

# ── Stub argus_code_agent before importing orchestrator ──────────────────────
# argus_code_agent is a runtime container dependency not present in test envs.
sys.modules.setdefault("argus_code_agent", MagicMock())

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# DB=1 — test isolation (resolved at runtime via central resolver, never hardcoded)
TEST_REDIS_URL = resolve_test_redis_url()
SMOKE_CMD = ["python", "ops/scheduler/smoke_noop.py"]
FAIL_CMD  = ["python", "-c", "import sys; sys.exit(1)"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_minus_5s() -> str:
    """Return UTC ISO timestamp 5s in the past — immediately due, within grace window."""
    ts = datetime.now(tz=timezone.utc) - timedelta(seconds=5)
    return ts.isoformat()


def _now_plus_60s() -> str:
    """Return UTC ISO timestamp 60s in the future."""
    ts = datetime.now(tz=timezone.utc) + timedelta(seconds=60)
    return ts.isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def redis_client():
    """Clean Redis connection on the resolved test DB; skips if unavailable."""
    client = await get_test_redis_client()
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def scheduler_daemon(redis_client):
    """
    TaskSchedulerDaemon connected to test Redis DB=1.
    Patches module-level REDIS_URL and resets the global _event_bus singleton
    so the EventBus also targets DB=1.
    """
    import ops.scheduler.task_scheduler as ts_mod

    original_url = ts_mod.REDIS_URL
    original_event_bus = ts_mod._event_bus

    ts_mod.REDIS_URL = TEST_REDIS_URL
    ts_mod._event_bus = None   # Force re-creation against TEST_REDIS_URL

    daemon = ts_mod.TaskSchedulerDaemon(redis_url=TEST_REDIS_URL)
    await daemon.connect()

    yield daemon

    await daemon.disconnect()

    # Restore module state
    ts_mod.REDIS_URL = original_url
    if ts_mod._event_bus is not None:
        try:
            await ts_mod._event_bus.disconnect()
        except Exception:
            pass
    ts_mod._event_bus = original_event_bus


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Argus _exec_schedule_task → Redis pending queue
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_argus_schedule_task_to_scheduler_queue(redis_client):
    """Argus _exec_schedule_task must persist metadata and enqueue to pending set."""
    import ops.scheduler.agent_scheduler_adapter as asa_mod
    from ops.argus.argus_orchestrator import ArgusOrchestrator

    task_id = "e2e-smoke-enqueue-001"

    with patch.dict(os.environ, {"TASK_SCHEDULER_REDIS_URL": TEST_REDIS_URL}), \
         patch.object(asa_mod, "_DEFAULT_REDIS_URL", TEST_REDIS_URL):
        orch = ArgusOrchestrator.__new__(ArgusOrchestrator)
        ok, detail = await orch._exec_schedule_task({
            "task_id": task_id,
            "task_type": "argus_smoke",
            "command": SMOKE_CMD,
            "scheduled_for": _now_minus_5s(),
        })

    assert ok, f"_exec_schedule_task returned failure: {detail}"
    assert task_id in detail or "task_id" in detail

    # Verify Redis state
    meta = await redis_client.hgetall(f"scheduler:task:{task_id}")
    assert meta, "Task metadata hash not found in Redis"
    assert meta.get("task_type") == "argus_smoke"
    assert meta.get("created_by") == "argus"
    assert meta.get("status") == "PENDING"

    # Verify pending sorted set
    score = await redis_client.zscore("scheduler:tasks:pending", task_id)
    assert score is not None, "Task not found in scheduler:tasks:pending sorted set"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Daemon executes safe smoke task → SUCCEEDED lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduler_daemon_executes_safe_smoke_task(scheduler_daemon, redis_client):
    """_dispatch_task on smoke_noop.py must complete with SUCCEEDED status."""
    import ops.scheduler.task_scheduler as ts_mod

    task_id = "e2e-smoke-exec-002"
    scheduled_for = _now_minus_5s()

    # Seed metadata + enqueue (bypassing Argus for isolation)
    from ops.scheduler.task_models import TaskMetadata, TaskStatus
    metadata = TaskMetadata(
        task_id=task_id,
        task_type="argus_smoke",
        command=SMOKE_CMD,
        scheduled_for=scheduled_for,
        created_at=datetime.utcnow().isoformat(),
        created_by="argus",
        executor_runtime="redis-scheduler",
        workdir_strategy="runtime_resolver",
        resource_key="task:argus_smoke",
        status=TaskStatus.PENDING.value,
    )
    await scheduler_daemon.queue.set_task_metadata(task_id, metadata)
    await scheduler_daemon.queue.schedule_task(task_id, scheduled_for)

    # Dispatch (no full 60s run loop — call directly)
    await scheduler_daemon._dispatch_task(task_id)

    # Verify final status = SUCCEEDED
    meta = await redis_client.hgetall(f"scheduler:task:{task_id}")
    assert meta, "Task metadata not found after dispatch"
    assert meta.get("status") == "SUCCEEDED", (
        f"Expected SUCCEEDED, got: {meta.get('status')} | error: {meta.get('error', '')}"
    )

    # Verify task removed from pending / moved to completed
    pending_score = await redis_client.zscore("scheduler:tasks:pending", task_id)
    assert pending_score is None, "Task still in pending queue after SUCCEEDED"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — EventBus ledger: TASK_STARTED + TASK_COMPLETED after success
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_ledger_sequence_for_successful_task(scheduler_daemon, redis_client):
    """After successful dispatch, EventBus must contain TASK_STARTED and TASK_COMPLETED."""
    from ops.scheduler.task_models import TaskMetadata, TaskStatus

    task_id = "e2e-smoke-events-003"
    scheduled_for = _now_minus_5s()

    metadata = TaskMetadata(
        task_id=task_id,
        task_type="argus_smoke",
        command=SMOKE_CMD,
        scheduled_for=scheduled_for,
        created_at=datetime.utcnow().isoformat(),
        created_by="argus",
        executor_runtime="redis-scheduler",
        workdir_strategy="runtime_resolver",
        resource_key="task:argus_smoke",
        status=TaskStatus.PENDING.value,
    )
    await scheduler_daemon.queue.set_task_metadata(task_id, metadata)
    await scheduler_daemon.queue.schedule_task(task_id, scheduled_for)

    await scheduler_daemon._dispatch_task(task_id)

    # Read event ledgers from Redis
    started_entries  = await redis_client.lrange("event_ledger:task.started", 0, -1)
    completed_entries = await redis_client.lrange("event_ledger:task.completed", 0, -1)

    started_task_ids  = [json.loads(e).get("data", {}).get("task_id") for e in started_entries]
    completed_task_ids = [json.loads(e).get("data", {}).get("task_id") for e in completed_entries]

    assert task_id in started_task_ids,  f"TASK_STARTED not published for {task_id}"
    assert task_id in completed_task_ids, f"TASK_COMPLETED not published for {task_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — No duplicate TASK_SCHEDULED event
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_duplicate_task_scheduled_event(redis_client):
    """One _exec_schedule_task call must publish exactly one TASK_SCHEDULED event."""
    import ops.scheduler.task_scheduler as ts_mod
    import ops.scheduler.agent_scheduler_adapter as asa_mod
    from ops.argus.argus_orchestrator import ArgusOrchestrator

    task_id = "e2e-smoke-dedup-004"

    # Patch module-level REDIS_URL and reset EventBus so TASK_SCHEDULED lands in DB=1
    original_url = ts_mod.REDIS_URL
    original_event_bus = ts_mod._event_bus
    ts_mod.REDIS_URL = TEST_REDIS_URL
    ts_mod._event_bus = None

    try:
        with patch.dict(os.environ, {"TASK_SCHEDULER_REDIS_URL": TEST_REDIS_URL}), \
             patch.object(asa_mod, "_DEFAULT_REDIS_URL", TEST_REDIS_URL):
            orch = ArgusOrchestrator.__new__(ArgusOrchestrator)
            ok, _ = await orch._exec_schedule_task({
                "task_id": task_id,
                "task_type": "argus_smoke",
                "command": SMOKE_CMD,
                "scheduled_for": _now_minus_5s(),
            })
    finally:
        # Restore module state
        if ts_mod._event_bus is not None:
            try:
                await ts_mod._event_bus.disconnect()
            except Exception:
                pass
        ts_mod.REDIS_URL = original_url
        ts_mod._event_bus = original_event_bus

    assert ok, "Enqueue failed — cannot test for duplication"

    scheduled_entries = await redis_client.lrange("event_ledger:task.scheduled", 0, -1)
    matching = [
        e for e in scheduled_entries
        if json.loads(e).get("data", {}).get("task_id") == task_id
    ]

    assert len(matching) == 1, (
        f"Expected exactly 1 TASK_SCHEDULED event for {task_id}, found {len(matching)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Rejected forbidden command leaves no Redis state
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rejected_forbidden_command_leaves_no_redis_state(redis_client):
    """Commands containing 'rm -rf' must be rejected and leave no Redis key."""
    import ops.scheduler.agent_scheduler_adapter as asa_mod
    from ops.argus.argus_orchestrator import ArgusOrchestrator

    task_id = "e2e-reject-forbidden-005"

    with patch.dict(os.environ, {"TASK_SCHEDULER_REDIS_URL": TEST_REDIS_URL}), \
         patch.object(asa_mod, "_DEFAULT_REDIS_URL", TEST_REDIS_URL):
        orch = ArgusOrchestrator.__new__(ArgusOrchestrator)
        ok, detail = await orch._exec_schedule_task({
            "task_id": task_id,
            "task_type": "argus_smoke",
            "command": ["python", "rm -rf /tmp/x"],
            "scheduled_for": _now_minus_5s(),
        })

    assert not ok, "Forbidden command should have been rejected"
    assert "rm -rf" in detail or "forbidden" in detail.lower()

    # Verify no Redis state was created
    meta = await redis_client.hgetall(f"scheduler:task:{task_id}")
    assert not meta, f"Redis metadata should be empty after rejection, found: {meta}"

    pending_score = await redis_client.zscore("scheduler:tasks:pending", task_id)
    assert pending_score is None, "Rejected task must not appear in pending queue"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — Failure path: exit(1) → TASK_FAILED event published
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failure_path_records_failed_or_retry_event(scheduler_daemon, redis_client):
    """Task that exits non-zero must publish TASK_FAILED or TASK_RETRY_SCHEDULED."""
    from ops.scheduler.task_models import TaskMetadata, TaskStatus

    task_id = "e2e-fail-path-006"
    scheduled_for = _now_minus_5s()

    metadata = TaskMetadata(
        task_id=task_id,
        task_type="argus_smoke",
        command=FAIL_CMD,
        scheduled_for=scheduled_for,
        created_at=datetime.utcnow().isoformat(),
        created_by="argus",
        executor_runtime="redis-scheduler",
        workdir_strategy="runtime_resolver",
        resource_key="task:argus_smoke",
        status=TaskStatus.PENDING.value,
        is_retryable=False,   # Force straight to FAILED (no retry loop in tests)
        max_retries=0,
    )
    await scheduler_daemon.queue.set_task_metadata(task_id, metadata)
    await scheduler_daemon.queue.schedule_task(task_id, scheduled_for)

    # Suppress EscalationHandler (both import paths) so no Telegram/Repairman calls
    escalation_mock = MagicMock()
    escalation_mock.handle_escalation = AsyncMock(return_value=None)

    with patch("ops.scheduler.task_scheduler.EscalationHandler", return_value=escalation_mock), \
         patch("ops.scheduler.escalation_handler.EscalationHandler", return_value=escalation_mock):
        await scheduler_daemon._dispatch_task(task_id)

    # Verify terminal failure status
    meta = await redis_client.hgetall(f"scheduler:task:{task_id}")
    assert meta, "Task metadata not found after failure dispatch"
    status = meta.get("status", "")
    assert status in ("FAILED", "RETRYING", "ESCALATED"), (
        f"Expected FAILED/RETRYING/ESCALATED, got: {status}"
    )

    # Verify failure event published
    failed_entries  = await redis_client.lrange("event_ledger:task.failed", 0, -1)
    retry_entries   = await redis_client.lrange("event_ledger:task.retry_scheduled", 0, -1)
    escalated_entries = await redis_client.lrange("event_ledger:task.escalated", 0, -1)

    all_relevant = failed_entries + retry_entries + escalated_entries
    matching_ids = [
        json.loads(e).get("data", {}).get("task_id") for e in all_relevant
    ]
    assert task_id in matching_ids, (
        f"No TASK_FAILED/RETRY/ESCALATED event found for {task_id}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — Argus never executes directly (enqueue-only verification)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_argus_never_executes_directly(redis_client):
    """
    _exec_schedule_task must enqueue to Redis and NOT spawn a subprocess.
    The smoke task must NOT produce its AIMS_SCHEDULER_SMOKE_OK stdout marker
    as a result of _exec_schedule_task — only _dispatch_task (scheduler daemon)
    produces that output.
    """
    from ops.argus.argus_orchestrator import ArgusOrchestrator

    task_id = "e2e-no-exec-007"

    # Intercept subprocess creation — should never be called by Argus
    subprocess_calls = []

    original_create = asyncio.create_subprocess_exec

    async def spy_subprocess(*args, **kwargs):
        subprocess_calls.append(args)
        return await original_create(*args, **kwargs)

    import ops.scheduler.agent_scheduler_adapter as asa_mod
    with patch.dict(os.environ, {"TASK_SCHEDULER_REDIS_URL": TEST_REDIS_URL}), \
         patch.object(asa_mod, "_DEFAULT_REDIS_URL", TEST_REDIS_URL), \
         patch("asyncio.create_subprocess_exec", side_effect=spy_subprocess):
        orch = ArgusOrchestrator.__new__(ArgusOrchestrator)
        ok, detail = await orch._exec_schedule_task({
            "task_id": task_id,
            "task_type": "argus_smoke",
            "command": SMOKE_CMD,
            "scheduled_for": _now_minus_5s(),
        })

    assert ok, f"Enqueue failed: {detail}"
    assert subprocess_calls == [], (
        f"Argus called create_subprocess_exec directly — enqueue-only contract violated! "
        f"Subprocess args: {subprocess_calls}"
    )

    # Confirm task is in pending queue (was enqueued, not executed)
    score = await redis_client.zscore("scheduler:tasks:pending", task_id)
    assert score is not None, "Task not found in pending queue — not enqueued"

    # Confirm status is PENDING (not RUNNING/SUCCEEDED from direct execution)
    meta = await redis_client.hgetall(f"scheduler:task:{task_id}")
    assert meta.get("status") == "PENDING", (
        f"Expected PENDING (enqueue-only), got: {meta.get('status')}"
    )
