import json
from dataclasses import dataclass

import pytest

from ops.docgen.universal_overlay.evidence_normalizer import normalize_run_evidence
from ops.docgen.universal_overlay.lifecycle_adapter import run_backend_with_overlay


@dataclass
class _Result:
    score: float


def _fake_snapshot(path):
    path.write_text("{}", encoding="utf-8")
    return path


def test_normalize_run_evidence_collects_cycles(tmp_path):
    (tmp_path / "metrics.json").write_text(
        json.dumps({"overall_score": 0.5}),
        encoding="utf-8",
    )
    cycle = tmp_path / "cycle_01"
    cycle.mkdir()
    (cycle / "metrics.json").write_text(
        json.dumps({"overall_score": 0.8}),
        encoding="utf-8",
    )

    result = normalize_run_evidence(tmp_path)

    assert result["cycle_count"] == 1
    assert result["root"]["scores"]["overall_score"] == 0.5
    assert result["cycles"][0]["scores"]["overall_score"] == 0.8


def test_backend_wrapper_saves_serializable_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ops.docgen.universal_overlay.lifecycle_adapter.capture_model_runtime_snapshot",
        _fake_snapshot,
    )

    result = run_backend_with_overlay(
        backend=lambda output_dir: _Result(score=0.98),
        backend_kwargs={"output_dir": tmp_path},
        output_dir=tmp_path,
        document_type="maintenance_procedure",
    )

    assert result.score == 0.98
    saved = json.loads(
        (tmp_path / "universal_overlay" / "backend_result.json").read_text()
    )
    assert saved["status"] == "BACKEND_COMPLETED"
    assert saved["result"]["score"] == 0.98
    assert saved["self_improvement_handoff"]
    assert (
        tmp_path
        / "universal_overlay"
        / "self_improvement_readiness.json"
    ).exists()


def test_backend_wrapper_reraises_original_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ops.docgen.universal_overlay.lifecycle_adapter.capture_model_runtime_snapshot",
        _fake_snapshot,
    )

    def failing_backend(**_kwargs):
        raise ValueError("backend failed")

    with pytest.raises(ValueError, match="backend failed"):
        run_backend_with_overlay(
            backend=failing_backend,
            backend_kwargs={},
            output_dir=tmp_path,
            document_type="policy_framework",
        )

    saved = json.loads(
        (tmp_path / "universal_overlay" / "backend_result.json").read_text()
    )
    assert saved["status"] == "BACKEND_FAILED"
