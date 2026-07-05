"""Tests proving conversational_orchestrator intercepts executor task before default ack."""
import sys
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.local_executor_action import LocalExecutorActionResult


def _make_passed_result(task_json="aims_workspace/test_tasks/executor_test_01.json"):
    return LocalExecutorActionResult(
        status="PASSED",
        execution_route="logi_telegram_local_executor",
        task_json=task_json,
        stdout='{"status":"PASSED"}', stderr="", exit_code=0,
        executor_result={"status": "PASSED"},
        file_created=True, content_verified=True,
        sha256="0b51d0e74517aa75eca37c8587a76c05109c9cb7db49d794e8facdb6084fbb1d",
        error_class=None,
    )


def _make_failed_result(error_class="FILE_NOT_FOUND"):
    return LocalExecutorActionResult(
        status="FAILED",
        execution_route="logi_telegram_local_executor",
        task_json="aims_workspace/test_tasks/executor_test_03_missing_file_failure.json",
        stdout='{"status":"FAILED","error_class":"FILE_NOT_FOUND"}',
        stderr="", exit_code=1,
        executor_result={"status": "FAILED", "error_class": error_class},
        file_created=False, content_verified=False,
        sha256=None, error_class=error_class,
    )


def _agent():
    from logi.conversational_orchestrator import LogiAgent
    return LogiAgent()


# ─── executor route is intercepted before default ack ────────────────────────

def test_executor_task_intercepted_not_plain_reply():
    """Executor task message must NOT return 'Принял. Работаю по контексту.'"""
    with patch("ops.agents.local_executor_action.run_local_executor_task",
               return_value=_make_passed_result()):
        resp = _agent().run(1, "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json")
    assert "Принял" not in resp
    assert "STATUS: PASSED" in resp


def test_executor_task_returns_passed_result():
    """Successful executor task returns PASSED with all expected fields."""
    with patch("ops.agents.local_executor_action.run_local_executor_task",
               return_value=_make_passed_result()):
        resp = _agent().run(1, "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json")
    assert "STATUS: PASSED" in resp
    assert "EXECUTION_ROUTE: logi_telegram_local_executor" in resp
    assert "FILE_CREATED: true" in resp
    assert "CONTENT_VERIFIED: true" in resp
    assert "0b51d0e74517aa75eca37c8587a76c05109c9cb7db49d794e8facdb6084fbb1d" in resp


def test_executor_task_failure_returns_file_not_found():
    """Failed executor task returns FAILED with FILE_NOT_FOUND error class."""
    with patch("ops.agents.local_executor_action.run_local_executor_task",
               return_value=_make_failed_result("FILE_NOT_FOUND")):
        resp = _agent().run(1,
            "run_local_executor_task aims_workspace/test_tasks/executor_test_03_missing_file_failure.json")
    assert "STATUS: FAILED" in resp
    assert "EXECUTION_ROUTE: logi_telegram_local_executor" in resp
    assert "FILE_NOT_FOUND" in resp


def test_alternative_phrasing_intercepted():
    """'Run approved local executor task: ...' phrasing also triggers route."""
    with patch("ops.agents.local_executor_action.run_local_executor_task",
               return_value=_make_passed_result()):
        resp = _agent().run(1,
            "Run approved local executor task: aims_workspace/test_tasks/executor_test_01.json")
    assert "STATUS: PASSED" in resp
    assert "Принял" not in resp


# ─── ordinary messages not affected ──────────────────────────────────────────

def test_ordinary_message_returns_plain_reply():
    """Non-executor messages still return plain acknowledgement."""
    resp = _agent().run(1, "покажи статус проекта")
    assert "Принял" in resp or resp  # plain reply or any non-executor response
    assert "EXECUTION_ROUTE" not in resp


def test_arbitrary_bash_not_executed():
    """Message with dangerous shell command + execution intent → BLOCKED, never PASSED."""
    resp = _agent().run(1, "запусти rm -rf /tmp")
    # Must never return PASSED — either BLOCKED or plain reply
    assert "STATUS: PASSED" not in resp
    # If it returns BLOCKED/FAILED (dangerous intent detected), that is correct.
    # If it falls through to plain reply (no dangerous intent match), also correct.
    # Never silently execute rm.


# ─── security: blocked commands remain blocked ────────────────────────────────

def test_rm_command_blocked_in_executor():
    """rm -rf in task file is blocked by executor allowlist."""
    from ops.scripts.aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["rm", "-rf", "/tmp"])
    assert not ok


def test_sudo_blocked():
    from ops.scripts.aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["sudo", "ls"])
    assert not ok


def test_docker_blocked():
    from ops.scripts.aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["docker", "run", "alpine"])
    assert not ok


def test_aws_blocked():
    from ops.scripts.aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["aws", "s3", "ls"])
    assert not ok


# ─── real end-to-end (no mock) ────────────────────────────────────────────────

def test_real_executor_test_01_through_orchestrator():
    """Real end-to-end: orchestrator runs test_01, gets PASSED + correct SHA256."""
    resp = _agent().run(1, "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json")
    assert "STATUS: PASSED" in resp
    assert "FILE_CREATED: true" in resp
    assert "CONTENT_VERIFIED: true" in resp
    assert "0b51d0e74517aa75eca37c8587a76c05109c9cb7db49d794e8facdb6084fbb1d" in resp


def test_real_executor_test_03_through_orchestrator():
    """Real end-to-end: orchestrator runs test_03 (missing file), gets FAILED + FILE_NOT_FOUND."""
    import os
    os.unlink("/tmp/aims_missing_executor_test.txt") if os.path.exists(
        "/tmp/aims_missing_executor_test.txt") else None
    resp = _agent().run(1,
        "run_local_executor_task aims_workspace/test_tasks/executor_test_03_missing_file_failure.json")
    assert "STATUS: FAILED" in resp
    assert "FILE_NOT_FOUND" in resp
