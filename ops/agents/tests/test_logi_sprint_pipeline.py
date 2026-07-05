"""Tests for logi_sprint_pipeline.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))


def test_create_sprint_state(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_sprint_pipeline._SPRINTS_DIR", tmp_path):
        from ops.agents.logi_sprint_pipeline import create_sprint_state
        state = create_sprint_state("Fix scheduler timeout")
    assert state.sprint_id.startswith("sprint_")
    assert state.goal == "Fix scheduler timeout"
    assert state.current_phase == "THINK"
    assert state.status == "ACTIVE"


def test_sprint_state_persisted(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_sprint_pipeline._SPRINTS_DIR", tmp_path):
        from ops.agents.logi_sprint_pipeline import create_sprint_state, load_sprint_state
        state = create_sprint_state("Test goal")
        loaded = load_sprint_state(state.sprint_id)
    assert loaded is not None
    assert loaded.goal == "Test goal"


def test_advance_sprint_state(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_sprint_pipeline._SPRINTS_DIR", tmp_path):
        from ops.agents.logi_sprint_pipeline import create_sprint_state, advance_sprint_state
        state = create_sprint_state("advance test")
        updated = advance_sprint_state(state.sprint_id, {"skill_id": "office_hours"})
    assert "office_hours" in updated.skills_run


def test_recommend_next_skill(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_sprint_pipeline._SPRINTS_DIR", tmp_path):
        from ops.agents.logi_sprint_pipeline import create_sprint_state, recommend_next_skill
        state = create_sprint_state("recommend test")
        recs = recommend_next_skill(state.sprint_id)
    assert isinstance(recs, list)
    assert len(recs) > 0


def test_summarize_sprint_state(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_sprint_pipeline._SPRINTS_DIR", tmp_path):
        from ops.agents.logi_sprint_pipeline import create_sprint_state, summarize_sprint_state
        state = create_sprint_state("summarize test")
        summary = summarize_sprint_state(state.sprint_id)
    assert "THINK" in summary or "PLAN" in summary
    assert "summarize test" in summary


def test_missing_sprint_returns_none(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_sprint_pipeline._SPRINTS_DIR", tmp_path):
        from ops.agents.logi_sprint_pipeline import load_sprint_state
        result = load_sprint_state("nonexistent_sprint_id")
    assert result is None
