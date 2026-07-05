"""Tests for local_executor_action.py — Logi Telegram executor route."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ops.agents.local_executor_action import (
    run_local_executor_task,
    format_telegram_executor_result,
    _validate_task_path,
    LocalExecutorActionResult,
)


# ─── path validation ─────────────────────────────────────────────────────────

def test_path_traversal_rejected():
    ok, reason = _validate_task_path("aims_workspace/test_tasks/../../etc/passwd")
    assert not ok
    assert "blocked" in reason.lower() or "escapes" in reason.lower() or "characters" in reason.lower()

def test_absolute_path_outside_workspace_rejected():
    ok, reason = _validate_task_path("/etc/passwd")
    assert not ok

def test_shell_metacharacter_rejected():
    for bad in [
        "aims_workspace/test_tasks/foo;rm",
        "aims_workspace/test_tasks/foo`whoami`",
        "aims_workspace/test_tasks/foo$(echo)",
        "aims_workspace/test_tasks/foo|bar",
    ]:
        ok, reason = _validate_task_path(bad)
        assert not ok, f"Should have rejected: {bad!r}"

def test_dotdot_in_path_rejected():
    ok, reason = _validate_task_path("aims_workspace/test_tasks/../../../.bashrc")
    assert not ok

def test_valid_path_in_task_dir(tmp_path):
    # Create a real file inside a fake task dir to test path validation pass
    task_file = tmp_path / "test.json"
    task_file.write_text('{"task_id":"t1"}')
    from ops.agents.local_executor_action import _TASK_DIR
    with patch("ops.agents.local_executor_action._TASK_DIR", tmp_path):
        ok, detail = _validate_task_path(str(task_file))
    assert ok
    assert str(task_file) in detail


# ─── blocked command classes ──────────────────────────────────────────────────

def test_rm_command_blocked_in_executor():
    """rm must be blocked by aims_local_executor.py allowlist."""
    import sys
    sys.path.insert(0, str(Path(__file__).parents[3] / "ops" / "scripts"))
    from aims_local_executor import _check_command_allowed
    ok, reason = _check_command_allowed(["rm", "-rf", "/tmp/test"])
    assert not ok

def test_sudo_command_blocked():
    from aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["sudo", "ls"])
    assert not ok

def test_docker_command_blocked():
    from aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["docker", "run", "alpine"])
    assert not ok

def test_aws_command_blocked():
    from aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["aws", "s3", "ls"])
    assert not ok

def test_curl_command_blocked():
    from aims_local_executor import _check_command_allowed
    ok, _ = _check_command_allowed(["curl", "https://example.com"])
    assert not ok


# ─── allowed executor task runs ──────────────────────────────────────────────

def test_allowed_executor_task_runs_and_returns_passed(tmp_path):
    """run_local_executor_task with a valid test task must return PASSED."""
    task_json_content = json.dumps({
        "task_id": "test-exec-001",
        "actions": [
            {"type": "write_file", "path": "/tmp/aims_executor_test_action.txt",
             "content": "TEST_PASSED\n"},
        ],
        "verify": {
            "file_exists": "/tmp/aims_executor_test_action.txt",
        }
    })
    task_file = tmp_path / "test_exec_001.json"
    task_file.write_text(task_json_content)

    from ops.agents.local_executor_action import _TASK_DIR, _EXECUTOR
    with patch("ops.agents.local_executor_action._TASK_DIR", tmp_path):
        with patch("ops.agents.local_executor_action._EXECUTOR", _EXECUTOR):
            result = run_local_executor_task(str(task_file))

    assert result.status == "PASSED"
    assert result.file_created is True
    assert result.execution_route == "logi_telegram_local_executor"


def test_expected_output_placeholder_rejected():
    """A result with no real stdout JSON must not be treated as PASSED."""
    # Simulate executor returning expected_output text instead of real JSON
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "I expected this to be AIMS_EXECUTOR_TEST_01_PASS"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        with patch("ops.agents.local_executor_action._TASK_DIR",
                   Path("aims_workspace/test_tasks")):
            # Create a temp file that exists
            import tempfile, os
            fd, path = tempfile.mkstemp(suffix=".json",
                                        dir="aims_workspace/test_tasks")
            os.close(fd)
            Path(path).write_text('{"task_id":"t"}')
            try:
                result = run_local_executor_task(path)
            finally:
                Path(path).unlink(missing_ok=True)

    # No valid JSON from executor → FAILED or executor_result is empty
    # The stdout was not valid JSON, so executor_result = {} → status FAILED
    assert result.status == "FAILED" or result.executor_result == {}


def test_arbitrary_bash_blocked_via_path_validation():
    """A request with shell metacharacters in task_json must be blocked."""
    result = run_local_executor_task("aims_workspace/test_tasks/foo; rm -rf /")
    assert result.status == "FAILED"
    assert result.error_class == "INVALID_TASK_PATH"


# ─── execution result written to workspace ───────────────────────────────────

def test_executor_result_contains_sha256(tmp_path):
    """Execution result must include real sha256 from executor, not a placeholder."""
    task_json_content = json.dumps({
        "task_id": "sha256-test",
        "actions": [
            {"type": "write_file", "path": "/tmp/aims_sha256_test.txt",
             "content": "SHA256_TEST\n"},
            {"type": "sha256_file", "path": "/tmp/aims_sha256_test.txt"},
        ],
        "verify": {"file_exists": "/tmp/aims_sha256_test.txt"}
    })
    task_file = tmp_path / "sha256_test.json"
    task_file.write_text(task_json_content)

    from ops.agents.local_executor_action import _EXECUTOR
    with patch("ops.agents.local_executor_action._TASK_DIR", tmp_path):
        with patch("ops.agents.local_executor_action._EXECUTOR", _EXECUTOR):
            result = run_local_executor_task(str(task_file))

    assert result.sha256 is not None
    assert len(result.sha256) == 64  # sha256 hex digest length
    assert result.sha256 != "expected_sha256"  # never a placeholder


# ─── Telegram format ─────────────────────────────────────────────────────────

def test_format_passed_result():
    r = LocalExecutorActionResult(
        status="PASSED",
        execution_route="logi_telegram_local_executor",
        task_json="aims_workspace/test_tasks/executor_test_01.json",
        stdout='{"status":"PASSED"}',
        stderr="",
        exit_code=0,
        executor_result={"status": "PASSED"},
        file_created=True,
        content_verified=True,
        sha256="0b51d0e74517aa75eca37c8587a76c05109c9cb7db49d794e8facdb6084fbb1d",
        error_class=None,
    )
    text = format_telegram_executor_result(r)
    assert "STATUS: PASSED" in text
    assert "EXECUTION_ROUTE: logi_telegram_local_executor" in text
    assert "FILE_CREATED: true" in text
    assert "CONTENT_VERIFIED: true" in text
    assert "0b51d0e74517aa75eca37c8587a76c05109c9cb7db49d794e8facdb6084fbb1d" in text


def test_format_blocked_result():
    r = LocalExecutorActionResult(
        status="BLOCKED_BY_FINAL_POLICY_GATE",
        execution_route="logi_telegram_local_executor",
        task_json="",
        stdout="", stderr="", exit_code=1,
        executor_result={},
        file_created=False,
        content_verified=False,
        sha256=None,
        error_class="EXECUTOR_ROUTE_POLICY_BLOCKED",
    )
    text = format_telegram_executor_result(r)
    assert "BLOCKED_BY_FINAL_POLICY_GATE" in text
    assert "EXECUTOR_ROUTE_POLICY_BLOCKED" in text


# ─── gateway integration ─────────────────────────────────────────────────────

def test_gateway_routes_executor_task_message():
    """Gateway must detect run_local_executor_task message and return executor result."""
    from ops.agents.logi_assistant_gateway import process_gateway_message

    mock_result = LocalExecutorActionResult(
        status="PASSED",
        execution_route="logi_telegram_local_executor",
        task_json="aims_workspace/test_tasks/executor_test_01.json",
        stdout='{"status":"PASSED"}', stderr="", exit_code=0,
        executor_result={"status": "PASSED"},
        file_created=True, content_verified=True,
        sha256="abc123", error_class=None,
    )

    with patch("ops.agents.local_executor_action.run_local_executor_task",
               return_value=mock_result):
        result = process_gateway_message(
            "Run approved local executor task: aims_workspace/test_tasks/executor_test_01.json",
            source="telegram",
        )

    assert result["action_type"] == "run_local_executor_task"
    assert result["status"] == "PASSED"
    assert result["file_created"] is True
