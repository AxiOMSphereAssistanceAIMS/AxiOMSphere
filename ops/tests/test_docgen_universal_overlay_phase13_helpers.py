import json

from ops.docgen.universal_overlay.phase13_compare_existing_vs_overlay import (
    compare_existing_vs_overlay,
)
from ops.docgen.universal_overlay.phase13_detect_run_dir import (
    detect_latest_run_dir,
)
from ops.docgen.universal_overlay.phase13_hash_run_dir import hash_run_dir


def test_phase13_hash_run_dir_ignores_overlay(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "scores.json").write_text("{}", encoding="utf-8")
    overlay = run_dir / "universal_overlay"
    overlay.mkdir()
    (overlay / "overlay_report.json").write_text("{}", encoding="utf-8")

    out = hash_run_dir(run_dir, tmp_path / "hashes.json")
    data = json.loads(out.read_text(encoding="utf-8"))

    assert "scores.json" in data["hashes"]
    assert "universal_overlay/overlay_report.json" not in data["hashes"]


def test_phase13_detect_run_dir_prefers_newest_marked_directory(tmp_path):
    older = tmp_path / "older_docgen_run"
    newer = tmp_path / "newer_docgen_run"
    older.mkdir()
    newer.mkdir()
    (older / "baseline_eval.json").write_text("{}", encoding="utf-8")
    (newer / "baseline_eval.json").write_text("{}", encoding="utf-8")
    newer_timestamp = (older / "baseline_eval.json").stat().st_mtime + 10
    (newer / "baseline_eval.json").touch()
    import os

    os.utime(newer / "baseline_eval.json", (newer_timestamp, newer_timestamp))

    result = detect_latest_run_dir("maintenance_procedure", roots=[tmp_path])

    assert result["best"]["path"] == str(newer)


def test_phase13_compare_existing_vs_overlay(tmp_path):
    run_dir = tmp_path / "run"
    overlay = run_dir / "universal_overlay"
    overlay.mkdir(parents=True)

    (run_dir / "baseline_eval.json").write_text(
        json.dumps({"overall_score": 0.7}),
        encoding="utf-8",
    )
    (run_dir / "benchmark_comparison.json").write_text(
        json.dumps({"quality_ratio": 0.9}),
        encoding="utf-8",
    )
    (run_dir / "auditor_result.json").write_text(
        json.dumps(
            {
                "overall_score": 0.5,
                "provider": "mock",
                "degraded": True,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "teacher_audit.json").write_text(
        json.dumps({"document_type": "technical_report"}),
        encoding="utf-8",
    )
    (overlay / "overlay_report.json").write_text(
        json.dumps({"status": "OVERLAY_READ_ONLY_REPORT_CREATED"}),
        encoding="utf-8",
    )
    (overlay / "normalized_evidence.json").write_text(
        json.dumps(
            {
                "scores": {"coverage_score": 0.7},
                "failures": {"failures": []},
            }
        ),
        encoding="utf-8",
    )
    (overlay / "decision_summary.json").write_text(
        json.dumps(
            {
                "weakest_dimension": "coverage",
                "repair_decision_preview": {
                    "repair_mode": "targeted_section_repair"
                },
                "skill_candidates": [],
                "branch_candidates": [],
                "training_candidates": [],
            }
        ),
        encoding="utf-8",
    )

    out_json, out_md = compare_existing_vs_overlay(
        run_dir,
        tmp_path / "comparison.json",
        tmp_path / "comparison.md",
    )
    data = json.loads(out_json.read_text(encoding="utf-8"))

    assert data["status"] == "COMPARISON_CREATED"
    assert data["phase_13_decision"] == "READ_ONLY_OBSERVATION_ONLY"
    assert data["architecture_observation"]["document_type_controls_generation"] is False
    assert data["architecture_observation"]["benchmark_auditor_score_delta"] == 0.4
    assert data["architecture_observation"]["reference_binding_present"] is False
    assert out_md.exists()
