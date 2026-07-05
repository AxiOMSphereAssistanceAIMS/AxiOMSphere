"""Tests for read_logs_allowlisted action in Logi confirmation flow."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.logi_confirmation_flow import (
    parse_read_logs_intent,
    request_read_logs,
    confirm_action,
    format_confirmation_response,
    _pending_path,
    _completed_path,
    _READ_LOGS_DEFAULT_LINES,
    _READ_LOGS_MAX_LINES,
)


# ─── intent parsing ──────────────────────────────────────────────────────────

def test_read_logs_russian_pokaji_50():
    intent = parse_read_logs_intent("Логи, покажи последние 50 строк logi-bot")
    assert intent is not None
    assert not intent.get("blocked")
    assert intent["action_type"] == "read_logs_allowlisted"
    assert intent["raw_service"] == "logi-bot"
    assert intent["lines"] == 50


def test_read_logs_russian_pokaji_logs():
    intent = parse_read_logs_intent("Логи, покажи логи logi-bot")
    assert intent is not None
    assert not intent.get("blocked")
    assert intent["action_type"] == "read_logs_allowlisted"
    assert intent["raw_service"] == "logi-bot"


def test_read_logs_english_show_last_100():
    intent = parse_read_logs_intent("Show last 100 lines logi-bot")
    assert intent is not None
    assert intent["lines"] == 100


def test_read_logs_english_read_logs():
    intent = parse_read_logs_intent("Read logs logi-bot")
    assert intent is not None
    assert intent["action_type"] == "read_logs_allowlisted"


def test_read_logs_default_lines_50():
    """When no line count given, default must be 50."""
    intent = parse_read_logs_intent("покажи логи logi-bot")
    assert intent is not None
    assert intent["lines"] == _READ_LOGS_DEFAULT_LINES


def test_read_logs_parse_100():
    intent = parse_read_logs_intent("покажи последние 100 строк logi-bot")
    assert intent is not None
    assert intent["lines"] == 100


def test_read_logs_clamp_above_200():
    """Lines > 200 must be clamped to 200 with lines_clamped=True."""
    intent = parse_read_logs_intent("покажи последние 500 строк logi-bot")
    assert intent is not None
    assert intent["lines"] == _READ_LOGS_MAX_LINES
    assert intent["lines_clamped"] is True


def test_read_logs_blocked_on_metachar():
    intent = parse_read_logs_intent("покажи логи logi-bot; rm -rf /")
    assert intent is not None
    assert intent.get("blocked") is True


def test_read_logs_blocked_on_dangerous_word():
    intent = parse_read_logs_intent("покажи логи logi-bot docker exec")
    assert intent is not None
    assert intent.get("blocked") is True


def test_unknown_service_blocked():
    resp = request_read_logs("unknown-bot", 50, False, "user", "покажи логи unknown-bot")
    assert resp["status"] == "BLOCKED"
    assert resp["error_class"] == "UNKNOWN_SERVICE"


# ─── request_read_logs ────────────────────────────────────────────────────────

def test_request_read_logs_returns_requires_confirmation():
    resp = request_read_logs("logi-bot", 50, False, "user_1", "покажи логи logi-bot")
    assert resp["status"] == "REQUIRES_CONFIRMATION"
    assert resp["action_type"] == "read_logs_allowlisted"
    assert resp["service"] == "axiomsphere-logi-bot"
    assert resp["lines"] == 50
    assert "action_id" in resp
    assert resp["reply_with"].startswith("CONFIRM ")


def test_pending_confirmation_json_created():
    resp = request_read_logs("logi", 50, False, "user_2", "покажи логи logi")
    action_id = resp["action_id"]
    pending_file = _pending_path(action_id)
    assert pending_file.exists()
    data = json.loads(pending_file.read_text())
    assert data["action_type"] == "read_logs_allowlisted"
    assert data["params"]["lines"] == 50


def test_lines_clamped_flag_in_response():
    resp = request_read_logs("logi-bot", 200, True, "user_3", "покажи 500 строк logi-bot")
    assert resp.get("lines_clamped") is True


# ─── confirm_action ──────────────────────────────────────────────────────────

def test_confirm_read_logs_logi_bot_returns_passed_or_unavailable():
    """CONFIRM for logi-bot read_logs → PASSED with log_tail or structured unavailable."""
    resp = request_read_logs("logi-bot", 50, False, "user_4", "покажи логи logi-bot")
    action_id = resp["action_id"]

    result = confirm_action(action_id)
    # Must be PASSED (log file exists) or FAILED with LOG_BACKEND_UNAVAILABLE
    assert result["status"] in ("PASSED", "FAILED")
    assert result["action_type"] == "read_logs_allowlisted"
    if result["status"] == "FAILED":
        assert result.get("error_class") == "LOG_BACKEND_UNAVAILABLE"
    else:
        assert "log_tail" in result
        assert len(result["log_tail"]) > 0


def test_completed_confirmation_json_created():
    resp = request_read_logs("logi-bot", 10, False, "user_5", "покажи логи logi-bot")
    action_id = resp["action_id"]
    confirm_action(action_id)

    completed_file = _completed_path(action_id)
    assert completed_file.exists()
    data = json.loads(completed_file.read_text())
    assert data["action_id"] == action_id
    assert data["action_type"] == "read_logs_allowlisted"
    assert "executed_at" in data
    assert "result" in data


def test_confirm_does_not_execute_arbitrary_shell():
    """confirm_action must never pass user input to a shell command."""
    # Verify subprocess is never called with shell=True for read_logs
    import subprocess as sp

    original_run = sp.run
    shell_calls = []

    def spy_run(cmd, **kwargs):
        if kwargs.get("shell"):
            shell_calls.append(cmd)
        return original_run(cmd, **kwargs)

    resp = request_read_logs("logi-bot", 20, False, "user_6", "покажи логи logi-bot")
    action_id = resp["action_id"]

    with patch("subprocess.run", side_effect=spy_run):
        confirm_action(action_id)

    assert shell_calls == [], f"shell=True calls detected: {shell_calls}"


# ─── orchestrator integration ─────────────────────────────────────────────────

def _orch(text: str) -> str:
    from logi.conversational_orchestrator import LogiAgent
    return LogiAgent().run(1, text)


def test_orchestrator_read_logs_returns_requires_confirmation():
    resp = _orch("Логи, покажи последние 50 строк logi-bot")
    assert "STATUS: REQUIRES_CONFIRMATION" in resp
    assert "ACTION_TYPE: read_logs_allowlisted" in resp
    assert "SERVICE: axiomsphere-logi-bot" in resp
    assert "LINES: 50" in resp
    assert "REPLY_WITH: CONFIRM" in resp


def test_orchestrator_read_logs_end_to_end():
    """Full two-step flow for read_logs through orchestrator."""
    resp1 = _orch("Логи, покажи логи logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp1

    action_id = None
    for line in resp1.splitlines():
        if line.startswith("ACTION_ID:"):
            action_id = line.split(":", 1)[1].strip()
    assert action_id

    resp2 = _orch(f"CONFIRM {action_id}")
    assert "STATUS: PASSED" in resp2 or "LOG_BACKEND_UNAVAILABLE" in resp2
    assert "ACTION_TYPE: read_logs_allowlisted" in resp2


def test_orchestrator_dangerous_log_request_blocked():
    resp = _orch("Логи, покажи логи logi-bot; rm -rf /")
    assert "BLOCKED" in resp or "FAILED" in resp
    assert "COMMAND_BLOCKED" in resp


# ─── regression: healthcheck_service still works ─────────────────────────────

def test_healthcheck_service_regression():
    resp = _orch("Логи, проверь здоровье logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp
    assert "ACTION_TYPE: healthcheck_service" in resp


def test_healthcheck_confirm_regression():
    resp1 = _orch("Логи, healthcheck logi-bot")
    action_id = next(
        (l.split(":", 1)[1].strip() for l in resp1.splitlines() if l.startswith("ACTION_ID:")),
        None,
    )
    assert action_id
    resp2 = _orch(f"CONFIRM {action_id}")
    assert "STATUS: PASSED" in resp2
    assert "HEALTH: running" in resp2
