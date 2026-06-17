from ops.docgen.universal_overlay.lifecycle_adapter import (
    UniversalLoopRequest,
    planned_bindings,
)


def test_overlay_request_contract():
    request = UniversalLoopRequest(
        document_type="maintenance_procedure",
        request_text="Create procedure",
    )

    assert request.document_type == "maintenance_procedure"
    assert request.target_quality == 0.98
    assert request.dry_run is True


def test_planned_bindings_include_existing_modules():
    names = {binding.name for binding in planned_bindings()}

    assert "quality_cycle_runner" in names
    assert "repair_loop_policy" in names
    assert "validation_profile_loader" in names
