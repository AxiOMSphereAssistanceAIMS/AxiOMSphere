from ops.docgen.universal_overlay.document_profile_conformance import (
    apply_profile_formatting,
    validate_document_against_profile,
)
from ops.docgen.universal_overlay.document_type_profile_loader import (
    get_document_generation_profile,
)


def test_profile_formatter_inserts_type_marker() -> None:
    profile = get_document_generation_profile("maintenance_procedure")
    text, result = apply_profile_formatting("# Pump Maintenance\n\nBody", profile)

    assert result["changed"] is True
    assert "Document Type: maintenance_procedure" in text


def test_profile_validator_emits_missing_section_repairs() -> None:
    profile = get_document_generation_profile("maintenance_procedure")
    report = validate_document_against_profile(
        "# Pump Maintenance\n\nDocument Type: maintenance_procedure\n\n"
        "## 1.0 Purpose and Objectives\n\nText.\n",
        profile,
    )

    assert report.status == "REVIEW"
    assert "Procedure Steps" in report.missing_sections
    assert any("Add new Section" in item for item in report.profile_repair_recommendations)


def test_profile_validator_passes_complete_minimal_policy() -> None:
    profile = get_document_generation_profile("policy_framework")
    body = "\n".join(
        ["# Policy", "Document Type: policy_framework"]
        + [
            f"## {index}.0 {section}\nText with controlled content."
            for index, section in enumerate(profile.required_sections, start=1)
        ]
    )

    report = validate_document_against_profile(body, profile)

    assert report.passed
    assert report.profile_repair_recommendations == []


def test_profile_validator_does_not_forbid_api_codes_in_policy_profile() -> None:
    profile = get_document_generation_profile("policy_framework")
    report = validate_document_against_profile(
        "# Report\n\n## 1.0 Executive Summary\nAPI 580 is required.",
        profile,
    )

    assert report.forbidden_references == []
    assert report.status == "REVIEW"


def test_profile_validator_ignores_unlisted_reference_in_other_profile() -> None:
    profile = get_document_generation_profile("technical_report")
    report = validate_document_against_profile(
        "# Report\n\n## 1.0 Executive Summary\nAPI 580 is required.",
        profile,
    )

    assert report.forbidden_references == []
