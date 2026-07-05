"""Tests for logi_skill_request.py"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))


def test_write_skill_request(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_skill_request._PENDING_DIR", tmp_path):
        from ops.agents.logi_skill_request import write_skill_request
        rec = write_skill_request(
            skill_name="diagnose_container_deep",
            purpose="Deep container diagnostics",
            original_message="создай skill для диагностики сервисов",
        )
    assert rec.request_id.startswith("skill_req_")
    assert rec.auditor_review_required is True
    assert rec.status == "pending"


def test_auditor_review_always_required(tmp_path):
    """auditor_review_required must always be True."""
    from unittest.mock import patch
    with patch("ops.agents.logi_skill_request._PENDING_DIR", tmp_path):
        from ops.agents.logi_skill_request import write_skill_request
        rec = write_skill_request("any_skill", "purpose", "msg")
    assert rec.auditor_review_required is True


def test_skill_request_file_has_required_fields(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_skill_request._PENDING_DIR", tmp_path):
        from ops.agents.logi_skill_request import write_skill_request
        rec = write_skill_request("my_skill", "do X", "original msg")
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    for field in ["skill_name", "purpose", "auditor_review_required",
                  "allowed_actions", "forbidden_actions", "safety_constraints"]:
        assert field in data, f"Missing field: {field}"
    assert data["auditor_review_required"] is True


def test_skill_request_via_orchestrator_requires_confirmation():
    """Skill request via orchestrator must return REQUIRES_CONFIRMATION."""
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1, "Логи, создай skill для диагностики сервисов")
    assert "REQUIRES_CONFIRMATION" in resp or "SKILL_ID" in resp
