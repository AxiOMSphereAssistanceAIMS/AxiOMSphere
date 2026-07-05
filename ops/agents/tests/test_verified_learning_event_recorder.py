"""Tests for verified_learning_event_recorder.py"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ops.agents.verified_learning_event_recorder import (
    record_learning_event,
    load_recent_events,
    LearningEventInput,
    _EVENTS_FILE,
    _INBOX,
)


def _sample_input(**overrides) -> LearningEventInput:
    base = dict(
        task_id="test-rec-001",
        user_request="show status",
        actor_initial_output="Status: 1234 files",
        actor_final_output="FINAL:\nstatus: PASS\nevidence:\n- master_status.json",
        self_check_result={"status": "FAKE_OUTPUT", "mistake_class": "FAKE_OUTPUT", "findings": ["fake"]},
        codex_audit_result={"status": "SKIPPED", "findings": []},
        verifier_result={"status": "VERIFIED_FAIL"},
        correction_summary="Actor corrected after self-check",
        mistake_class="FAKE_OUTPUT",
        evidence_dir="aims_workspace/test/",
    )
    base.update(overrides)
    return LearningEventInput(**base)


def test_event_written_to_inbox(tmp_path):
    """Learning event must be written to the inbox JSONL file."""
    events_file = tmp_path / "audited_correction_events.jsonl"
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", events_file):
            event = record_learning_event(_sample_input())
    assert events_file.exists()
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["task_id"] == "test-rec-001"


def test_training_eligible_false_without_verifier(tmp_path):
    """training_eligible must be False when verifier result is absent/unavailable."""
    events_file = tmp_path / "audited_correction_events.jsonl"
    inp = _sample_input(verifier_result={"status": "VERIFIER_UNAVAILABLE"})
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", events_file):
            event = record_learning_event(inp)
    assert event["training_eligible"] is False


def test_training_eligible_true_with_verified_fail(tmp_path):
    """training_eligible must be True when verifier returns VERIFIED_FAIL."""
    events_file = tmp_path / "audited_correction_events.jsonl"
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", events_file):
            event = record_learning_event(_sample_input(verifier_result={"status": "VERIFIED_FAIL"}))
    assert event["training_eligible"] is True


def test_initial_and_final_output_preserved_separately(tmp_path):
    """Initial bad output and corrected output must be stored separately."""
    events_file = tmp_path / "audited_correction_events.jsonl"
    bad = "files: 1234 5678 9101"
    good = "FINAL:\nstatus: PASS"
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", events_file):
            event = record_learning_event(_sample_input(
                actor_initial_output=bad,
                actor_final_output=good,
            ))
    assert event["actor_initial_output"] == bad
    assert event["actor_final_output"] == good
    assert event["actor_initial_output"] != event["actor_final_output"]


def test_event_has_required_fields(tmp_path):
    """Event must contain all required schema fields."""
    events_file = tmp_path / "audited_correction_events.jsonl"
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", events_file):
            event = record_learning_event(_sample_input())
    required = [
        "event_id", "created_at_utc", "event_type", "task_id",
        "user_request", "actor_initial_output", "actor_final_output",
        "self_check_result", "codex_audit_result", "verifier_result",
        "correction_summary", "mistake_class", "training_eligible",
        "evidence_dir", "source",
    ]
    for field in required:
        assert field in event, f"Missing field: {field}"


def test_event_type_from_mistake_class(tmp_path):
    """mistake_class correctly maps to event_type."""
    events_file = tmp_path / "audited_correction_events.jsonl"
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", events_file):
            event = record_learning_event(_sample_input(mistake_class="STATIC_ONLY_OPERATIONAL"))
    assert event["event_type"] == "VERIFIED_CONTEXT_MERGE_ERROR"


def test_load_recent_events_empty_when_no_file(tmp_path):
    """load_recent_events returns empty list when no file exists."""
    missing = tmp_path / "nonexistent.jsonl"
    with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", missing):
        events = load_recent_events()
    assert events == []


def test_multiple_events_appended(tmp_path):
    """Multiple events are appended, not overwritten."""
    events_file = tmp_path / "audited_correction_events.jsonl"
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", events_file):
            record_learning_event(_sample_input(task_id="task-A"))
            record_learning_event(_sample_input(task_id="task-B"))
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    ids = {json.loads(l)["task_id"] for l in lines}
    assert ids == {"task-A", "task-B"}
