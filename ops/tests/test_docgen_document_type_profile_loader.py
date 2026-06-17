from ops.docgen.universal_overlay.document_type_profile_loader import (
    get_document_generation_profile,
    infer_document_type_from_task,
    list_profile_document_types,
)
from ops.docgen.universal_overlay.standards_catalog import DOCUMENT_TYPE_STANDARD_MAP
from ops.agents.skills.context_grounded_document_generation import (
    build_generation_context,
    build_section_contract,
    render_generation_prompt,
)


def test_all_standard_mapped_document_types_have_generation_profiles() -> None:
    assert set(DOCUMENT_TYPE_STANDARD_MAP).issubset(set(list_profile_document_types()))


def test_maintenance_profile_is_compiled_contract_not_full_standard_text() -> None:
    profile = get_document_generation_profile("maintenance_procedure")
    contract = profile.generation_contract()

    assert contract["document_type"] == "maintenance_procedure"
    assert "Procedure Steps" in contract["required_sections"]
    assert "ISO 10013:2021" in contract["formation_standards"]
    assert "IEC/IEEE 82079-1:2019" in contract["formation_standards"]
    assert contract["read_full_standards_during_generation"] is False
    assert contract["require_provenance_before_standard_citation"] is True


def test_policy_profile_blocks_technical_report_structure() -> None:
    profile = get_document_generation_profile("policy_framework")

    assert "Governance Model" in profile.required_sections
    assert "technical_report_findings_as_main_structure" in profile.forbidden_structures
    assert profile.generation_contract()["forbidden_references"] == []


def test_inspection_report_profile_includes_governing_discovery_candidate() -> None:
    profile = get_document_generation_profile("inspection_report")

    assert profile.standards.discovery_candidates == ()


def test_preservation_strategy_profile_loads_without_branch_specific_standards() -> None:
    profile = get_document_generation_profile("preservation_strategy")
    contract = profile.generation_contract()

    assert contract["document_type"] == "preservation_strategy"
    assert "Asset Inventory" in contract["required_sections"]
    assert "Preservation Methods" in contract["required_sections"]


def test_method_statement_profile_loads_without_branch_specific_standards() -> None:
    profile = get_document_generation_profile("method_statement")
    contract = profile.generation_contract()

    assert contract["document_type"] == "method_statement"
    assert "Scope of Work" in contract["required_sections"]
    assert "HSE Requirements" in contract["required_sections"]


def test_infer_document_type_prefers_explicit_type() -> None:
    doc_type, scores = infer_document_type_from_task(
        "write maintenance procedure", explicit_document_type="risk_assessment"
    )

    assert doc_type == "risk_assessment"
    assert scores["risk_assessment"] == 999


def test_infer_document_type_from_context() -> None:
    doc_type, scores = infer_document_type_from_task(
        "Prepare a preventive maintenance procedure for centrifugal pumps"
    )

    assert doc_type == "maintenance_procedure"
    assert scores["maintenance_procedure"] > 0


def test_generation_context_uses_compiled_profile_contract() -> None:
    context = build_generation_context(
        topic="Preventive maintenance strategy for centrifugal pumps",
        doc_type="maintenance_procedure",
        task_context="maintenance procedure",
        similar_limit=0,
    )
    sections = build_section_contract(context)
    prompt = render_generation_prompt(context)

    assert context.profile_contract["document_type"] == "maintenance_procedure"
    assert any("Procedure Steps" in section.title for section in sections)
    assert "COMPILED DOCUMENT TYPE PROFILE CONTRACT" in prompt
    assert '"read_full_standards_during_generation": false' in prompt
