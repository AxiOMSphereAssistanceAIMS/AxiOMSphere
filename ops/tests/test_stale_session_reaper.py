from __future__ import annotations

import json

from ops.self_learning.stale_session_reaper import classify_stale_session


def test_missing_final_without_live_pid_is_hold_not_fabricated(tmp_path):
    session = tmp_path / "s1"
    session.mkdir()
    (session / "session_manifest.json").write_text(json.dumps({"status": "RUNNING", "pid": 99999}) + "\n")
    (session / "transcript.md").write_text("bounded evidence\n")
    result = classify_stale_session(session, set())
    assert result["decision"] == "HOLD_STALE_NO_LIVE_PID"
    assert result["terminal_time_fabricated"] is False
    assert result["deletion_performed"] is False


def test_live_pid_is_never_touched(tmp_path):
    session = tmp_path / "s2"
    session.mkdir()
    (session / "session_manifest.json").write_text(json.dumps({"status": "RUNNING", "pid": 42}) + "\n")
    result = classify_stale_session(session, {42})
    assert result["decision"] == "ACTIVE_DO_NOT_TOUCH"
