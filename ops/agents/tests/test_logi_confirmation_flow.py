"""Tests for logi_confirmation_flow.py — two-step healthcheck confirmation."""
import json
import time
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.logi_confirmation_flow import (
    parse_healthcheck_intent,
    parse_confirm_intent,
    request_healthcheck,
    confirm_action,
    format_confirmation_response,
    _PENDING_DIR,
    _COMPLETED_DIR,
    _pending_path,
    _completed_path,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _orch(text: str) -> str:
    from logi.conversational_orchestrator import LogiAgent
    return LogiAgent().run(1, text)


# ─── intent parsing ──────────────────────────────────────────────────────────

def test_parse_healthcheck_russian():
    intent = parse_healthcheck_intent("Логи, проверь здоровье logi-bot")
    assert intent is not None
    assert intent.get("blocked") is not True
    assert intent["action_type"] == "healthcheck_service"
    assert intent["raw_service"] == "logi-bot"


def test_parse_healthcheck_english():
    intent = parse_healthcheck_intent("Логи, healthcheck logi-bot")
    assert intent is not None
    assert intent["raw_service"] == "logi-bot"


def test_parse_healthcheck_check_health():
    intent = parse_healthcheck_intent("Check health logi-bot")
    assert intent is not None
    assert intent["action_type"] == "healthcheck_service"


def test_parse_healthcheck_status():
    intent = parse_healthcheck_intent("Проверь статус logi-bot")
    assert intent is not None


def test_parse_healthcheck_blocked_on_metachar():
    intent = parse_healthcheck_intent("Логи, проверь здоровье logi-bot; rm -rf /")
    assert intent is not None
    assert intent.get("blocked") is True
    assert ";" in intent["reason"] or "blocked" in intent["reason"].lower()


def test_parse_healthcheck_blocked_on_dangerous_word():
    intent = parse_healthcheck_intent("проверь статус logi-bot docker restart")
    assert intent is not None
    assert intent.get("blocked") is True


def test_parse_confirm_valid():
    assert parse_confirm_intent("CONFIRM abc12345") == "abc12345"
    assert parse_confirm_intent("confirm ABC12345") == "abc12345"


def test_parse_confirm_none_for_normal_message():
    assert parse_confirm_intent("покажи статус проекта") is None
    assert parse_confirm_intent("CONFIRM") is None  # no id


# ─── request_healthcheck ─────────────────────────────────────────────────────

def test_healthcheck_intent_returns_requires_confirmation():
    """request_healthcheck must return REQUIRES_CONFIRMATION and create pending JSON."""
    resp = request_healthcheck("logi-bot", "user_1", "Логи, проверь здоровье logi-bot")
    assert resp["status"] == "REQUIRES_CONFIRMATION"
    assert resp["action_type"] == "healthcheck_service"
    assert resp["service"] == "axiomsphere-logi-bot"
    assert "action_id" in resp
    assert "reply_with" in resp
    assert resp["reply_with"].startswith("CONFIRM ")


def test_pending_confirmation_json_created():
    """Pending confirmation JSON must be written to disk."""
    resp = request_healthcheck("logi", "user_2", "healthcheck logi")
    action_id = resp["action_id"]
    pending_file = _pending_path(action_id)
    assert pending_file.exists(), f"Pending file not found: {pending_file}"
    data = json.loads(pending_file.read_text())
    assert data["action_id"] == action_id
    assert data["service"] == "axiomsphere-logi-bot"
    assert data["action_type"] == "healthcheck_service"
    assert "expires_at" in data


def test_unknown_service_returns_blocked():
    resp = request_healthcheck("unknown-bot", "user_3", "healthcheck unknown-bot")
    assert resp["status"] == "BLOCKED"
    assert resp["error_class"] == "UNKNOWN_SERVICE"


# ─── confirm_action ──────────────────────────────────────────────────────────

def test_confirm_valid_action_returns_passed():
    """Valid CONFIRM of logi-bot healthcheck → PASSED + HEALTH running via self_process."""
    resp = request_healthcheck("logi-bot", "user_4", "healthcheck logi-bot")
    action_id = resp["action_id"]

    result = confirm_action(action_id)
    # logi-bot uses self_process — always PASSED when this code is running
    assert result["status"] == "PASSED"
    assert result["action_type"] == "healthcheck_service"
    assert result["service"] == "axiomsphere-logi-bot"
    assert result.get("health") == "running"


def test_completed_confirmation_json_created():
    """Completed confirmation JSON must be written after confirm."""
    resp = request_healthcheck("logi-bot", "user_5", "healthcheck logi-bot")
    action_id = resp["action_id"]
    confirm_action(action_id)

    completed_file = _completed_path(action_id)
    assert completed_file.exists(), f"Completed file not found: {completed_file}"
    data = json.loads(completed_file.read_text())
    assert data["action_id"] == action_id
    assert "executed_at" in data
    assert "result" in data


def test_pending_file_removed_after_confirm():
    """Pending file must be deleted after confirm."""
    resp = request_healthcheck("logi-bot", "user_6", "healthcheck logi-bot")
    action_id = resp["action_id"]
    confirm_action(action_id)
    assert not _pending_path(action_id).exists()


def test_unknown_action_id_returns_failed():
    result = confirm_action("0000000000ab")
    assert result["status"] == "FAILED"
    assert result["error_class"] == "UNKNOWN_CONFIRMATION"


def test_already_completed_returns_failed():
    """Confirming already-completed action returns ALREADY_COMPLETED."""
    resp = request_healthcheck("logi-bot", "user_7", "healthcheck logi-bot")
    action_id = resp["action_id"]
    confirm_action(action_id)
    result2 = confirm_action(action_id)
    assert result2["status"] == "FAILED"
    assert result2["error_class"] == "ALREADY_COMPLETED"


def test_expired_confirmation_returns_failed():
    """An expired pending confirmation must return EXPIRED_CONFIRMATION."""
    resp = request_healthcheck("logi-bot", "user_8", "healthcheck logi-bot")
    action_id = resp["action_id"]

    # Rewrite pending with past expiry
    pending_file = _pending_path(action_id)
    data = json.loads(pending_file.read_text())
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    data["expires_at"] = past
    pending_file.write_text(json.dumps(data))

    result = confirm_action(action_id)
    assert result["status"] == "FAILED"
    assert result["error_class"] == "EXPIRED_CONFIRMATION"


# ─── dangerous message blocked ───────────────────────────────────────────────

def test_dangerous_healthcheck_message_blocked():
    """healthcheck with dangerous content must be blocked before confirmation is created."""
    resp = _orch("Логи, проверь здоровье logi-bot; rm -rf /")
    assert "BLOCKED" in resp or "FAILED" in resp
    assert "COMMAND_BLOCKED" in resp or "BLOCKED" in resp


def test_confirm_cannot_execute_arbitrary_command():
    """CONFIRM with arbitrary text (no valid action_id) must fail."""
    result = confirm_action("not_a_real_id")
    assert result["status"] == "FAILED"


# ─── orchestrator integration ─────────────────────────────────────────────────

def test_orchestrator_healthcheck_returns_requires_confirmation():
    resp = _orch("Логи, проверь здоровье logi-bot")
    assert "STATUS: REQUIRES_CONFIRMATION" in resp
    assert "ACTION_TYPE: healthcheck_service" in resp
    assert "SERVICE: axiomsphere-logi-bot" in resp
    assert "ACTION_ID:" in resp
    assert "REPLY_WITH: CONFIRM" in resp


def test_orchestrator_confirm_flow_end_to_end():
    """Full two-step flow through orchestrator — logi-bot uses self_process."""
    resp1 = _orch("Логи, healthcheck logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp1

    action_id = None
    for line in resp1.splitlines():
        if line.startswith("ACTION_ID:"):
            action_id = line.split(":", 1)[1].strip()
    assert action_id, "No ACTION_ID in step 1 response"

    resp2 = _orch(f"CONFIRM {action_id}")
    assert "STATUS: PASSED" in resp2
    assert "ACTION_TYPE: healthcheck_service" in resp2
    assert "HEALTH: running" in resp2


# ─── self_process backend (no docker) ─────────────────────────────────────────

def test_logi_bot_healthcheck_uses_self_process():
    """healthcheck for logi-bot returns PASSED via self_process without docker."""
    from ops.agents.logi_confirmation_flow import _healthcheck_self_process
    result = _healthcheck_self_process()
    assert result["status"] == "PASSED"
    assert result["health"] == "running"
    assert result["method"] == "self_process"
    assert "pid" in result


def test_logi_bot_healthcheck_does_not_need_docker():
    """Even if docker CLI is absent, logi-bot healthcheck must return PASSED."""
    from ops.agents.logi_confirmation_flow import _run_healthcheck
    from unittest.mock import patch

    # Simulate docker CLI being absent — should never be reached for logi-bot
    with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
        result = _run_healthcheck("axiomsphere-logi-bot")

    # self_process is used before docker is ever attempted
    assert result["status"] == "PASSED"
    assert result["health"] == "running"
    assert result["method"] == "self_process"


def test_run_healthcheck_logi_bot_full():
    """_run_healthcheck('axiomsphere-logi-bot') → PASSED, running, self_process."""
    from ops.agents.logi_confirmation_flow import _run_healthcheck
    result = _run_healthcheck("axiomsphere-logi-bot")
    assert result["status"] == "PASSED"
    assert result["health"] == "running"
    assert result.get("method") == "self_process"


def test_unknown_service_still_blocked():
    """Unknown container not in allowlist returns structured UNKNOWN_SERVICE."""
    from ops.agents.logi_confirmation_flow import _run_healthcheck
    result = _run_healthcheck("some-random-container")
    assert result["status"] == "FAILED"
    assert result.get("error_class") == "UNKNOWN_SERVICE"


def test_confirmation_confirm_passes_without_docker():
    """Full confirmation cycle for logi-bot — no docker dependency."""
    from ops.agents.logi_confirmation_flow import request_healthcheck, confirm_action
    from unittest.mock import patch

    with patch("subprocess.run", side_effect=FileNotFoundError("no docker")):
        resp = request_healthcheck("logi-bot", "test_user", "healthcheck logi-bot")
        action_id = resp["action_id"]
        result = confirm_action(action_id)

    assert result["status"] == "PASSED"
    assert result["health"] == "running"
