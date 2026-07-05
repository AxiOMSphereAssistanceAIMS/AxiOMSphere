"""Tests for diagnose_service_allowlisted action in Logi confirmation flow."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.logi_confirmation_flow import (
    parse_diagnose_intent,
    request_diagnose,
    confirm_action,
    format_confirmation_response,
    _pending_path,
    _completed_path,
    _run_diagnose,
)


# ─── intent parsing ──────────────────────────────────────────────────────────

def test_diagnose_intent_russian_diagnostiruuy():
    intent = parse_diagnose_intent("Логи, диагностируй logi-bot")
    assert intent is not None
    assert not intent.get("blocked")
    assert intent["action_type"] == "diagnose_service_allowlisted"
    assert intent["raw_service"] == "logi-bot"


def test_diagnose_intent_russian_diagnostika():
    intent = parse_diagnose_intent("Логи, диагностика logi-bot")
    assert intent is not None
    assert intent["action_type"] == "diagnose_service_allowlisted"


def test_diagnose_intent_russian_bare():
    intent = parse_diagnose_intent("Диагностируй logi-bot")
    assert intent is not None
    assert intent["raw_service"] == "logi-bot"


def test_diagnose_intent_english_diagnose():
    intent = parse_diagnose_intent("Diagnose logi-bot")
    assert intent is not None
    assert intent["action_type"] == "diagnose_service_allowlisted"


def test_diagnose_intent_english_run_diagnostics():
    intent = parse_diagnose_intent("Run diagnostics logi-bot")
    assert intent is not None


def test_diagnose_blocked_on_metachar():
    intent = parse_diagnose_intent("Логи, диагностируй logi-bot; rm -rf /")
    assert intent is not None
    assert intent.get("blocked") is True


def test_diagnose_blocked_on_dangerous_word():
    intent = parse_diagnose_intent("диагностируй logi-bot docker exec")
    assert intent is not None
    assert intent.get("blocked") is True


def test_diagnose_unknown_service_blocked():
    resp = request_diagnose("unknown-bot", "user", "диагностируй unknown-bot")
    assert resp["status"] == "BLOCKED"
    assert resp["error_class"] == "UNKNOWN_SERVICE"


# ─── request_diagnose ─────────────────────────────────────────────────────────

def test_request_diagnose_returns_requires_confirmation():
    resp = request_diagnose("logi-bot", "user_1", "диагностируй logi-bot")
    assert resp["status"] == "REQUIRES_CONFIRMATION"
    assert resp["action_type"] == "diagnose_service_allowlisted"
    assert resp["service"] == "axiomsphere-logi-bot"
    assert resp["lines"] == 50
    assert "action_id" in resp
    assert resp["reply_with"].startswith("CONFIRM ")


def test_pending_confirmation_json_created():
    resp = request_diagnose("logi", "user_2", "диагностируй logi")
    action_id = resp["action_id"]
    assert _pending_path(action_id).exists()
    data = json.loads(_pending_path(action_id).read_text())
    assert data["action_type"] == "diagnose_service_allowlisted"
    assert data["params"]["lines"] == 50


# ─── confirm_action ──────────────────────────────────────────────────────────

def test_confirm_diagnose_returns_passed_or_degraded():
    """CONFIRM runs healthcheck + log scan — PASSED or DEGRADED, never arbitrary shell."""
    resp = request_diagnose("logi-bot", "user_3", "диагностируй logi-bot")
    action_id = resp["action_id"]

    result = confirm_action(action_id)
    assert result["status"] in ("PASSED", "DEGRADED")
    assert result["action_type"] == "diagnose_service_allowlisted"
    assert result["service"] == "axiomsphere-logi-bot"
    assert result.get("health") is not None
    assert "log_lines_scanned" in result
    assert "errors_found" in result
    assert isinstance(result["top_findings"], list)
    assert "recommended_next_action" in result


def test_completed_confirmation_json_created():
    resp = request_diagnose("logi-bot", "user_4", "диагностируй logi-bot")
    action_id = resp["action_id"]
    confirm_action(action_id)
    assert _completed_path(action_id).exists()
    data = json.loads(_completed_path(action_id).read_text())
    assert data["action_type"] == "diagnose_service_allowlisted"
    assert "executed_at" in data


def test_clean_logs_return_passed_errors_0():
    """If log scan finds no error patterns → errors_found=0, PASSED."""
    mock_log = {"status": "PASSED", "log_tail": "INFO: all good\nINFO: running", "lines_returned": 2}
    mock_health = {"status": "PASSED", "health": "running", "method": "self_process"}

    with patch("ops.agents.logi_confirmation_flow._run_healthcheck", return_value=mock_health):
        with patch("ops.agents.logi_confirmation_flow._run_read_logs", return_value=mock_log):
            result = _run_diagnose("axiomsphere-logi-bot")

    assert result["status"] == "PASSED"
    assert result["errors_found"] == 0
    assert "No critical patterns" in result["top_findings"][0]


def test_logs_with_errors_return_degraded():
    """If log scan finds ERROR/Traceback → errors_found > 0, DEGRADED."""
    error_log = "ERROR: something failed\nTraceback (most recent call last):\n  File foo.py"
    mock_log = {"status": "PASSED", "log_tail": error_log, "lines_returned": 3}
    mock_health = {"status": "PASSED", "health": "running", "method": "self_process"}

    with patch("ops.agents.logi_confirmation_flow._run_healthcheck", return_value=mock_health):
        with patch("ops.agents.logi_confirmation_flow._run_read_logs", return_value=mock_log):
            result = _run_diagnose("axiomsphere-logi-bot")

    assert result["status"] == "DEGRADED"
    assert result["errors_found"] > 0
    assert len(result["top_findings"]) > 0


def test_diagnose_no_shell_true():
    """confirm_action for diagnose must never invoke shell=True."""
    import subprocess as sp

    original_run = sp.run
    shell_calls = []

    def spy_run(cmd, **kwargs):
        if kwargs.get("shell"):
            shell_calls.append(cmd)
        return original_run(cmd, **kwargs)

    resp = request_diagnose("logi-bot", "user_5", "диагностируй logi-bot")
    action_id = resp["action_id"]

    with patch("subprocess.run", side_effect=spy_run):
        confirm_action(action_id)

    assert shell_calls == [], f"shell=True detected: {shell_calls}"


# ─── orchestrator integration ─────────────────────────────────────────────────

def _orch(text: str) -> str:
    from logi.conversational_orchestrator import LogiAgent
    return LogiAgent().run(1, text)


def test_orchestrator_diagnose_returns_requires_confirmation():
    resp = _orch("Логи, диагностируй logi-bot")
    assert "STATUS: REQUIRES_CONFIRMATION" in resp
    assert "ACTION_TYPE: diagnose_service_allowlisted" in resp
    assert "SERVICE: axiomsphere-logi-bot" in resp
    assert "REPLY_WITH: CONFIRM" in resp


def test_orchestrator_diagnose_end_to_end():
    """Full two-step diagnose flow through orchestrator."""
    resp1 = _orch("Diagnose logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp1

    action_id = next(
        (l.split(":", 1)[1].strip() for l in resp1.splitlines() if l.startswith("ACTION_ID:")),
        None,
    )
    assert action_id

    resp2 = _orch(f"CONFIRM {action_id}")
    assert "STATUS: PASSED" in resp2 or "STATUS: DEGRADED" in resp2
    assert "ACTION_TYPE: diagnose_service_allowlisted" in resp2
    assert "HEALTH:" in resp2
    assert "LOG_LINES_SCANNED:" in resp2
    assert "ERRORS_FOUND:" in resp2
    assert "TOP_FINDINGS:" in resp2


def test_orchestrator_dangerous_diagnose_blocked():
    resp = _orch("Логи, диагностируй logi-bot; rm -rf /")
    assert "BLOCKED" in resp or "FAILED" in resp
    assert "COMMAND_BLOCKED" in resp


# ─── regression tests ─────────────────────────────────────────────────────────

def test_healthcheck_regression():
    resp = _orch("Логи, проверь здоровье logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp
    assert "ACTION_TYPE: healthcheck_service" in resp


def test_read_logs_regression():
    resp = _orch("Логи, покажи последние 50 строк logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp
    assert "ACTION_TYPE: read_logs_allowlisted" in resp


def test_executor_regression():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json",
        source="telegram",
    )
    assert result["status"] == "PASSED"
