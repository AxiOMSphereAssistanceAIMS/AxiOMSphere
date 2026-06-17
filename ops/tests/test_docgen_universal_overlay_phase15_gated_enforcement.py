import json
from pathlib import Path
from unittest.mock import patch

from ops.docgen.universal_overlay.enforcement_contracts import (
    EnforcementContext,
)
from ops.docgen.universal_overlay.phase15_gated_runner import (
    execute_gated_command,
)
from ops.docgen.universal_overlay.profile_binding_gate import (
    validate_generated_type,
    validate_profile_binding,
)
from ops.docgen.universal_overlay.real_judge_gate import (
    validate_real_judge_path,
)
from ops.docgen.universal_overlay.reference_binding_gate import (
    validate_reference_binding,
)
from ops.docgen.universal_overlay.training_promotion_gate import (
    decide_training_or_promotion_allowed,
)
from ops.docgen.quality_iteration_engine import QualityIterationEngine


def _passing_context() -> EnforcementContext:
    return EnforcementContext(
        requested_document_type="policy_framework",
        profile={"document_type": "policy_framework"},
        validation_profile={"document_type": "policy_framework"},
        generation_context={"document_type": "policy_framework"},
        reference_binding={"references": ["OEM manual", "ADNOC standard"]},
        judge_context={
            "provider": "aws_bedrock",
            "bedrock_invoked": True,
            "model_id": "anthropic.claude-opus-4-6",
        },
        allow_review_only=False,
    )


def test_profile_binding_passes_when_type_present():
    assert validate_profile_binding(_passing_context()).status == "PASS"


def test_profile_binding_blocks_missing_profile_type():
    context = EnforcementContext(
        requested_document_type="policy_framework",
        profile={"document_type": "technical_report"},
        validation_profile={"document_type": "policy_framework"},
        generation_context={"document_type": "policy_framework"},
    )
    result = validate_profile_binding(context)
    assert result.status == "FAIL"
    assert result.blocker_code == "PROFILE_BINDING_MISSING"


def test_profile_binding_blocks_empty_profile():
    context = EnforcementContext(
        requested_document_type="maintenance_procedure",
        profile={},
        validation_profile={},
        generation_context={"document_type": "maintenance_procedure"},
    )
    assert validate_profile_binding(context).blocker_code == "PROFILE_BINDING_MISSING"


def test_profile_binding_blocks_unsupported_backend_type():
    context = EnforcementContext(
        requested_document_type="policy_framework",
        profile={"document_type": "policy_framework"},
        validation_profile={"document_type": "policy_framework"},
        generation_context={
            "document_type": "policy_framework",
            "backend_supported_document_types": ["technical_report"],
        },
    )
    result = validate_profile_binding(context)
    assert result.status == "FAIL"
    assert result.blocker_code == "GENERATOR_DOCUMENT_TYPE_UNSUPPORTED"


def test_generated_type_blocks_type_drift():
    context = EnforcementContext(
        requested_document_type="policy_framework",
        generated_document_text=(
            "# Technical Report\nExecutive summary, findings, analysis, "
            "and recommendations."
        ),
    )
    result = validate_generated_type(context)
    assert result.status == "FAIL"
    assert result.blocker_code == "TYPE_DRIFT_BLOCKED"


def test_generated_type_accepts_first_line_machine_readable_type():
    context = EnforcementContext(
        requested_document_type="maintenance_procedure",
        generated_document_text=(
            "maintenance_procedure\n\n"
            "# Preventive Maintenance Strategy Procedure\n\n"
            "## 1.0 Purpose and Objectives\n"
        ),
    )

    result = validate_generated_type(context)

    assert result.status == "PASS"
    assert result.evidence["detection_source"] == (
        "explicit_document_type_metadata"
    )


def test_generated_type_prefers_explicit_metadata_over_generic_report_terms():
    context = EnforcementContext(
        requested_document_type="maintenance_procedure",
        generated_document_text=(
            "# Preventive Maintenance Strategy Procedure\n\n"
            "**Document Type:** maintenance_procedure\n\n"
            "## 1.0 Purpose and Objectives\n"
            "The failure analysis produces findings and recommendations.\n"
            "## 8.0 Work Preparation and Execution\n"
        ),
    )
    result = validate_generated_type(context)
    assert result.status == "PASS"
    assert result.evidence["detection_source"] == (
        "explicit_document_type_metadata"
    )


def test_generated_type_blocks_conflicting_explicit_metadata():
    context = EnforcementContext(
        requested_document_type="policy_framework",
        generated_document_text=(
            "# Asset Integrity Policy\n"
            "**Document Type:** technical_report\n"
        ),
    )
    result = validate_generated_type(context)
    assert result.status == "FAIL"
    assert result.blocker_code == "TYPE_DRIFT_BLOCKED"


def test_reference_binding_blocks_absent_refs():
    context = EnforcementContext(
        requested_document_type="policy_framework",
        reference_binding={},
    )
    result = validate_reference_binding(context)
    assert result.status == "FAIL"
    assert result.blocker_code == "REFERENCE_BINDING_ABSENT"


def test_reference_binding_blocks_forbidden_refs():
    context = EnforcementContext(
        requested_document_type="maintenance_procedure",
        reference_binding={
            "references": ["API 580"],
            "forbidden_references": ["API 580"],
        },
    )
    result = validate_reference_binding(context)
    assert result.status == "FAIL"
    assert result.blocker_code == "FORBIDDEN_REFERENCES_BLOCKED"


def test_reference_binding_passes_bound_refs():
    context = EnforcementContext(
        requested_document_type="maintenance_procedure",
        reference_binding={"references": ["OEM manual", "ADNOC standard"]},
    )
    assert validate_reference_binding(context).status == "PASS"


def test_real_judge_blocks_mock_without_real():
    context = EnforcementContext(
        requested_document_type="policy_framework",
        judge_context={"provider": "mock", "status": "degraded"},
    )
    result = validate_real_judge_path(context)
    assert result.status == "FAIL"
    assert result.blocker_code == "MOCK_OR_DEGRADED_JUDGE_BLOCKED"


def test_real_judge_passes_bedrock_claude():
    assert validate_real_judge_path(_passing_context()).status == "PASS"


def test_training_promotion_gate_blocks_failed_gate():
    gate = validate_reference_binding(
        EnforcementContext(
            requested_document_type="policy_framework",
            reference_binding={},
        )
    )
    result = decide_training_or_promotion_allowed([gate])
    assert result.status == "FAIL"
    assert result.blocker_code == "TRAINING_PROMOTION_BLOCKED"


def test_gated_runner_does_not_execute_command_when_blocked(tmp_path):
    marker = tmp_path / "executed"
    context = EnforcementContext(
        requested_document_type="policy_framework",
        profile={"document_type": "technical_report"},
        validation_profile={"document_type": "policy_framework"},
        generation_context={"document_type": "policy_framework"},
        reference_binding={"references": ["OEM manual"]},
        judge_context={
            "provider": "aws_bedrock",
            "model_id": "anthropic.claude",
        },
    )
    rc, payload = execute_gated_command(
        context=context,
        command=["touch", str(marker)],
        output_dir=tmp_path / "out",
    )
    assert rc == 73
    assert payload["command_executed"] is False
    assert not marker.exists()
    blocked = json.loads((tmp_path / "out" / "blocked.json").read_text())
    assert blocked["status"] == "PHASE15_GATED_RUN_BLOCKED"


@patch("ops.docgen.quality_iteration_engine.run_vertical_slice")
def test_engine_blocks_policy_framework_before_generation(mock_run, tmp_path):
    engine = QualityIterationEngine(workspace_dir=tmp_path, max_iterations=1)

    result = engine.run("policy_framework", "Asset integrity policy")

    assert result["status"] == "DOCGEN_QUALITY_LOOP_BLOCKED"
    assert result["iterations_count"] == 0
    mock_run.assert_not_called()
    state = json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))
    assert "PROFILE_BINDING_MISSING" in state["errors"][0]


@patch("ops.docgen.quality_iteration_engine.run_vertical_slice")
def test_engine_blocks_maintenance_procedure_before_generation(
    mock_run,
    tmp_path,
):
    engine = QualityIterationEngine(workspace_dir=tmp_path, max_iterations=1)

    result = engine.run("maintenance_procedure", "Centrifugal pump PM")

    assert result["status"] == "DOCGEN_QUALITY_LOOP_BLOCKED"
    assert result["iterations_count"] == 0
    mock_run.assert_not_called()
