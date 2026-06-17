from __future__ import annotations

import json
from pathlib import Path

from ops.traini import slot14_lifecycle_report as slr


def _write_summary(path: Path) -> None:
    payload = {
        "winner": "omi-ft-14b-v20:latest",
        "runner_up": "omi-ft-14b-v19:latest",
        "ranking": [
            {"model": "omi-ft-14b-v20:latest", "pass_rate": 0.96, "passed": 19, "total": 20},
            {"model": "omi-ft-14b-v19:latest", "pass_rate": 0.95, "passed": 18, "total": 20},
            {"model": "omi-ft-14b-v18:latest", "pass_rate": 0.93, "passed": 17, "total": 20},
            {"model": "omi-ft-14b-v16:latest", "pass_rate": 0.91, "passed": 16, "total": 20},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_cleanup_request_keeps_winner_and_runner_up() -> None:
    summary = {
        "winner": "omi-ft-14b-v20:latest",
        "runner_up": "omi-ft-14b-v19:latest",
        "ranking": [
            {"model": "omi-ft-14b-v20:latest"},
            {"model": "omi-ft-14b-v19:latest"},
            {"model": "omi-ft-14b-v18:latest"},
            {"model": "omi-ft-14b-v16:latest"},
        ],
    }
    cleanup = slr.build_cleanup_request(summary)
    assert cleanup["retain_models"] == ["omi-ft-14b-v20:latest", "omi-ft-14b-v19:latest"]
    assert cleanup["delete_candidates"] == ["omi-ft-14b-v18:latest", "omi-ft-14b-v16:latest"]
    assert cleanup["operator_confirmation_required"] is True


def test_pin_locks_when_winner_exceeds_budget_and_stays_locked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(slr, "STATE_DIR", tmp_path / "state", raising=False)
    monkeypatch.setattr(slr, "PIN_STATE_PATH", tmp_path / "state" / "slot14_pc_andrei_pin_lock.json", raising=False)

    summary = {
        "winner": "omi-ft-14b-v20:latest",
        "runner_up": "omi-ft-14b-v19:latest",
        "ranking": [
            {"model": "omi-ft-14b-v20:latest"},
            {"model": "omi-ft-14b-v19:latest"},
            {"model": "omi-ft-14b-v18:latest"},
        ],
    }
    size_map = {
        "omi-ft-14b-v20:latest": 16.2,
        "omi-ft-14b-v19:latest": 15.1,
        "omi-ft-14b-v18:latest": 14.8,
    }

    first = slr.build_pin_decision(summary, size_map=size_map, pin_state={"locked": False, "pinned_model": None})
    assert first["policy"] == "fallback_lock"
    assert first["locked"] is True
    assert first["pinned_model"] == "omi-ft-14b-v19:latest"

    slr.save_pin_state(
        {
            "locked": True,
            "pinned_model": first["pinned_model"],
            "policy": first["policy"],
            "reason": first["reason"],
        },
        path=slr.PIN_STATE_PATH,
    )
    assert slr.PIN_STATE_PATH.exists()

    second = slr.build_pin_decision(
        summary,
        size_map={"omi-ft-14b-v20:latest": 13.8, "omi-ft-14b-v19:latest": 12.9},
        pin_state=slr.load_pin_state(),
    )
    assert second["policy"] == "locked_pin"
    assert second["pinned_model"] == "omi-ft-14b-v19:latest"
    assert second["locked"] is True


def test_pin_ignores_stale_lock_when_current_winner_fits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(slr, "STATE_DIR", tmp_path / "state", raising=False)
    monkeypatch.setattr(slr, "PIN_STATE_PATH", tmp_path / "state" / "slot14_pc_andrei_pin_lock.json", raising=False)

    summary = {
        "winner": "qwen25-chat-14-v19:latest",
        "runner_up": "qwen25-chat-14-v19-new:latest",
        "ranking": [
            {"model": "qwen25-chat-14-v19:latest"},
            {"model": "qwen25-chat-14-v19-new:latest"},
            {"model": "omi-ft-14b-v18:latest"},
        ],
    }
    size_map = {
        "qwen25-chat-14-v19:latest": 14.62,
        "qwen25-chat-14-v19-new:latest": 14.62,
        "omi-ft-14b-v18:latest": 14.8,
    }
    pin_state = {
        "locked": True,
        "pinned_model": "omi-ft-14b-v19:latest",
        "policy": "fallback_lock",
    }

    decision = slr.build_pin_decision(summary, size_map=size_map, pin_state=pin_state)
    assert decision["policy"] == "winner_fits"
    assert decision["locked"] is False
    assert decision["pinned_model"] == "qwen25-chat-14-v19:latest"


def test_emit_artifacts_writes_report_cleanup_and_pin(tmp_path: Path, monkeypatch) -> None:
    audit_root = tmp_path / "audit"
    state_dir = tmp_path / "state"
    summary_dir = audit_root / "traini_slot14_rebenchmark_20260612_010101"
    summary_dir.mkdir(parents=True)
    summary_path = summary_dir / "compare_summary.json"
    _write_summary(summary_path)

    monkeypatch.setattr(slr, "AUDIT_ROOT", audit_root, raising=False)
    monkeypatch.setattr(slr, "STATE_DIR", state_dir, raising=False)
    monkeypatch.setattr(slr, "PIN_STATE_PATH", state_dir / "slot14_pc_andrei_pin_lock.json", raising=False)
    monkeypatch.setattr(
        slr,
        "fetch_model_sizes",
        lambda _pc_url=None: {
            "omi-ft-14b-v20:latest": 16.4,
            "omi-ft-14b-v19:latest": 15.1,
            "omi-ft-14b-v18:latest": 14.8,
            "omi-ft-14b-v16:latest": 14.4,
        },
    )

    result = slr.emit_artifacts(summary_path)

    report_md = Path(result["report_md"])
    report_json = Path(result["report_json"])
    cleanup_json = Path(result["cleanup_json"])
    pin_json = Path(result["pin_json"])

    assert report_md.exists()
    assert report_json.exists()
    assert cleanup_json.exists()
    assert pin_json.exists()

    report_text = report_md.read_text(encoding="utf-8")
    assert "Slot14 multi-model evaluation report" in report_text
    assert "Pin lock note:" in report_text
    assert "omi-ft-14b-v20:latest" in report_text
    assert "omi-ft-14b-v19:latest" in report_text

    cleanup = json.loads(cleanup_json.read_text(encoding="utf-8"))
    assert cleanup["retain_models"] == ["omi-ft-14b-v20:latest", "omi-ft-14b-v19:latest"]
    assert cleanup["delete_candidates"] == ["omi-ft-14b-v18:latest", "omi-ft-14b-v16:latest"]


def test_discover_models_matches_installed_slot14_family(monkeypatch) -> None:
    from ops.learning.compare_14b_chat_models import _discover_models

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "models": [
                        {"name": "omi-ft-14b-v18:latest"},
                        {"name": "omi-ft-14b-v16:latest"},
                        {"name": "qwen25-chat-14-v20-qwen25-thinking:latest"},
                        {"name": "qwen3:14b"},
                        {"name": "axi_omi_sphere:latest"},
                    ]
                }
            ).encode("utf-8")

    def _fake_urlopen(req, timeout=20):
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    models = _discover_models("http://example.invalid")
    assert models == [
        "omi-ft-14b-v16:latest",
        "omi-ft-14b-v18:latest",
        "qwen25-chat-14-v20-qwen25-thinking:latest",
        "qwen3:14b",
    ]
