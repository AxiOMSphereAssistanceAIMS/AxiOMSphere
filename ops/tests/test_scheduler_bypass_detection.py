#!/usr/bin/env python3
"""
Bypass detection tests — verifies that the backpressure gate in
TaskSchedulerDaemon._dispatch_task() correctly defers tasks when
ResourcePolicy denies dispatch.

Uses AsyncMock to inject policy decisions without a live Redis.
"""

import pytest
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

from ops.scheduler.task_models import TaskMetadata, TaskStatus
from ops.scheduler.resource_policy import PolicyDecision, PolicyViolation


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_metadata_dict(
    task_type="argus_smoke",
    created_by="argus",
    model_slot="",
    resource_key="",
    dispatch_blocked="",
):
    return {
        "task_id": "t1",
        "task_type": task_type,
        "command": json.dumps(["echo", "test"]),
        "scheduled_for": "2026-06-10T00:00:00+00:00",
        "created_at": "2026-06-10T00:00:00+00:00",
        "created_by": created_by,
        "status": TaskStatus.PENDING.value,
        "retry_count": "0",
        "max_retries": "3",
        "priority": "50",
        "vram_sensitive": "false",
        "model_slot": model_slot,
        "resource_key": resource_key,
        "dispatch_blocked": dispatch_blocked,
    }


def make_daemon():
    """Build a TaskSchedulerDaemon with mocked internals."""
    from ops.scheduler.task_scheduler import TaskSchedulerDaemon
    daemon = TaskSchedulerDaemon.__new__(TaskSchedulerDaemon)
    daemon.queue = MagicMock()
    daemon.redis = MagicMock()
    daemon.executor = MagicMock()
    daemon.monitor = MagicMock()
    daemon.retry_manager = MagicMock()
    daemon.vram_checker = None
    daemon._on_missed_start_report = None
    return daemon


# ─────────────────────────────────────────────────────────────────────────────
# Gate: dispatch_blocked flag (existing Phase 3 behaviour)
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchBlockedGate:
    @pytest.mark.asyncio
    async def test_dispatch_blocked_skips_lock(self):
        daemon = make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            return_value=make_metadata_dict(dispatch_blocked="true")
        )
        daemon.queue.acquire_lock = AsyncMock()

        await daemon._dispatch_task("t1")

        daemon.queue.acquire_lock.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_unblocked_proceeds_to_policy_check(self):
        daemon = make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            return_value=make_metadata_dict(dispatch_blocked="")
        )
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=[])
        daemon.queue.acquire_lock = AsyncMock(return_value=False)  # lock fails → stops here

        from ops.scheduler.resource_policy import ResourcePolicy
        daemon.resource_policy = ResourcePolicy()

        await daemon._dispatch_task("t1")

        # acquire_lock was attempted, meaning policy gate was cleared
        daemon.queue.acquire_lock.assert_called_once_with("t1")


# ─────────────────────────────────────────────────────────────────────────────
# Gate: ResourcePolicy denial defers the task
# ─────────────────────────────────────────────────────────────────────────────

class TestResourcePolicyGate:
    @pytest.mark.asyncio
    async def test_policy_deny_prevents_lock_acquisition(self):
        daemon = make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            return_value=make_metadata_dict()
        )
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=[])
        daemon.queue.acquire_lock = AsyncMock()

        # Inject a policy that always denies
        mock_policy = MagicMock()
        mock_policy.check_dispatch = MagicMock(
            return_value=PolicyDecision.deny(
                PolicyViolation.GLOBAL_CONCURRENCY,
                "test: always deny",
            )
        )
        daemon.resource_policy = mock_policy

        await daemon._dispatch_task("t1")

        daemon.queue.acquire_lock.assert_not_called()

    @pytest.mark.asyncio
    async def test_policy_permit_allows_lock_acquisition(self):
        daemon = make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            return_value=make_metadata_dict()
        )
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=[])
        daemon.queue.acquire_lock = AsyncMock(return_value=False)  # lock fails → stops

        mock_policy = MagicMock()
        mock_policy.check_dispatch = MagicMock(
            return_value=PolicyDecision.permit()
        )
        daemon.resource_policy = mock_policy

        await daemon._dispatch_task("t1")

        daemon.queue.acquire_lock.assert_called_once()

    @pytest.mark.asyncio
    async def test_policy_called_with_correct_running_list(self):
        """_get_running_metadatas() result is passed to check_dispatch."""
        daemon = make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            side_effect=[
                make_metadata_dict(),          # candidate (first call)
                make_metadata_dict(created_by="other"),  # running task (second call)
            ]
        )
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=["r1"])
        daemon.queue.acquire_lock = AsyncMock(return_value=False)

        captured_running = []

        def capture_policy(candidate, running):
            captured_running.extend(running)
            return PolicyDecision.permit()

        mock_policy = MagicMock()
        mock_policy.check_dispatch = MagicMock(side_effect=capture_policy)
        daemon.resource_policy = mock_policy

        await daemon._dispatch_task("t1")

        assert len(captured_running) == 1
        assert captured_running[0].created_by == "other"


# ─────────────────────────────────────────────────────────────────────────────
# Gate: metadata not found (existing safeguard)
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataNotFound:
    @pytest.mark.asyncio
    async def test_missing_metadata_skips_dispatch(self):
        daemon = make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(return_value=None)
        daemon.queue.acquire_lock = AsyncMock()

        await daemon._dispatch_task("t1")

        daemon.queue.acquire_lock.assert_not_called()
