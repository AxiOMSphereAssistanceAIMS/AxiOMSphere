"""Regression tests for Russian/mixed executor intents in Logi Telegram route."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.local_executor_action import (
    EXECUTOR_TASK_RE,
    validate_executor_message,
    is_dangerous_execution_intent,
    LocalExecutorActionResult,
)


# ─── EXECUTOR_TASK_RE: Russian/mixed matching ─────────────────────────────────

def test_regex_matches_russian_zapusti_utv():
    """запусти утвержденную задачу → regex must match."""
    m = EXECUTOR_TASK_RE.search(
        "Логи, запусти утвержденную задачу aims_workspace/test_tasks/executor_test_01.json"
    )
    assert m is not None
    assert m.group(1) == "aims_workspace/test_tasks/executor_test_01.json"


def test_regex_matches_russian_prover_executor():
    """проверь через локальный executor → regex must match."""
    m = EXECUTOR_TASK_RE.search(
        "Логи, проверь через локальный executor aims_workspace/test_tasks/executor_test_01.json"
    )
    assert m is not None
    assert "test_tasks" in m.group(1)


def test_regex_matches_prover_zadachu():
    """Проверь через локальный executor задачу → regex must match."""
    m = EXECUTOR_TASK_RE.search(
        "Проверь через локальный executor задачу aims_workspace/test_tasks/executor_test_01.json"
    )
    assert m is not None


def test_regex_matches_zapusti_approved_task():
    """запусти approved task → regex must match."""
    m = EXECUTOR_TASK_RE.search(
        "Логи, запусти approved task aims_workspace/test_tasks/executor_test_01.json"
    )
    assert m is not None


def test_regex_matches_vypolni_approved_task():
    """выполни approved task → regex must match."""
    m = EXECUTOR_TASK_RE.search(
        "Логи, выполни approved task aims_workspace/test_tasks/executor_test_01.json"
    )
    assert m is not None


def test_regex_matches_zapusti_approved_local_executor_task():
    """Запусти approved local executor task → regex must match."""
    m = EXECUTOR_TASK_RE.search(
        "Запусти approved local executor task aims_workspace/test_tasks/executor_test_01.json"
    )
    assert m is not None


def test_regex_does_not_match_no_json_path():
    """Without a .json path, executor regex must not fire."""
    assert EXECUTOR_TASK_RE.search("Логи, запусти команду docker restart bot") is None
    assert EXECUTOR_TASK_RE.search("Логи, выполни rm -rf /tmp") is None


# ─── is_dangerous_execution_intent ───────────────────────────────────────────

def test_dangerous_intent_rm():
    assert is_dangerous_execution_intent("Логи, выполни rm -rf /tmp/aims_executor_test_01.txt") is True


def test_dangerous_intent_docker():
    assert is_dangerous_execution_intent("Логи, запусти команду docker restart axiomsphere-logi-bot") is True


def test_dangerous_intent_not_triggered_for_approved_task():
    """Approved .json task message must NOT trigger dangerous intent block."""
    assert is_dangerous_execution_intent(
        "Логи, запусти утвержденную задачу aims_workspace/test_tasks/executor_test_01.json"
    ) is False


def test_dangerous_intent_not_triggered_for_plain_message():
    """Plain non-execution message must not be flagged."""
    assert is_dangerous_execution_intent("покажи статус проекта") is False


# ─── orchestrator: Russian accepted ──────────────────────────────────────────

def _orch(text: str) -> str:
    from logi.conversational_orchestrator import LogiAgent
    return LogiAgent().run(1, text)


def test_russian_approved_task_passes():
    """Russian запусти утвержденную задачу → PASSED through orchestrator."""
    resp = _orch(
        "Логи, запусти утвержденную задачу aims_workspace/test_tasks/executor_test_01.json"
    )
    assert "STATUS: PASSED" in resp
    assert "EXECUTION_ROUTE: logi_telegram_local_executor" in resp
    assert "FILE_CREATED: true" in resp


def test_russian_prover_executor_passes():
    """Russian проверь через локальный executor → PASSED."""
    resp = _orch(
        "Логи, проверь через локальный executor aims_workspace/test_tasks/executor_test_01.json"
    )
    assert "STATUS: PASSED" in resp


def test_russian_failure_task_returns_failed():
    """Russian approved task with missing file → FAILED + FILE_NOT_FOUND."""
    resp = _orch(
        "Проверь через локальный executor задачу "
        "aims_workspace/test_tasks/executor_test_03_missing_file_failure.json"
    )
    assert "STATUS: FAILED" in resp
    assert "FILE_NOT_FOUND" in resp


def test_russian_dangerous_rm_blocked():
    """Russian выполни rm -rf → BLOCKED."""
    resp = _orch("Логи, выполни rm -rf /tmp/aims_executor_test_01.txt")
    assert "BLOCKED" in resp or "FAILED" in resp
    assert "COMMAND_BLOCKED" in resp


def test_russian_dangerous_docker_blocked():
    """Russian запусти docker → BLOCKED."""
    resp = _orch("Логи, запусти команду docker restart axiomsphere-logi-bot")
    assert "BLOCKED" in resp or "FAILED" in resp
    assert "COMMAND_BLOCKED" in resp


def test_russian_injection_after_path_blocked():
    """Russian path + injection ; rm -rf → COMMAND_BLOCKED."""
    resp = _orch(
        "Логи, запусти утвержденную задачу "
        "aims_workspace/test_tasks/executor_test_01.json; rm -rf /"
    )
    assert "STATUS: FAILED" in resp
    assert "COMMAND_BLOCKED" in resp


def test_russian_absolute_path_rejected():
    """Russian path /tmp/... → INVALID_TASK_PATH."""
    resp = _orch("Логи, запусти утвержденную задачу /tmp/executor_test_01.json")
    assert "STATUS: FAILED" in resp
    assert "INVALID_TASK_PATH" in resp


def test_russian_path_traversal_rejected():
    """Russian path .. → INVALID_TASK_PATH."""
    resp = _orch(
        "Логи, запусти утвержденную задачу "
        "aims_workspace/test_tasks/../executor_test_01.json"
    )
    assert "STATUS: FAILED" in resp
    assert "INVALID_TASK_PATH" in resp


def test_ordinary_message_not_affected():
    """Ordinary non-executor message still returns plain reply, not executor route."""
    resp = _orch("покажи статус проекта")
    assert "EXECUTION_ROUTE" not in resp
    assert "STATUS: PASSED" not in resp


# ─── English syntax still works ──────────────────────────────────────────────

def test_english_strict_still_passes():
    resp = _orch("run_local_executor_task aims_workspace/test_tasks/executor_test_01.json")
    assert "STATUS: PASSED" in resp


def test_english_natural_still_passes():
    resp = _orch(
        "Logi, run approved local executor task "
        "aims_workspace/test_tasks/executor_test_01.json"
    )
    assert "STATUS: PASSED" in resp
