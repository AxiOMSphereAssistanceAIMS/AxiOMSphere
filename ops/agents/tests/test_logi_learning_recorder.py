"""Tests for logi_learning_recorder.py"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))


def test_write_learning_event_candidate(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_learning_recorder._PENDING_DIR", tmp_path / "pending"):
        with patch("ops.agents.logi_learning_recorder._TRAINING_CANDIDATES_DIR", tmp_path / "candidates"):
            from ops.agents.logi_learning_recorder import write_learning_event_candidate
            ev = write_learning_event_candidate(
                source_message="Logi не распознал диагностику",
                user_intent="Logi should route диагностируй to diagnose_service_allowlisted",
                expected_behavior="REQUIRES_CONFIRMATION",
                actual_behavior="Принял. Работаю.",
                failure_class="INTENT_NOT_MATCHED",
            )
    assert ev.event_id.startswith("learn_ev_")
    assert ev.training_eligible is False
    assert ev.failure_class == "INTENT_NOT_MATCHED"


def test_training_eligible_always_false_at_creation(tmp_path):
    """training_eligible must always be False at creation — requires verifier."""
    from unittest.mock import patch
    with patch("ops.agents.logi_learning_recorder._PENDING_DIR", tmp_path / "pending"):
        with patch("ops.agents.logi_learning_recorder._TRAINING_CANDIDATES_DIR", tmp_path / "candidates"):
            from ops.agents.logi_learning_recorder import write_learning_event_candidate
            ev = write_learning_event_candidate("msg", "intent", "expected", "actual")
    assert ev.training_eligible is False


def test_learning_event_creates_pair_candidate(tmp_path):
    """A training pair candidate file must be written alongside the event."""
    from unittest.mock import patch
    candidates_dir = tmp_path / "candidates"
    with patch("ops.agents.logi_learning_recorder._PENDING_DIR", tmp_path / "pending"):
        with patch("ops.agents.logi_learning_recorder._TRAINING_CANDIDATES_DIR", candidates_dir):
            from ops.agents.logi_learning_recorder import write_learning_event_candidate
            ev = write_learning_event_candidate("msg", "intent", "expected", "actual")
    files = list(candidates_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["training_eligible"] is False
    assert "pair" in data


def test_learning_event_via_orchestrator_requires_confirmation():
    """Learning registration via orchestrator must return REQUIRES_CONFIRMATION."""
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1,
        "Логи, зарегистрируй этот сбой в учебный пайплайн: Logi не распознал диагностику")
    assert "REQUIRES_CONFIRMATION" in resp or "SKILL_ID" in resp


def test_no_training_run_started(tmp_path):
    """Writing a learning event must not trigger a training run."""
    from unittest.mock import patch
    called = []
    def spy_run(cmd, **kwargs):
        called.append(cmd)

    import subprocess
    orig = subprocess.run
    with patch("subprocess.run", side_effect=spy_run):
        with patch("ops.agents.logi_learning_recorder._PENDING_DIR", tmp_path / "pending"):
            with patch("ops.agents.logi_learning_recorder._TRAINING_CANDIDATES_DIR", tmp_path / "candidates"):
                from ops.agents.logi_learning_recorder import write_learning_event_candidate
                write_learning_event_candidate("msg", "intent", "expected", "actual")

    # No subprocess calls should have been made
    assert called == [], f"Unexpected subprocess calls: {called}"
