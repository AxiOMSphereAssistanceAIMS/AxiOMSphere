"""Tests for logi_artifact_store.py"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.logi_artifact_store import write_skill_artifact, load_latest_artifact


def test_write_skill_artifact_creates_file(tmp_path):
    from ops.agents.logi_artifact_store import _ARTIFACTS_DIR
    from unittest.mock import patch
    with patch("ops.agents.logi_artifact_store._ARTIFACTS_DIR", tmp_path):
        artifact = write_skill_artifact(
            skill_id="office_hours",
            source_message="office hours test",
            output={"SIX_FORCING_QUESTIONS": ["Q1", "Q2"]},
            user_id="1", chat_id="test",
        )
    assert artifact.artifact_id.startswith("office_hours_")
    skill_dir = tmp_path / "office_hours"
    assert skill_dir.exists()
    files = list(skill_dir.glob("*.json"))
    assert len(files) == 1


def test_artifact_has_required_fields(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_artifact_store._ARTIFACTS_DIR", tmp_path):
        artifact = write_skill_artifact(
            skill_id="ceo_review",
            source_message="ceo review test",
            output={"SCOPE_CHALLENGE": "test"},
        )
    assert artifact.skill_id == "ceo_review"
    assert artifact.source_message == "ceo review test"
    assert artifact.status == "PASSED"
    assert artifact.learning_event_candidate is False


def test_load_latest_artifact(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_artifact_store._ARTIFACTS_DIR", tmp_path):
        write_skill_artifact("test_skill", "msg1", {"k": "v1"})
        write_skill_artifact("test_skill", "msg2", {"k": "v2"})
        latest = load_latest_artifact("test_skill")
    assert latest is not None
    assert latest["skill_id"] == "test_skill"


def test_load_missing_returns_none(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_artifact_store._ARTIFACTS_DIR", tmp_path):
        result = load_latest_artifact("nonexistent_skill")
    assert result is None
