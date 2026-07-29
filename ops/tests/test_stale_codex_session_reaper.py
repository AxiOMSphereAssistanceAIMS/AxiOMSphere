from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ops.logi.stale_codex_session_reaper import reap


def _session(tmp_path: Path) -> Path:
    path = tmp_path / "aims_workspace/logi/raw_material/codex_sessions/stale"
    path.mkdir(parents=True)
    manifest = {
        "status": "RUNNING",
        "started_at_utc": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "pid_launcher": 123,
        "launcher_path": "/safe/launcher",
    }
    (path / "session_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_reaper_closes_only_orphan_without_signaling(monkeypatch, tmp_path: Path) -> None:
    path = _session(tmp_path)
    monkeypatch.setattr("ops.logi.stale_codex_session_reaper._owned_process", lambda manifest: None)
    report = reap(tmp_path, max_age_seconds=3600, apply=True)
    assert report["sessions"][0]["action"] == "ORPHANED_CAPTURE_CLOSED"
    assert json.loads((path / "final_status.json").read_text())["forced_termination"] is False


def test_reaper_never_kills_verified_live_process(monkeypatch, tmp_path: Path) -> None:
    path = _session(tmp_path)
    monkeypatch.setattr(
        "ops.logi.stale_codex_session_reaper._owned_process",
        lambda manifest: {"pid": 123, "cmd_tokens": ["/safe/launcher"]},
    )
    report = reap(tmp_path, max_age_seconds=3600, apply=True)
    assert report["sessions"][0]["action"] == "BLOCKED_VERIFIED_PROCESS_STILL_LIVE"
    assert not (path / "final_status.json").exists()
    assert json.loads((path / "session_manifest.json").read_text())["status"] == "RUNNING"
