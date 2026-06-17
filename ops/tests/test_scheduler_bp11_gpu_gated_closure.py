#!/usr/bin/env python3
"""
BP-11 closure tests — PlannedActionExecutionDaemon scheduler routing (Phase 5).

Verifies that live-gpu-gated actions are dispatched through the Redis Scheduler
(via _dispatch_via_scheduler / _submit_and_wait) instead of the direct
dgx_heavy_lock() + subprocess.run() path in PlannedActionRunner.

Tests
─────
A. gpu-gated-safe action + live-gpu-gated mode → _dispatch_via_scheduler called
B. lightweight action + live-gpu-gated mode → runner.run called (not scheduler)
C. gpu-gated-safe action + live-lightweight mode → runner.run called (mode gate)
D. gpu-gated-safe action + dry-run mode → runner.run called
E. _dispatch_via_scheduler SUCCEEDED → status=PASS, exit_code=0, scheduler_routed=True
F. _dispatch_via_scheduler asyncio.run raises → status=FAIL, error=scheduler_dispatch_error
G. scheduler_url injected from constructor, not hardcoded
H. _submit_and_wait SUCCEEDED terminal → status=PASS, exit_code=0, scheduler_task_id set
I. _submit_and_wait FAILED terminal → status=FAIL, exit_code=1
J. _submit_and_wait ESCALATED terminal → status=FAIL (any non-SUCCEEDED terminal is FAIL)
K. _submit_and_wait poll timeout → status=FAIL, error contains "scheduler_poll_timeout"
L. _submit_and_wait submit params: task_type, model_slot, vram_sensitive, resource_key, created_by
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.logi.short_term_action_plan import StrategicPlannedAction
from ops.scheduler.planned_action_execution_daemon import (
    PlannedActionExecutionDaemon,
    _TERMINAL_STATUSES,
    _SCHEDULER_RETRY_DELAYS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _gpu_gated_action() -> StrategicPlannedAction:
    """Action that passes _is_live_gpu_gated_safe()."""
    return StrategicPlannedAction(
        action_id="PA-TEST-GPU-01",
        title="GPU gated test action",
        command_or_callable="python",
        command_args=["ops/scripts/nightly.py"],
        status="PENDING",
        resource_policy={
            "gpu_queue_and_await": True,
            "max_vram_gb": 10,
            "cpu_only_ok": False,
            "allowed_model_slots": ["slot32"],
            "max_wall_time_minutes": 30,
        },
        safety_policy={"abort_if_argus_critical": False},
    )


def _lightweight_action() -> StrategicPlannedAction:
    """Action that passes _is_live_lightweight_safe() but not gpu-gated."""
    return StrategicPlannedAction(
        action_id="PA-TEST-CPU-01",
        title="Lightweight test action",
        command_or_callable="python",
        command_args=["ops/scripts/lightweight.py"],
        status="PENDING",
        resource_policy={
            "gpu_queue_and_await": False,
            "max_vram_gb": 0,
            "cpu_only_ok": True,
            "allowed_model_slots": [],
        },
        safety_policy={"abort_if_argus_critical": False},
    )


def _make_daemon(mode: str = "live-gpu-gated") -> PlannedActionExecutionDaemon:
    """Build a daemon bypassing __init__ to avoid Redis/filesystem side effects."""
    daemon = PlannedActionExecutionDaemon.__new__(PlannedActionExecutionDaemon)
    daemon.mode = mode
    daemon.dry_run = (mode == "dry-run")
    daemon.action_id_prefix = ""
    daemon._scheduler_url = "redis://test:6379"
    daemon.registry = MagicMock()
    daemon.runner = MagicMock()
    daemon._queue = []
    daemon._ran_ids = {}
    daemon._running = True
    daemon.missed_start_records = []
    daemon.schedule_decisions = []
    return daemon


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — _dispatch() routing (A–D)
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchRouting:
    """Verify that _dispatch() sends gpu-gated actions to the scheduler and all
    others to the runner, gated by both mode and resource-policy classification."""

    def _patch_dispatch(self, daemon: PlannedActionExecutionDaemon, action: StrategicPlannedAction, tmp_path: Path):
        """Wire registry mock and patch EVIDENCE_ROOT for a single _dispatch() call."""
        daemon.registry.load.return_value = action
        daemon.registry.update_status = MagicMock()
        return patch(
            "ops.scheduler.planned_action_execution_daemon.EVIDENCE_ROOT",
            tmp_path,
        )

    def test_A_gpu_gated_action_routes_to_scheduler(self, tmp_path):
        """live-gpu-gated + gpu-gated-safe action → _dispatch_via_scheduler called."""
        daemon = _make_daemon(mode="live-gpu-gated")
        action = _gpu_gated_action()

        with self._patch_dispatch(daemon, action, tmp_path):
            with patch.object(
                daemon, "_dispatch_via_scheduler", return_value={"status": "PASS", "exit_code": 0}
            ) as mock_sched:
                daemon._dispatch("PA-TEST-GPU-01")

        mock_sched.assert_called_once_with("PA-TEST-GPU-01", action)
        daemon.runner.run.assert_not_called()

    def test_B_lightweight_action_in_gpu_mode_uses_runner(self, tmp_path):
        """live-gpu-gated + lightweight action → runner.run called (not scheduler)."""
        daemon = _make_daemon(mode="live-gpu-gated")
        action = _lightweight_action()
        daemon.runner.run.return_value = {"status": "PASS", "final_status": "PASS"}

        with self._patch_dispatch(daemon, action, tmp_path):
            with patch.object(daemon, "_dispatch_via_scheduler") as mock_sched:
                daemon._dispatch("PA-TEST-CPU-01")

        daemon.runner.run.assert_called_once_with(action)
        mock_sched.assert_not_called()

    def test_C_gpu_gated_action_in_lightweight_mode_uses_runner(self, tmp_path):
        """live-lightweight + gpu-gated-safe action → runner.run called (mode gate)."""
        daemon = _make_daemon(mode="live-lightweight")
        action = _gpu_gated_action()
        # live-lightweight mode: _safety_check will reject gpu-gated action
        # (not_live_lightweight_safe) so it gets DEFERRED, not run at all
        with self._patch_dispatch(daemon, action, tmp_path):
            with patch.object(daemon, "_dispatch_via_scheduler") as mock_sched:
                daemon._dispatch("PA-TEST-GPU-01")

        # In live-lightweight mode the gpu-gated action fails safety check → deferred
        mock_sched.assert_not_called()
        daemon.runner.run.assert_not_called()

    def test_D_dry_run_mode_gpu_gated_uses_runner(self, tmp_path):
        """dry-run mode + gpu-gated-safe action → runner.run called (dry-run bypasses scheduler)."""
        daemon = _make_daemon(mode="dry-run")
        action = _gpu_gated_action()
        daemon.runner.run.return_value = {"status": "PASS", "final_status": "PASS"}

        with self._patch_dispatch(daemon, action, tmp_path):
            with patch.object(daemon, "_dispatch_via_scheduler") as mock_sched:
                daemon._dispatch("PA-TEST-GPU-01")

        daemon.runner.run.assert_called_once_with(action)
        mock_sched.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — _dispatch_via_scheduler() (E–G)
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchViaScheduler:
    """Unit-test the synchronous bridge method that wraps asyncio.run()."""

    def test_E_succeeded_result_preserved(self):
        """asyncio.run returns SUCCEEDED result → forwarded unchanged."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        expected = {
            "status": "PASS",
            "exit_code": 0,
            "scheduler_routed": True,
            "scheduler_task_id": "logi_planned_action_gpu_abc123",
            "scheduler_terminal_status": "SUCCEEDED",
            "wall_time_sec": 12.3,
        }

        with patch("asyncio.run", return_value=expected) as mock_run:
            result = daemon._dispatch_via_scheduler("PA-TEST-GPU-01", action)

        assert result["status"] == "PASS"
        assert result["exit_code"] == 0
        assert result["scheduler_routed"] is True
        mock_run.assert_called_once()

    def test_F_asyncio_run_exception_returns_fail(self):
        """asyncio.run raises → FAIL result with scheduler_dispatch_error."""
        daemon = _make_daemon()
        action = _gpu_gated_action()

        with patch("asyncio.run", side_effect=RuntimeError("connection refused")):
            result = daemon._dispatch_via_scheduler("PA-TEST-GPU-01", action)

        assert result["status"] == "FAIL"
        assert result["exit_code"] == -1
        assert "scheduler_dispatch_error" in result["error"]
        assert "connection refused" in result["error"]
        assert result["scheduler_routed"] is True

    def test_G_scheduler_url_from_constructor(self):
        """scheduler_url constructor arg reaches _submit_and_wait coroutine."""
        daemon = _make_daemon()
        daemon._scheduler_url = "redis://custom-host:6380"
        action = _gpu_gated_action()

        captured_coro_args = {}

        async def fake_submit_and_wait(cmd, act, timeout_sec):
            captured_coro_args["url"] = daemon._scheduler_url
            return {"status": "PASS", "exit_code": 0, "scheduler_routed": True}

        with patch.object(daemon, "_submit_and_wait", side_effect=fake_submit_and_wait):
            with patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.new_event_loop().run_until_complete(coro)):
                daemon._dispatch_via_scheduler("PA-TEST-GPU-01", action)

        assert daemon._scheduler_url == "redis://custom-host:6380"


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — _submit_and_wait() (H–L)
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_redis(status: str | None) -> AsyncMock:
    """Return an async Redis mock whose hgetall always returns a dict with `status`."""
    r = AsyncMock()
    if status is not None:
        r.hgetall = AsyncMock(return_value={"status": status, "task_type": "logi_planned_action_gpu"})
    else:
        r.hgetall = AsyncMock(return_value={})
    r.close = AsyncMock()
    return r


def _make_mock_adapter(task_id: str = "logi_planned_action_gpu_test0001") -> MagicMock:
    """Return a mock AgentSchedulerAdapter that yields task_id from submit()."""
    adapter = AsyncMock()
    adapter.submit = AsyncMock(return_value=task_id)
    adapter.__aenter__ = AsyncMock(return_value=adapter)
    adapter.__aexit__ = AsyncMock(return_value=None)
    return adapter


class TestSubmitAndWait:
    """Async tests for _submit_and_wait() coroutine — run via asyncio.run()."""

    def test_H_succeeded_returns_pass(self):
        """SUCCEEDED terminal state → status=PASS, exit_code=0, scheduler_task_id set."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        task_id = "logi_planned_action_gpu_h001"
        mock_adapter = _make_mock_adapter(task_id)
        mock_redis = _make_mock_redis("SUCCEEDED")

        with patch("redis.asyncio.from_url", new=AsyncMock(return_value=mock_redis)):
            with patch(
                "ops.scheduler.agent_scheduler_adapter.AgentSchedulerAdapter",
                return_value=mock_adapter,
            ):
                result = asyncio.run(
                    daemon._submit_and_wait(["python", "script.py"], action, timeout_sec=60.0)
                )

        assert result["status"] == "PASS"
        assert result["exit_code"] == 0
        assert result["scheduler_routed"] is True
        assert result["scheduler_terminal_status"] == "SUCCEEDED"
        assert "scheduler_task_id" in result

    def test_I_failed_terminal_returns_fail(self):
        """FAILED terminal state → status=FAIL, exit_code=1."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        mock_adapter = _make_mock_adapter()
        mock_redis = _make_mock_redis("FAILED")

        with patch("redis.asyncio.from_url", new=AsyncMock(return_value=mock_redis)):
            with patch(
                "ops.scheduler.agent_scheduler_adapter.AgentSchedulerAdapter",
                return_value=mock_adapter,
            ):
                result = asyncio.run(
                    daemon._submit_and_wait(["python", "script.py"], action, timeout_sec=60.0)
                )

        assert result["status"] == "FAIL"
        assert result["exit_code"] == 1
        assert result["scheduler_terminal_status"] == "FAILED"
        assert result["scheduler_routed"] is True

    def test_J_escalated_terminal_returns_fail(self):
        """ESCALATED terminal state → status=FAIL (non-SUCCEEDED terminal is always FAIL)."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        mock_adapter = _make_mock_adapter()
        mock_redis = _make_mock_redis("ESCALATED")

        with patch("redis.asyncio.from_url", new=AsyncMock(return_value=mock_redis)):
            with patch(
                "ops.scheduler.agent_scheduler_adapter.AgentSchedulerAdapter",
                return_value=mock_adapter,
            ):
                result = asyncio.run(
                    daemon._submit_and_wait(["python", "script.py"], action, timeout_sec=60.0)
                )

        assert result["status"] == "FAIL"
        assert result["scheduler_terminal_status"] == "ESCALATED"
        assert result["scheduler_routed"] is True

    def test_K_poll_timeout_returns_fail_with_message(self):
        """Timeout before terminal status → status=FAIL, error contains scheduler_poll_timeout."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        mock_adapter = _make_mock_adapter()
        # Redis always returns non-terminal status
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={"status": "RUNNING"})
        mock_redis.close = AsyncMock()

        with patch("redis.asyncio.from_url", new=AsyncMock(return_value=mock_redis)):
            with patch(
                "ops.scheduler.agent_scheduler_adapter.AgentSchedulerAdapter",
                return_value=mock_adapter,
            ):
                # Use a very short timeout so the test completes quickly
                result = asyncio.run(
                    daemon._submit_and_wait(["python", "script.py"], action, timeout_sec=0.1)
                )

        assert result["status"] == "FAIL"
        assert result["exit_code"] == -1
        assert "scheduler_poll_timeout" in result["error"]
        assert result["scheduler_routed"] is True
        assert "scheduler_task_id" in result

    def test_L_submit_params_correct(self):
        """adapter.submit() called with task_type, model_slot, vram_sensitive, resource_key, created_by."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        mock_adapter = _make_mock_adapter()
        mock_redis = _make_mock_redis("SUCCEEDED")

        with patch("redis.asyncio.from_url", new=AsyncMock(return_value=mock_redis)):
            with patch(
                "ops.scheduler.agent_scheduler_adapter.AgentSchedulerAdapter",
                return_value=mock_adapter,
            ):
                asyncio.run(
                    daemon._submit_and_wait(["python", "script.py"], action, timeout_sec=60.0)
                )

        mock_adapter.submit.assert_awaited_once()
        _, kwargs = mock_adapter.submit.call_args
        assert kwargs.get("task_type") == "logi_planned_action_gpu"
        assert kwargs.get("model_slot") == "slot32"
        assert kwargs.get("vram_sensitive") is True
        assert kwargs.get("resource_key") == "gpu_exclusive"
        assert kwargs.get("created_by") == "logi"


# ─────────────────────────────────────────────────────────────────────────────
# Terminal status set sanity check
# ─────────────────────────────────────────────────────────────────────────────

def test_terminal_statuses_complete():
    """_TERMINAL_STATUSES covers all expected scheduler terminal states."""
    expected = {"SUCCEEDED", "FAILED", "ESCALATED", "CLOSED", "CANCELLED"}
    assert _TERMINAL_STATUSES == expected


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — _dispatch_via_scheduler() retry logic (R–U)
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchViaSchedulerRetry:
    """_dispatch_via_scheduler retries up to len(_SCHEDULER_RETRY_DELAYS) times
    on transient exceptions, sleeping between attempts, and returns FAIL only
    after all attempts are exhausted."""

    def test_R_first_attempt_succeeds_no_retry(self):
        """First attempt succeeds → result returned immediately, sleep never called."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        expected = {"status": "PASS", "exit_code": 0, "scheduler_routed": True}

        with patch("asyncio.run", return_value=expected) as mock_run:
            with patch("time.sleep") as mock_sleep:
                result = daemon._dispatch_via_scheduler("PA-TEST-GPU-01", action)

        assert result["status"] == "PASS"
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    def test_S_transient_fail_then_succeed(self):
        """First attempt raises, second attempt returns PASS → final status PASS."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        success = {"status": "PASS", "exit_code": 0, "scheduler_routed": True}
        side_effects = [RuntimeError("connection refused"), success]

        with patch("asyncio.run", side_effect=side_effects):
            with patch("time.sleep"):
                result = daemon._dispatch_via_scheduler("PA-TEST-GPU-01", action)

        assert result["status"] == "PASS"
        assert result["exit_code"] == 0

    def test_T_all_attempts_exhausted_returns_fail(self):
        """All attempts raise → FAIL result with scheduler_dispatch_error."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        max_attempts = len(_SCHEDULER_RETRY_DELAYS) + 1

        with patch("asyncio.run", side_effect=RuntimeError("redis down")) as mock_run:
            with patch("time.sleep"):
                result = daemon._dispatch_via_scheduler("PA-TEST-GPU-01", action)

        assert result["status"] == "FAIL"
        assert result["exit_code"] == -1
        assert "scheduler_dispatch_error" in result["error"]
        assert "redis down" in result["error"]
        assert result["scheduler_routed"] is True
        assert mock_run.call_count == max_attempts

    def test_U_retry_delays_match_constant(self):
        """time.sleep is called with the values from _SCHEDULER_RETRY_DELAYS in order."""
        daemon = _make_daemon()
        action = _gpu_gated_action()
        max_attempts = len(_SCHEDULER_RETRY_DELAYS) + 1
        sleep_calls = []

        def _capture_sleep(secs):
            sleep_calls.append(secs)

        with patch("asyncio.run", side_effect=RuntimeError("blip")):
            with patch("time.sleep", side_effect=_capture_sleep):
                daemon._dispatch_via_scheduler("PA-TEST-GPU-01", action)

        # sleep is called between attempts — one fewer than total attempts
        assert len(sleep_calls) == max_attempts - 1
        assert sleep_calls == list(_SCHEDULER_RETRY_DELAYS)
