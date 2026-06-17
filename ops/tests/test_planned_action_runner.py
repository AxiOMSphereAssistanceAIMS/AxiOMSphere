#!/usr/bin/env python3
"""
PlannedActionRunner test suite.

Tests
─────
A. PlannedActionRunner(mode="dry-run")        → dry_run=True, mode="dry-run"
B. PlannedActionRunner(mode="live-lightweight") → dry_run=False, mode="live-lightweight"
C. PlannedActionRunner(mode="live-gpu-gated")  → dry_run=False, mode="live-gpu-gated"

D. _is_live_lightweight_safe: cpu_only + vram=0 → True
E. _is_live_lightweight_safe: vram>0           → False
F. _is_live_gpu_gated_safe:  gpu_queue_and_await=True, vram>0, slot32 → True
G. _is_live_gpu_gated_safe:  cpu_only_ok=True  → False (not gpu-gated-safe)

H. _execute dry_run → SIMULATED, subprocess never called
I. _execute handler="logi_tool" (unknown) → SKIP with reason
J. _execute handler="logi_subprocess" → delegates to _run_subprocess

K. _run_subprocess returncode=0  → status=PASS, exit_code=0
L. _run_subprocess returncode=1  → status=FAIL, exit_code=1
M. _run_subprocess TimeoutExpired → status=FAIL, error contains "timeout"
N. _run_subprocess live-gpu-gated → dgx_heavy_lock() context entered

O. _evaluate_criteria: SIMULATED result → (True, [])
P. _evaluate_criteria: exit_code=0      → (True, [])
Q. _evaluate_criteria: exit_code=1      → (False, non-empty)
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
OPS  = ROOT / "ops"
for p in (str(ROOT), str(OPS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from logi.planned_action_runner import (
    PlannedActionRunner,
    _is_live_lightweight_safe,
    _is_live_gpu_gated_safe,
)
from logi.short_term_action_plan import StrategicPlannedAction


# ── fixtures ──────────────────────────────────────────────────────────────────

def _cpu_action() -> StrategicPlannedAction:
    return StrategicPlannedAction(
        action_id="PA-TEST-CPU-01",
        title="CPU only action",
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
        execution_handler="logi_subprocess",
    )


def _gpu_action() -> StrategicPlannedAction:
    return StrategicPlannedAction(
        action_id="PA-TEST-GPU-01",
        title="GPU gated action",
        command_or_callable="python",
        command_args=["ops/scripts/nightly.py"],
        status="PENDING",
        resource_policy={
            "gpu_queue_and_await": True,
            "max_vram_gb": 10,
            "cpu_only_ok": False,
            "allowed_model_slots": ["slot32"],
            "max_wall_time_minutes": 5,
        },
        safety_policy={"abort_if_argus_critical": False},
        execution_handler="logi_subprocess",
    )


def _make_runner(mode: str) -> PlannedActionRunner:
    """Build runner without touching StrategicPlannedActionsRegistry filesystem."""
    runner = PlannedActionRunner.__new__(PlannedActionRunner)
    runner.mode = mode
    runner.dry_run = (mode == "dry-run")
    runner.registry = MagicMock()
    return runner


def _mock_proc(returncode: int) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = "stdout output"
    proc.stderr = ""
    return proc


@contextmanager
def _null_lock():
    yield


# ── Group 1 — Mode resolution (A–C) ──────────────────────────────────────────

class TestModeResolution:
    def test_A_dry_run_mode(self):
        runner = PlannedActionRunner.__new__(PlannedActionRunner)
        PlannedActionRunner.__init__(runner, mode="dry-run")
        assert runner.dry_run is True
        assert runner.mode == "dry-run"

    def test_B_live_lightweight_mode(self):
        runner = PlannedActionRunner.__new__(PlannedActionRunner)
        PlannedActionRunner.__init__(runner, mode="live-lightweight")
        assert runner.dry_run is False
        assert runner.mode == "live-lightweight"

    def test_C_live_gpu_gated_mode(self):
        runner = PlannedActionRunner.__new__(PlannedActionRunner)
        PlannedActionRunner.__init__(runner, mode="live-gpu-gated")
        assert runner.dry_run is False
        assert runner.mode == "live-gpu-gated"


# ── Group 2 — Safety predicates (D–G) ────────────────────────────────────────

class TestSafetyPredicates:
    def test_D_lightweight_safe_cpu_zero_vram(self):
        assert _is_live_lightweight_safe(_cpu_action()) is True

    def test_E_lightweight_unsafe_when_vram_nonzero(self):
        action = _cpu_action()
        action.resource_policy["max_vram_gb"] = 5
        assert _is_live_lightweight_safe(action) is False

    def test_F_gpu_gated_safe_with_correct_policy(self):
        assert _is_live_gpu_gated_safe(_gpu_action()) is True

    def test_G_gpu_gated_unsafe_when_cpu_only_ok_true(self):
        action = _gpu_action()
        action.resource_policy["cpu_only_ok"] = True
        assert _is_live_gpu_gated_safe(action) is False


# ── Group 3 — _execute routing (H–J) ─────────────────────────────────────────

class TestExecuteRouting:
    def _ledger(self) -> MagicMock:
        m = MagicMock()
        m.record = MagicMock()
        return m

    def test_H_dry_run_returns_simulated(self, tmp_path):
        runner = _make_runner("dry-run")
        action = _cpu_action()
        result = runner._execute(action, self._ledger(), tmp_path)
        assert result["status"] == "SIMULATED"
        assert result["exit_code"] == 0
        assert "dry_run" in result["stdout"]

    def test_I_unknown_handler_returns_skip(self, tmp_path):
        runner = _make_runner("live-lightweight")
        action = _cpu_action()
        action.execution_handler = "logi_tool"
        result = runner._execute(action, self._ledger(), tmp_path)
        assert result["status"] == "SKIP"
        assert "not implemented" in result["reason"]

    def test_J_subprocess_handler_calls_run_subprocess(self, tmp_path):
        runner = _make_runner("live-lightweight")
        action = _cpu_action()
        action.execution_handler = "logi_subprocess"
        with patch.object(runner, "_run_subprocess", return_value={"status": "PASS", "exit_code": 0}) as mock_sub:
            runner._execute(action, self._ledger(), tmp_path)
        mock_sub.assert_called_once_with(action, tmp_path)


# ── Group 4 — _run_subprocess outcomes (K–N) ─────────────────────────────────

_SUBPROCESS_PATCHES = [
    patch("logi.planned_action_runner.resolve_model_slot", return_value="axi_omi_sphere"),
    patch("logi.planned_action_runner.ollama_ps_entry_summary", return_value=""),
]


class TestRunSubprocess:
    def _run(self, runner, action, tmp_path, proc_mock):
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        with patch("subprocess.run", return_value=proc_mock):
            with patch("logi.planned_action_runner.resolve_model_slot", return_value="axi_omi_sphere"):
                with patch("logi.planned_action_runner.ollama_ps_entry_summary", return_value=""):
                    with patch("logi.planned_action_runner.dgx_heavy_lock", _null_lock):
                        return runner._run_subprocess(action, evidence_dir)

    def test_K_returncode_0_is_pass(self, tmp_path):
        runner = _make_runner("live-lightweight")
        result = self._run(runner, _cpu_action(), tmp_path, _mock_proc(0))
        assert result["status"] == "PASS"
        assert result["exit_code"] == 0

    def test_L_returncode_nonzero_is_fail(self, tmp_path):
        runner = _make_runner("live-lightweight")
        result = self._run(runner, _cpu_action(), tmp_path, _mock_proc(1))
        assert result["status"] == "FAIL"
        assert result["exit_code"] == 1

    def test_M_timeout_returns_fail_with_message(self, tmp_path):
        runner = _make_runner("live-lightweight")
        action = _cpu_action()
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=60)):
            with patch("logi.planned_action_runner.resolve_model_slot", return_value="axi_omi_sphere"):
                with patch("logi.planned_action_runner.ollama_ps_entry_summary", return_value=""):
                    with patch("logi.planned_action_runner.dgx_heavy_lock", _null_lock):
                        result = runner._run_subprocess(action, evidence_dir)
        assert result["status"] == "FAIL"
        assert result["exit_code"] == -1
        assert "timeout" in result["error"]

    def test_N_gpu_gated_mode_enters_dgx_heavy_lock(self, tmp_path):
        runner = _make_runner("live-gpu-gated")
        action = _gpu_action()
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        lock_entered = []

        @contextmanager
        def _tracking_lock():
            lock_entered.append(True)
            yield

        with patch("subprocess.run", return_value=_mock_proc(0)):
            with patch("logi.planned_action_runner.resolve_model_slot", return_value="axi_omi_sphere"):
                with patch("logi.planned_action_runner.ollama_ps_entry_summary", return_value=""):
                    with patch("logi.planned_action_runner.dgx_heavy_lock", _tracking_lock):
                        runner._run_subprocess(action, evidence_dir)

        assert lock_entered, "dgx_heavy_lock was never entered for live-gpu-gated action"


# ── Group 5 — _evaluate_criteria (O–Q) ───────────────────────────────────────

class TestEvaluateCriteria:
    def _runner(self):
        return _make_runner("dry-run")

    def test_O_simulated_result_always_passes(self):
        runner = self._runner()
        action = _cpu_action()
        action.acceptance_criteria = ["exit code must be 0"]
        passed, failures = runner._evaluate_criteria(action, {"status": "SIMULATED", "exit_code": 0})
        assert passed is True
        assert failures == []

    def test_P_zero_exit_code_passes(self):
        runner = self._runner()
        action = _cpu_action()
        action.acceptance_criteria = ["exit code must be 0"]
        passed, failures = runner._evaluate_criteria(action, {"status": "PASS", "exit_code": 0})
        assert passed is True
        assert failures == []

    def test_Q_nonzero_exit_code_fails(self):
        runner = self._runner()
        action = _cpu_action()
        action.acceptance_criteria = ["exit code must be 0"]
        passed, failures = runner._evaluate_criteria(action, {"status": "FAIL", "exit_code": 2})
        assert passed is False
        assert len(failures) > 0
        assert any("2" in f for f in failures)
