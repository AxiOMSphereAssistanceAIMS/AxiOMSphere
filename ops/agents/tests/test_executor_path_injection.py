"""Regression tests for path/command injection in the local executor route."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.local_executor_action import validate_executor_message


# ─── validate_executor_message ───────────────────────────────────────────────

def test_clean_path_accepted():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json"
    )
    assert ok is True


def test_natural_language_accepted():
    ok, _ = validate_executor_message(
        "Logi, run approved local executor task aims_workspace/test_tasks/executor_test_01.json"
    )
    assert ok is True


def test_semicolon_injection_rejected():
    ok, reason = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json; rm -rf /"
    )
    assert ok is False
    assert ";" in reason or "metacharacter" in reason.lower()


def test_pipe_injection_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json | cat /etc/passwd"
    )
    assert ok is False


def test_backtick_injection_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json`whoami`"
    )
    assert ok is False


def test_dollar_injection_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json $(rm -rf /)"
    )
    assert ok is False


def test_ampersand_injection_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json & malicious"
    )
    assert ok is False


def test_rm_word_rejected():
    ok, reason = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json rm -rf /"
    )
    assert ok is False
    assert "rm" in reason.lower() or "blocked" in reason.lower()


def test_sudo_word_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json sudo ls"
    )
    assert ok is False


def test_docker_word_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json docker run alpine"
    )
    assert ok is False


def test_curl_word_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json curl https://evil.com"
    )
    assert ok is False


def test_aws_word_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json aws s3 ls"
    )
    assert ok is False


def test_newline_injection_rejected():
    ok, _ = validate_executor_message(
        "run_local_executor_task aims_workspace/test_tasks/foo.json\nrm -rf /"
    )
    assert ok is False


# ─── orchestrator regression ─────────────────────────────────────────────────

def _orchestrator_run(text: str) -> str:
    from logi.conversational_orchestrator import LogiAgent
    return LogiAgent().run(1, text)


def test_orchestrator_semicolon_injection_returns_failed():
    resp = _orchestrator_run(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json; rm -rf /"
    )
    assert "STATUS: FAILED" in resp
    assert "COMMAND_BLOCKED" in resp


def test_orchestrator_pipe_injection_returns_failed():
    resp = _orchestrator_run(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json | ls"
    )
    assert "STATUS: FAILED" in resp


def test_orchestrator_path_traversal_returns_failed():
    resp = _orchestrator_run(
        "run_local_executor_task aims_workspace/test_tasks/../executor_test_01.json"
    )
    assert "STATUS: FAILED" in resp
    assert "INVALID_TASK_PATH" in resp


def test_orchestrator_absolute_path_returns_failed():
    resp = _orchestrator_run("run_local_executor_task /tmp/executor_test_01.json")
    assert "STATUS: FAILED" in resp
    assert "INVALID_TASK_PATH" in resp


def test_orchestrator_clean_path_still_passes():
    resp = _orchestrator_run(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json"
    )
    assert "STATUS: PASSED" in resp
    assert "EXECUTION_ROUTE: logi_telegram_local_executor" in resp


# ─── gateway regression ──────────────────────────────────────────────────────

def _gateway_run(text: str) -> dict:
    from ops.agents.logi_assistant_gateway import process_gateway_message
    return process_gateway_message(text, source="telegram")


def test_gateway_semicolon_injection_returns_failed():
    result = _gateway_run(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json; rm -rf /"
    )
    assert result["status"] == "FAILED"
    assert result["error_class"] == "COMMAND_BLOCKED"


def test_gateway_path_traversal_returns_failed():
    result = _gateway_run(
        "run_local_executor_task aims_workspace/test_tasks/../executor_test_01.json"
    )
    assert result["status"] == "FAILED"
    assert result["error_class"] in ("INVALID_TASK_PATH", "COMMAND_BLOCKED")


def test_gateway_clean_path_passes():
    result = _gateway_run(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json"
    )
    assert result["status"] == "PASSED"
    assert result["execution_route"] == "logi_telegram_local_executor"
