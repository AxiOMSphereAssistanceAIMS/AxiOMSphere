#!/usr/bin/env python3
"""
Integration tests for heartbeat monitoring and crash detection.

Tests:
1. Heartbeat write and verify
2. Heartbeat expiry detection (task marked crashed)
3. Auto-retry after crash (retry_count incremented)
4. Max retries exhausted after crash (escalation triggered)
5. Concurrent crash recovery (multiple tasks)
"""

import asyncio
import os
import pytest
import pytest_asyncio
import time
from datetime import datetime

import redis.asyncio as redis

from ops.scheduler.heartbeat_monitor import HeartbeatMonitor, CrashDetectionConfig
from ops.scheduler.retry_manager import RetryManager


@pytest_asyncio.fixture
async def redis_client():
    """Redis async client fixture with multi-URL fallback."""
    # Try Docker container IP first, fall back to localhost
    redis_urls = [
        os.getenv("AIMS_TEST_REDIS_URL", "redis://172.18.0.26:6379/1"),  # Env var override
        "redis://aims-redis:6379/1",   # Docker network (if running in container)
        "redis://localhost:6379/1",    # Localhost fallback
    ]

    client = None
    for redis_url in redis_urls:
        try:
            client = await redis.from_url(redis_url, decode_responses=True)
            await client.ping()  # Verify connection works
            break
        except Exception as e:
            continue

    if client is None:
        raise RuntimeError(f"Could not connect to Redis on any of {redis_urls}")

    await client.flushdb()  # Clean before each test
    yield client
    await client.flushdb()  # Clean after each test
    await client.close()


@pytest.fixture
def crash_config():
    """Crash detection config with short timeouts for testing."""
    return CrashDetectionConfig(
        heartbeat_ttl_sec=5,  # 5s for fast testing
        heartbeat_check_interval_sec=1,  # Check every 1s
        stale_threshold_sec=10,  # Stale after 10s
        max_retries_on_crash=2,
    )


@pytest.fixture
def retry_manager():
    """Retry manager for backoff calculation."""
    return RetryManager()


@pytest_asyncio.fixture
async def monitor(redis_client, crash_config, retry_manager):
    """HeartbeatMonitor fixture."""
    return HeartbeatMonitor(
        redis_client=redis_client,
        config=crash_config,
        retry_manager=retry_manager,
    )


@pytest.mark.asyncio
async def test_heartbeat_write_and_verify(redis_client, monitor):
    """Test writing and reading heartbeat from Redis."""
    task_id = "task-001"

    # Write heartbeat
    success = await monitor.write_heartbeat(task_id)
    assert success is True

    # Verify heartbeat exists
    heartbeat_age = await monitor.check_task_heartbeat(task_id)
    assert heartbeat_age is not None
    assert 0 <= heartbeat_age < 1  # Should be very fresh


@pytest.mark.asyncio
async def test_heartbeat_ttl_expiry(redis_client, monitor):
    """Test that heartbeat expires after TTL."""
    task_id = "task-002"

    # Write heartbeat
    await monitor.write_heartbeat(task_id)
    assert await monitor.check_task_heartbeat(task_id) is not None

    # Wait for TTL to expire
    await asyncio.sleep(monitor.config.heartbeat_ttl_sec + 1)

    # Heartbeat should be gone
    heartbeat_age = await monitor.check_task_heartbeat(task_id)
    assert heartbeat_age is None


@pytest.mark.asyncio
async def test_crash_detection_marks_crashed_status(redis_client, monitor):
    """Test that missing heartbeat marks task as CRASHED."""
    task_id = "task-003"

    # Create task in RUNNING state
    await redis_client.hset(
        f"scheduler:task:{task_id}",
        mapping={
            "task_type": "test_task",
            "command": '["echo", "test"]',
            "status": "RUNNING",
            "retry_count": 0,
            "max_retries": 3,
            "scheduled_for": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "test",
        },
    )

    # Add to RUNNING queue
    await redis_client.zadd("scheduler:tasks:running", {task_id: time.time()})

    # Don't write heartbeat → simulate crash

    # Run crash detection
    await monitor._check_heartbeats()

    # Verify task marked RETRYING (crashes with retries remaining immediately transition)
    task_status = await redis_client.hget(f"scheduler:task:{task_id}", "status")
    assert task_status == "RETRYING"


@pytest.mark.asyncio
async def test_auto_retry_on_crash(redis_client, monitor):
    """Test that crashed task is auto-retried if retries remain."""
    task_id = "task-004"

    # Create task with retry_count=0, max_retries=3
    await redis_client.hset(
        f"scheduler:task:{task_id}",
        mapping={
            "task_type": "test_task",
            "command": '["echo", "test"]',
            "status": "RUNNING",
            "retry_count": 0,
            "max_retries": 3,
            "scheduled_for": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "test",
        },
    )

    await redis_client.zadd("scheduler:tasks:running", {task_id: time.time()})

    # Run crash detection
    await monitor._check_heartbeats()

    # Verify task moved to RETRYING
    task_status = await redis_client.hget(f"scheduler:task:{task_id}", "status")
    assert task_status == "RETRYING"

    # Verify retry_count incremented
    retry_count = int(await redis_client.hget(f"scheduler:task:{task_id}", "retry_count"))
    assert retry_count == 1

    # Verify task in RETRYING queue
    retrying_tasks = await redis_client.zrange("scheduler:tasks:retrying", 0, -1)
    assert task_id in retrying_tasks


@pytest.mark.asyncio
async def test_escalation_on_max_retries_after_crash(redis_client, monitor):
    """Test that task is escalated after max retries exhausted."""
    task_id = "task-005"

    # Create task with retry_count=2, max_retries=2 (at limit)
    await redis_client.hset(
        f"scheduler:task:{task_id}",
        mapping={
            "task_type": "test_task",
            "command": '["echo", "test"]',
            "status": "RUNNING",
            "retry_count": 2,
            "max_retries": 2,
            "scheduled_for": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "test",
        },
    )

    await redis_client.zadd("scheduler:tasks:running", {task_id: time.time()})

    # Run crash detection
    await monitor._check_heartbeats()

    # Verify task marked FAILED (escalation)
    task_status = await redis_client.hget(f"scheduler:task:{task_id}", "status")
    assert task_status == "FAILED"

    # Verify task in FAILED queue
    failed_tasks = await redis_client.zrange("scheduler:tasks:failed", 0, -1)
    assert task_id in failed_tasks


@pytest.mark.asyncio
async def test_concurrent_crash_recovery(redis_client, monitor):
    """Test crash recovery for multiple tasks simultaneously."""
    task_ids = ["task-006", "task-007", "task-008"]

    # Create 3 tasks in RUNNING state
    for task_id in task_ids:
        await redis_client.hset(
            f"scheduler:task:{task_id}",
            mapping={
                "task_type": "test_task",
                "command": '["echo", "test"]',
                "status": "RUNNING",
                "retry_count": 0,
                "max_retries": 3,
                "scheduled_for": datetime.utcnow().isoformat(),
                "created_at": datetime.utcnow().isoformat(),
                "created_by": "test",
            },
        )
        await redis_client.zadd("scheduler:tasks:running", {task_id: time.time()})

    # Run crash detection
    await monitor._check_heartbeats()

    # All 3 should be marked CRASHED and moved to RETRYING
    for task_id in task_ids:
        task_status = await redis_client.hget(f"scheduler:task:{task_id}", "status")
        assert task_status == "RETRYING"

    retrying_tasks = await redis_client.zrange("scheduler:tasks:retrying", 0, -1)
    assert len(retrying_tasks) == 3


@pytest.mark.asyncio
async def test_healthy_heartbeat_not_retried(redis_client, monitor):
    """Test that tasks with healthy heartbeat are not marked crashed."""
    task_id = "task-009"

    # Create task in RUNNING state
    await redis_client.hset(
        f"scheduler:task:{task_id}",
        mapping={
            "task_type": "test_task",
            "command": '["echo", "test"]',
            "status": "RUNNING",
            "retry_count": 0,
            "max_retries": 3,
            "scheduled_for": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "test",
        },
    )

    await redis_client.zadd("scheduler:tasks:running", {task_id: time.time()})

    # Write fresh heartbeat
    await monitor.write_heartbeat(task_id)

    # Run crash detection
    await monitor._check_heartbeats()

    # Verify task still RUNNING (not marked CRASHED)
    task_status = await redis_client.hget(f"scheduler:task:{task_id}", "status")
    assert task_status == "RUNNING"

    # Verify NOT in RETRYING queue
    retrying_tasks = await redis_client.zrange("scheduler:tasks:retrying", 0, -1)
    assert task_id not in retrying_tasks


@pytest.mark.asyncio
async def test_stale_heartbeat_detection(redis_client, monitor):
    """Test detection of stale heartbeat (old but not expired)."""
    task_id = "task-010"

    # Create task in RUNNING state
    await redis_client.hset(
        f"scheduler:task:{task_id}",
        mapping={
            "task_type": "test_task",
            "command": '["echo", "test"]',
            "status": "RUNNING",
            "retry_count": 0,
            "max_retries": 3,
            "scheduled_for": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "test",
        },
    )

    await redis_client.zadd("scheduler:tasks:running", {task_id: time.time()})

    # Write heartbeat, then wait for it to become stale (but not expire)
    old_time = time.time() - (monitor.config.stale_threshold_sec + 1)
    await redis_client.setex(
        f"scheduler:heartbeat:{task_id}",
        monitor.config.heartbeat_ttl_sec + 100,  # Long TTL so it doesn't expire
        str(old_time),
    )

    # Run crash detection
    await monitor._check_heartbeats()

    # Verify task marked RETRYING (stale heartbeat with retries remaining immediately transitions)
    task_status = await redis_client.hget(f"scheduler:task:{task_id}", "status")
    assert task_status == "RETRYING"


@pytest.mark.asyncio
async def test_crash_metadata_updated(redis_client, monitor):
    """Test that crash metadata is properly recorded."""
    task_id = "task-011"

    await redis_client.hset(
        f"scheduler:task:{task_id}",
        mapping={
            "task_type": "test_task",
            "command": '["echo", "test"]',
            "status": "RUNNING",
            "retry_count": 0,
            "max_retries": 3,
            "scheduled_for": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "test",
        },
    )

    await redis_client.zadd("scheduler:tasks:running", {task_id: time.time()})

    # Run crash detection
    await monitor._check_heartbeats()

    # Verify crash metadata
    task_data = await redis_client.hgetall(f"scheduler:task:{task_id}")
    assert "crashed_at" in task_data
    assert "crash_reason" in task_data
    assert task_data["crash_reason"] == "Heartbeat expired (task not writing)"
