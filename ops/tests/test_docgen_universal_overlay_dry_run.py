from ops.docgen.universal_overlay.dry_run import run_overlay_dry_run


def test_overlay_dry_run_writes_result(tmp_path):
    result = run_overlay_dry_run(
        document_type="maintenance_procedure",
        request_text="Create maintenance procedure",
        output_root=tmp_path,
    )

    assert result["status"] == "DRY_RUN_COMPLETE"
    assert result["document_type"] == "maintenance_procedure"
    assert result["snapshot"]
