#!/usr/bin/env python3
"""
Controlled validation scenarios for Redis Scheduler backpressure (Phase 2).

Scenario A — Avalanche prevention:
    Submit global_limit+1 tasks concurrently; policy must block the overflow.

Scenario B — slot32/slot120 mutex:
    slot32 running → slot120 candidate denied SLOT_MUTEX; slot14 still allowed.

Scenario C — Missed-start regression:
    dispatch_blocked flag still honoured even after policy gate added.

Scenario D — Dashboard reflects slot state:
    get_scheduler_backpressure_detail() slot_states mirror running task slots.
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scheduler.task_models import TaskMetadata, TaskStatus
from ops.scheduler.resource_policy import (
    ResourcePolicy, ResourcePolicyConfig, PolicyViolation,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _task(task_id, task_type="argus_smoke", model_slot=None, resource_key=None,
          created_by="argus", status=None):
    return TaskMetadata(
        task_id=task_id,
        task_type=task_type,
        command=["echo", "test"],
        scheduled_for="2026-06-10T00:00:00+00:00",
        created_at="2026-06-10T00:00:00+00:00",
        created_by=created_by,
        status=status or TaskStatus.RUNNING.value,
        model_slot=model_slot,
        resource_key=resource_key,
    )


def _meta_dict(task_type="argus_smoke", dispatch_blocked="", model_slot="", resource_key=""):
    return {
        "task_id": "t1",
        "task_type": task_type,
        "command": json.dumps(["echo", "test"]),
        "scheduled_for": "2026-06-10T00:00:00+00:00",
        "created_at": "2026-06-10T00:00:00+00:00",
        "created_by": "argus",
        "status": TaskStatus.PENDING.value,
        "retry_count": "0",
        "max_retries": "3",
        "priority": "50",
        "vram_sensitive": "false",
        "model_slot": model_slot,
        "resource_key": resource_key,
        "dispatch_blocked": dispatch_blocked,
    }


def _make_daemon():
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
# Scenario A — Avalanche prevention
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioA_AvalanchePrevention:
    """global_limit=3 means a 4th concurrent task must be denied."""

    def setup_method(self):
        self.policy = ResourcePolicy(ResourcePolicyConfig(global_max_concurrent=3))

    def test_first_three_tasks_permitted(self):
        # Use distinct created_by values to avoid per_agent_max_concurrent=2 limit
        running = [
            _task("r0", created_by="argus"),
            _task("r1", created_by="logi"),
        ]
        candidate = _task("c1", created_by="traini")  # 3rd task, 3rd agent
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_fourth_task_denied_global_concurrency(self):
        running = [_task(f"r{i}") for i in range(3)]  # 3 already running
        candidate = _task("c1")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.GLOBAL_CONCURRENCY

    def test_denied_task_includes_count_in_reason(self):
        running = [_task(f"r{i}") for i in range(3)]
        result = self.policy.check_dispatch(_task("c1"), running)
        assert "3" in result.reason

    def test_fourth_task_has_correct_limit(self):
        running = [_task(f"r{i}") for i in range(3)]
        result = self.policy.check_dispatch(_task("c1"), running)
        assert result.limit == 3
        assert result.running_count == 3

    @pytest.mark.asyncio
    async def test_avalanche_daemon_skips_lock_on_policy_deny(self):
        """_dispatch_task() must not acquire lock when policy denies."""
        daemon = _make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(return_value=_meta_dict())
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=["r1", "r2", "r3"])

        # Build 3 running tasks to trigger global limit
        running_meta = _meta_dict()

        async def _multi_hgetall(task_id):
            return running_meta

        daemon.queue.get_task_metadata = AsyncMock(side_effect=[
            _meta_dict(),      # candidate
            _meta_dict(),      # r1
            _meta_dict(),      # r2
            _meta_dict(),      # r3
        ])
        daemon.queue.acquire_lock = AsyncMock()
        daemon.resource_policy = ResourcePolicy(ResourcePolicyConfig(global_max_concurrent=3))

        await daemon._dispatch_task("c1")

        daemon.queue.acquire_lock.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Scenario B — slot32 ↔ slot120 mutex
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioB_SlotMutex:
    """slot32 and slot120 are mutually exclusive on the 128GB DGX Spark."""

    def setup_method(self):
        self.policy = ResourcePolicy()  # default config has mutex

    def test_slot120_blocked_when_slot32_running(self):
        running = [_task("r1", model_slot="slot32")]
        candidate = _task("c1", model_slot="slot120")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.SLOT_MUTEX

    def test_slot32_blocked_when_slot120_running(self):
        running = [_task("r1", model_slot="slot120")]
        candidate = _task("c1", model_slot="slot32")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.SLOT_MUTEX

    def test_slot14_not_blocked_by_slot32(self):
        running = [_task("r1", model_slot="slot32")]
        candidate = _task("c1", model_slot="slot14")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_slot14_not_blocked_by_slot120(self):
        running = [_task("r1", model_slot="slot120")]
        candidate = _task("c1", model_slot="slot14")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_mutex_reason_names_both_slots(self):
        running = [_task("r1", model_slot="slot32")]
        candidate = _task("c1", model_slot="slot120")
        result = self.policy.check_dispatch(candidate, running)
        assert "slot120" in result.reason
        assert "slot32" in result.reason

    def test_no_running_allows_either_slot(self):
        for slot in ("slot32", "slot120"):
            result = self.policy.check_dispatch(_task("c1", model_slot=slot), [])
            assert result.allowed, f"{slot} should be allowed with empty running list"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario C — Missed-start regression
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioC_MissedStartRegression:
    """dispatch_blocked (Phase 3 gate) must still block before policy gate."""

    @pytest.mark.asyncio
    async def test_dispatch_blocked_prevents_policy_check(self):
        """If dispatch_blocked=true, policy.check_dispatch() is never called."""
        daemon = _make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(
            return_value=_meta_dict(dispatch_blocked="true")
        )
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=[])
        daemon.queue.acquire_lock = AsyncMock()

        mock_policy = MagicMock()
        daemon.resource_policy = mock_policy

        await daemon._dispatch_task("t1")

        # Both lock and policy check skipped
        daemon.queue.acquire_lock.assert_not_called()
        mock_policy.check_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_unblocked_task_reaches_policy_check(self):
        """dispatch_blocked='' → policy gate reached (lock attempted if policy permits)."""
        daemon = _make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(return_value=_meta_dict())
        daemon.queue.scan_running_queue_all = AsyncMock(return_value=[])
        daemon.queue.acquire_lock = AsyncMock(return_value=False)  # lock fails → stops

        mock_policy = MagicMock()
        mock_policy.check_dispatch = MagicMock(
            return_value=__import__(
                "ops.scheduler.resource_policy",
                fromlist=["PolicyDecision"]
            ).PolicyDecision.permit()
        )
        daemon.resource_policy = mock_policy

        await daemon._dispatch_task("t1")

        mock_policy.check_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_metadata_none_skips_all_gates(self):
        """No metadata → skip before even reaching dispatch_blocked check."""
        daemon = _make_daemon()
        daemon.queue.get_task_metadata = AsyncMock(return_value=None)
        daemon.queue.acquire_lock = AsyncMock()
        mock_policy = MagicMock()
        daemon.resource_policy = mock_policy

        await daemon._dispatch_task("t1")

        daemon.queue.acquire_lock.assert_not_called()
        mock_policy.check_dispatch.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Scenario D — Dashboard slot state reflection
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioD_DashboardSlotReflection:
    """get_scheduler_backpressure_detail() slot_states mirror running task slots."""

    def _fresh_hb(self):
        return str(int(time.time()) - 10)

    def _base_client(self, running: int = 0):
        c = AsyncMock()
        c.get = AsyncMock(return_value=self._fresh_hb())
        c.zcard = AsyncMock(side_effect=[0, running, 0, 0, 0])
        c.aclose = AsyncMock()
        return c

    def _detail_client(self):
        c = AsyncMock()
        c.zcard = AsyncMock(return_value=0)
        c.zrange = AsyncMock(return_value=[])
        c.hgetall = AsyncMock(return_value={})
        c.aclose = AsyncMock()
        return c

    def _bp_client(self, tasks):
        c = AsyncMock()
        c.zrange = AsyncMock(return_value=[t["task_id"] for t in tasks])
        hgetall_results = [
            {"task_type": t.get("task_type", "unknown"),
             "model_slot": t.get("model_slot", ""),
             "resource_key": t.get("resource_key", "")}
            for t in tasks
        ]
        c.hgetall = AsyncMock(side_effect=hgetall_results) if tasks else AsyncMock(return_value={})
        c.aclose = AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_slot14_busy_in_dashboard_when_running(self):
        sys.modules.setdefault("argus_code_agent", MagicMock())
        from ops.argus.argus_orchestrator import get_scheduler_backpressure_detail

        seq = [
            self._base_client(running=1),
            self._detail_client(),
            self._bp_client([{"task_id": "t1", "task_type": "slot14_nightly_eval", "model_slot": "slot14"}]),
        ]

        async def _from_url(url, **kw):
            return seq.pop(0)

        mock_redis = MagicMock()
        mock_redis.from_url = AsyncMock(side_effect=_from_url)

        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", True), \
             patch("ops.argus.argus_orchestrator._aioredis", mock_redis):
            result = await get_scheduler_backpressure_detail()

        assert result["slot_states"]["slot14"] == "busy"
        assert result["slot_states"]["slot32"] == "free"
        assert result["slot_states"]["slot120"] == "free"
        assert result["mutex_locked"] is False

    @pytest.mark.asyncio
    async def test_both_detail_and_backpressure_keys_present(self):
        """Combined output has both DETAIL and BACKPRESSURE key families."""
        sys.modules.setdefault("argus_code_agent", MagicMock())
        from ops.argus.argus_orchestrator import get_scheduler_backpressure_detail

        with patch("ops.argus.argus_orchestrator._SCHEDULER_AVAILABLE", False):
            result = await get_scheduler_backpressure_detail()

        detail_keys = {"completed_total", "last_completed", "last_failed"}
        bp_keys = {"slot_states", "mutex_locked", "running_slots",
                   "active_resource_keys", "global_limit", "queue_pressure"}
        assert detail_keys.issubset(result.keys())
        assert bp_keys.issubset(result.keys())
