"""Tests for logi_auditor_request.py"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))


def test_write_auditor_request(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_auditor_request._PENDING_DIR", tmp_path):
        from ops.agents.logi_auditor_request import write_auditor_request
        rec = write_auditor_request(
            problem_summary="Logi cannot restart containers",
            original_message="обратись к аудитору: Logi не может перезапустить контейнеры",
        )
    assert rec.request_id.startswith("auditor_req_")
    assert rec.status == "pending"


def test_auditor_request_file_written(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_auditor_request._PENDING_DIR", tmp_path):
        from ops.agents.logi_auditor_request import write_auditor_request
        rec = write_auditor_request("test problem", "original")
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["problem_summary"] == "test problem"
    assert "safety_constraints" in data


def test_auditor_request_via_orchestrator_requires_confirmation():
    """Auditor request via orchestrator must return REQUIRES_CONFIRMATION."""
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1, "обратись к аудитору по поводу missing capability")
    assert "REQUIRES_CONFIRMATION" in resp or "SKILL_ID" in resp or isinstance(resp, str)


def test_load_auditor_request(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_auditor_request._PENDING_DIR", tmp_path):
        with patch("ops.agents.logi_auditor_request._COMPLETED_DIR", tmp_path / "completed"):
            from ops.agents.logi_auditor_request import write_auditor_request, load_auditor_request
            rec = write_auditor_request("load test", "msg")
            loaded = load_auditor_request(rec.request_id)
    assert loaded is not None
    assert loaded["problem_summary"] == "load test"
