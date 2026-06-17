import json

from ops.docgen.universal_overlay import lifecycle_adapter


def _mock_snapshot(monkeypatch):
    def capture(output_path):
        output_path.write_text(
            json.dumps({"captured_at": "test"}),
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr(
        lifecycle_adapter,
        "capture_model_runtime_snapshot",
        capture,
    )


def test_read_only_overlay_report_writes_overlay_files(tmp_path, monkeypatch):
    _mock_snapshot(monkeypatch)
    run_dir = tmp_path / "existing_run"
    run_dir.mkdir()

    original = run_dir / "scores.json"
    original.write_text(
        json.dumps(
            {
                "dimension_scores": {
                    "structure": 1.0,
                    "coverage": 0.7,
                    "standards": 0.8,
                }
            }
        ),
        encoding="utf-8",
    )
    before = original.read_bytes()

    report = lifecycle_adapter.create_read_only_overlay_report(
        run_dir=run_dir,
        document_type="maintenance_procedure",
    )

    assert report.exists()
    assert before == original.read_bytes()

    overlay_dir = run_dir / "universal_overlay"
    assert sorted(path.name for path in overlay_dir.iterdir()) == [
        "decision_summary.json",
        "model_runtime_snapshot.json",
        "normalized_evidence.json",
        "overlay_report.json",
    ]

    decision = json.loads(
        (overlay_dir / "decision_summary.json").read_text(encoding="utf-8")
    )
    assert decision["weakest_dimension"] == "coverage"
    assert decision["advisory_only"] is True


def test_read_only_overlay_report_status(tmp_path, monkeypatch):
    _mock_snapshot(monkeypatch)
    run_dir = tmp_path / "existing_run"
    run_dir.mkdir()
    (run_dir / "metrics.json").write_text(
        json.dumps({"coverage_score": 0.6}),
        encoding="utf-8",
    )

    report = lifecycle_adapter.create_read_only_overlay_report(
        run_dir=run_dir,
        document_type="maintenance_procedure",
    )
    data = json.loads(report.read_text(encoding="utf-8"))

    assert data["status"] == "OVERLAY_READ_ONLY_REPORT_CREATED"
    assert data["production_behavior_changed"] is False


def test_read_only_overlay_report_rejects_missing_run_dir(tmp_path):
    missing = tmp_path / "missing"

    try:
        lifecycle_adapter.create_read_only_overlay_report(
            run_dir=missing,
            document_type="maintenance_procedure",
        )
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing run directory was accepted")
