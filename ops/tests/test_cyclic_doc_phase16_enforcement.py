from types import SimpleNamespace

from ops.cyclic_doc_generation_pipeline import (
    _learning_pair_export_decision,
)
from ops.docgen.universal_overlay.enforcement_contracts import (
    EnforcementContext,
    GateResult,
)
from ops.docgen.universal_overlay.profile_binding_gate import (
    validate_generated_type,
    validate_reference_aware_profile_binding,
    validation_document_type_for,
)
from ops.docgen.universal_overlay.reference_binding_gate import (
    validate_reference_binding,
)


def _pass_gate(name: str) -> GateResult:
    return GateResult(gate_name=name, status="PASS")


def test_reference_aware_bindings_use_real_validator_aliases():
    assert validation_document_type_for("maintenance_procedure") == (
        "operational_manual"
    )
    assert validation_document_type_for("policy_framework") == "policy"


def test_maintenance_reference_aware_profile_passes():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="maintenance_procedure",
        archetype_id="maintenance_management",
        section_contract_count=17,
    )
    assert gate.status == "PASS"


def test_policy_reference_aware_profile_passes_asset_integrity_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="policy_framework",
        archetype_id="asset_integrity_framework",
        section_contract_count=42,
    )
    assert gate.status == "PASS"


def test_reference_aware_profile_blocks_wrong_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="policy_framework",
        archetype_id="technical_report",
        section_contract_count=10,
    )
    assert gate.status == "FAIL"
    assert gate.blocker_code == "REFERENCE_AWARE_ARCHETYPE_MISMATCH"


def test_risk_assessment_reference_aware_profile_passes_technical_report_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="risk_assessment",
        archetype_id="technical_report",
        section_contract_count=12,
    )
    assert gate.status == "PASS"
    assert gate.evidence["validation_document_type"] == "risk_assessment"


def test_inspection_report_reference_aware_profile_passes_technical_report_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="inspection_report",
        archetype_id="technical_report",
        section_contract_count=11,
    )
    assert gate.status == "PASS"
    assert gate.evidence["validation_document_type"] == "inspection_report"


def test_design_document_reference_aware_profile_passes_design_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="design_document",
        archetype_id="design_document",
        section_contract_count=10,
    )
    assert gate.status == "PASS"
    assert gate.evidence["validation_document_type"] == "design_document"


def test_design_document_generated_type_detection_passes_design_markers():
    gate = validate_generated_type(
        SimpleNamespace(
            requested_document_type="design_document",
            detected_document_type=None,
            generated_document_text=(
                "Design Document\n"
                "Architecture and interface overview with design rationale."
            ),
        )
    )
    assert gate.status == "PASS"


def test_requirements_specification_reference_aware_profile_passes_design_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="requirements_specification",
        archetype_id="requirements_specification",
        section_contract_count=10,
    )
    assert gate.status == "PASS"
    assert gate.evidence["validation_document_type"] == "requirements_specification"


def test_preservation_strategy_reference_aware_profile_passes_preservation_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="preservation_strategy",
        archetype_id="preservation_strategy",
        section_contract_count=9,
    )
    assert gate.status == "PASS"
    assert gate.evidence["validation_document_type"] == "preservation_strategy"


def test_method_statement_reference_aware_profile_passes_method_statement_archetype():
    gate = validate_reference_aware_profile_binding(
        requested_document_type="method_statement",
        archetype_id="method_statement",
        section_contract_count=9,
    )
    assert gate.status == "PASS"
    assert gate.evidence["validation_document_type"] == "method_statement"


def test_reference_binding_blocks_empty_extracted_content():
    gate = validate_reference_binding(
        EnforcementContext(
            requested_document_type="maintenance_procedure",
            reference_binding={
                "references": ["/tmp/reference.docx"],
                "path_exists": True,
                "content_chars": 0,
            },
        )
    )
    assert gate.status == "FAIL"
    assert gate.blocker_code == "REFERENCE_CONTENT_UNAVAILABLE"


def test_learning_pair_export_defaults_to_quarantine():
    allowed, failures = _learning_pair_export_decision(
        export_requested=False,
        hard_gate_allowed=True,
        hard_gate_failures=[],
        preflight_gates=[
            _pass_gate("profile"),
            _pass_gate("reference"),
            _pass_gate("judge"),
        ],
        generated_type_gate=_pass_gate("generated_type"),
    )
    assert allowed is False
    assert failures == ["learning_pair_export_not_requested"]


def test_learning_pair_export_requires_all_gates():
    allowed, failures = _learning_pair_export_decision(
        export_requested=True,
        hard_gate_allowed=False,
        hard_gate_failures=["hard_gate=FAIL"],
        preflight_gates=[_pass_gate("profile")],
        generated_type_gate=_pass_gate("generated_type"),
    )
    assert allowed is False
    assert failures == ["hard_gate=FAIL"]
