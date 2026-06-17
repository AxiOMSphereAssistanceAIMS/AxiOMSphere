import json

from ops.docgen.universal_overlay import model_snapshot
from ops.docgen.universal_overlay.model_snapshot import capture_model_runtime_snapshot


def test_capture_model_runtime_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(
        model_snapshot,
        "_run",
        lambda cmd, timeout=20: {
            "cmd": cmd,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
        },
    )
    monkeypatch.setattr(
        model_snapshot,
        "_capture_slot",
        lambda slot: {
            "slot": slot,
            "resolved_model": f"model-{slot}",
            "backend_url": "http://localhost:11434",
            "tags_available": True,
            "runtime_available": True,
            "model_listed": True,
            "model_loaded": slot == "14",
        },
    )
    path = capture_model_runtime_snapshot(tmp_path / "snapshot.json")

    assert path.exists()
    data = json.loads(path.read_text())
    assert "captured_at" in data
    assert "git_status" in data
    assert set(data["model_slots"]) == {"14", "32", "120"}
    assert data["model_slots"]["14"]["model_loaded"] is True
