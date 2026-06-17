import json

import pytest

from ops.ft.scripts import run_golden_v4_benchmark_claude_cli_parallel as module


def test_response_checkpoint_round_trip(tmp_path):
    path = tmp_path / "responses.json"
    checkpoint = {
        "model_a": "candidate",
        "model_b": "baseline",
        "cases": {"case_1": {"response_a": "A", "response_b": "B"}},
    }

    module.save_response_checkpoint(path, checkpoint)
    loaded = module.load_response_checkpoint(path, "candidate", "baseline")

    assert loaded["cases"]["case_1"] == {"response_a": "A", "response_b": "B"}
    assert loaded["updated_at"]
    assert not path.with_suffix(".json.tmp").exists()


def test_response_checkpoint_rejects_model_mismatch(tmp_path):
    path = tmp_path / "responses.json"
    path.write_text(json.dumps({
        "model_a": "old-candidate",
        "model_b": "baseline",
        "cases": {},
    }))

    with pytest.raises(RuntimeError, match="model mismatch"):
        module.load_response_checkpoint(path, "new-candidate", "baseline")


def test_ollama_retries_and_unloads_between_attempts(monkeypatch):
    calls = []
    unloads = []

    def fake_generate(payload, timeout):
        calls.append((payload, timeout))
        if len(calls) == 1:
            raise TimeoutError("slow")
        return {"response": "recovered"}

    monkeypatch.setattr(module, "_ollama_generate", fake_generate)
    monkeypatch.setattr(module, "_unload_ollama_model", unloads.append)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module, "OLLAMA_RETRIES", 2)

    result = module.run_ollama_model("model", [{"role": "user", "content": "test"}])

    assert result == "recovered"
    assert unloads == ["model"]
    assert len(calls) == 2
    assert calls[-1][0]["options"]["num_predict"] == module.OLLAMA_NUM_PREDICT
