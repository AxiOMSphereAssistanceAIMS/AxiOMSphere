import json
import os
import shlex
import time

from ops.ft.scripts import watch_benchmark_chain as module


def test_result_passed_requires_pass_and_decision(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"summary": {"status": "PASS", "decision_allowed": True}}))
    assert module._result_passed(path) is True

    path.write_text(json.dumps({"summary": {"status": "PASS", "decision_allowed": False}}))
    assert module._result_passed(path) is False


def test_stall_requires_running_process_and_old_log(tmp_path, monkeypatch):
    stage = {
        "id": "test",
        "session": "test",
        "prerequisite": "prerequisite.json",
        "result": "result.json",
        "log": "progress.log",
    }
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "prerequisite.json").write_text(
        json.dumps({"summary": {"status": "PASS", "decision_allowed": True}})
    )
    log = tmp_path / "progress.log"
    log.write_text("progress")
    old = time.time() - 1300
    os.utime(log, (old, old))
    monkeypatch.setattr(module, "_benchmark_running", lambda _: True)
    monkeypatch.setattr(module, "_benchmark_process_age", lambda _: 1300)
    monkeypatch.setattr(module, "_session_exists", lambda _: True)

    snapshot = module.inspect_stage(stage, stall_seconds=1200)
    assert snapshot["stalled"] is True


def test_recent_benchmark_is_not_stalled_by_old_waiting_log(tmp_path, monkeypatch):
    stage = {
        "id": "test",
        "session": "test",
        "prerequisite": "prerequisite.json",
        "result": "result.json",
        "log": "progress.log",
    }
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "prerequisite.json").write_text(
        json.dumps({"summary": {"status": "PASS", "decision_allowed": True}})
    )
    log = tmp_path / "progress.log"
    log.write_text("")
    old = time.time() - 3000
    os.utime(log, (old, old))
    monkeypatch.setattr(module, "_benchmark_running", lambda _: True)
    monkeypatch.setattr(module, "_benchmark_process_age", lambda _: 30)
    monkeypatch.setattr(module, "_session_exists", lambda _: True)

    snapshot = module.inspect_stage(stage, stall_seconds=1200)

    assert snapshot["benchmark_process_age_seconds"] == 30
    assert snapshot["stalled"] is False


def test_codex_repair_uses_unrestricted_noninteractive_mode(tmp_path, monkeypatch):
    stage = {
        "id": "test",
        "session": "benchmark-test",
    }
    captured = {}

    def fake_run(command, check):
        captured["command"] = command

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "STATUS_DIR", tmp_path / "status")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module._invoke_codex_repair(stage, {"stalled": True}, 1)

    command_text = captured["command"][-1]
    parsed = shlex.split(command_text.split(" > ", 1)[0])
    assert "--dangerously-bypass-approvals-and-sandbox" in parsed
    assert "workspace-write" not in parsed
