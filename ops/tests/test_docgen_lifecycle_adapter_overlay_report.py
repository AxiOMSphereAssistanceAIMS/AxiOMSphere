import json

from ops.docgen.universal_overlay.lifecycle_adapter import create_pre_post_overlay_report


def test_create_pre_post_overlay_report(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "scores.json").write_text(json.dumps({"overall_score": 0.95}))

    report = create_pre_post_overlay_report(
        run_dir=run_dir,
        document_type="maintenance_procedure",
    )

    assert report.exists()
    assert "OVERLAY_REPORT_CREATED" in report.read_text()
