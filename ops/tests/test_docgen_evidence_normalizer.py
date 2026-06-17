import json

from ops.docgen.universal_overlay.evidence_normalizer import (
    normalize_cycle_evidence,
    normalize_run_evidence,
)


def test_normalize_cycle_evidence(tmp_path):
    cycle = tmp_path / "cycle_001"
    cycle.mkdir()
    (cycle / "scores.json").write_text(json.dumps({"overall_score": 0.98}))

    result = normalize_cycle_evidence(cycle)

    assert result["exists"] is True
    assert result["scores"]["overall_score"] == 0.98


def test_normalize_run_evidence(tmp_path):
    for name, score in (("cycle_01", 0.7), ("cycle_02", 0.8)):
        cycle = tmp_path / name
        cycle.mkdir()
        (cycle / "metrics.json").write_text(
            json.dumps({"overall_score": score}),
            encoding="utf-8",
        )

    result = normalize_run_evidence(tmp_path)

    assert result["cycle_count"] == 2
    assert [
        item["scores"]["overall_score"] for item in result["cycles"]
    ] == [0.7, 0.8]
