import json
import sys

from ops.ft.scripts import run_benchmark_after_pass as module


def test_strips_remainder_separator_before_child_command(tmp_path, monkeypatch):
    prerequisite = tmp_path / "pass.json"
    prerequisite.write_text(json.dumps({
        "summary": {"status": "PASS", "decision_allowed": True},
    }))
    captured = {}

    class Result:
        returncode = 0

    def fake_run(command, check):
        captured["command"] = command
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "run_benchmark_after_pass.py",
        "--prerequisite", str(prerequisite),
        "--",
        "--model-a", "candidate",
        "--model-b", "baseline",
    ])

    assert module.main() == 0
    assert captured["command"][-4:] == [
        "--model-a", "candidate", "--model-b", "baseline",
    ]
    assert "--" not in captured["command"]
