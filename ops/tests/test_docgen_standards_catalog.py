from ops.docgen.universal_overlay.standards_catalog import (
    ACTIVE_DOCUMENT_FORMATION_STANDARDS,
    DOCUMENT_TYPE_STANDARD_MAP,
    FORBIDDEN_REFERENCES_BY_DEFAULT,
    FIRST_BATCH_IMPLEMENTATION_STANDARDS,
    REGISTRATION_TAXONOMY_STANDARDS,
    STANDARD_CATALOG,
    active_document_formation_records,
    assert_document_type_profile,
    assert_no_forbidden_references,
    assert_reference_binding,
    assert_standard_binding,
    discovery_hints_for,
    find_forbidden_references,
    standards_for_document_type,
)


def test_active_document_formation_standards_have_catalog_evidence() -> None:
    records = active_document_formation_records()

    assert [item["identifier"] for item in records] == list(
        ACTIVE_DOCUMENT_FORMATION_STANDARDS
    )
    assert all(item["implementation_status"] == "ACTIVE_GATE" for item in records)
    assert all(item.get("official_url") for item in records)


def test_registration_taxonomy_is_not_a_content_requirement() -> None:
    assert REGISTRATION_TAXONOMY_STANDARDS == ("ISO 55001", "ISO 55002")
    assert "ISO 55001" not in ACTIVE_DOCUMENT_FORMATION_STANDARDS
    assert "ISO 55002" not in ACTIVE_DOCUMENT_FORMATION_STANDARDS


def test_document_type_standards_are_discovery_hints() -> None:
    hints = discovery_hints_for("maintenance_procedure")

    assert "IEC/IEEE 82079-1" in hints
    assert "IEC 61355-1" in hints
    assert "ISO 14224" not in hints


def test_full_requested_universal_first_batch_is_registered() -> None:
    assert FIRST_BATCH_IMPLEMENTATION_STANDARDS == (
        "ISO 9001:2015",
        "ISO 10013:2021",
        "IEC/IEEE 82079-1:2019",
        "IEC 61355-1:2008",
        "IEC 82045-1:2001",
        "ISO 690:2021",
        "ISO 2145:1978",
        "ISO 8601-1:2019",
        "ISO 80000-1:2022",
    )


def test_all_requested_document_types_have_mapping() -> None:
    expected = {
        "policy_framework",
        "maintenance_procedure",
        "operating_instruction",
        "technical_report",
        "inspection_report",
        "test_report",
        "requirements_specification",
        "design_document",
        "user_manual",
        "quality_plan",
        "audit_report",
        "risk_assessment",
        "management_system_manual",
        "preservation_strategy",
        "method_statement",
    }

    assert expected.issubset(DOCUMENT_TYPE_STANDARD_MAP)
    assert "ISO 10013:2021" in standards_for_document_type("method_statement")


def test_catalog_contains_contextual_inspection_standards() -> None:
    assert "ISO 15463:2003" in STANDARD_CATALOG
    assert "API 5CT" in STANDARD_CATALOG


def test_catalog_contains_contextual_design_standards() -> None:
    assert "EN 54" in STANDARD_CATALOG
    assert "EN 13480" in STANDARD_CATALOG


def test_gate_examples_block_expected_failures() -> None:
    assert_standard_binding("maintenance_procedure", ["IEC/IEEE 82079-1:2019"])

    try:
        assert_standard_binding("maintenance_procedure", ["ISO 690:2021"])
    except RuntimeError as exc:
        assert "STANDARD_BINDING_ABSENT" in str(exc)
    else:
        raise AssertionError("standard binding gate should block unrelated binding")

    try:
        assert_document_type_profile("policy_framework", "technical_report")
    except RuntimeError as exc:
        assert "TYPE_DRIFT_BLOCKED" in str(exc)
    else:
        raise AssertionError("document type drift gate should block mismatch")

    try:
        assert_reference_binding("audit_report", [])
    except RuntimeError as exc:
        assert "REFERENCE_BINDING_ABSENT" in str(exc)
    else:
        raise AssertionError("reference binding gate should require references")


def test_forbidden_reference_rule_examples() -> None:
    assert FORBIDDEN_REFERENCES_BY_DEFAULT == frozenset(
        {"API 510", "API 570", "API 580", "API 581"}
    )
    assert find_forbidden_references(["API 580 and API 581"]) == [
        "API 580",
        "API 581",
    ]

    try:
        assert_no_forbidden_references(["API 510"])
    except RuntimeError as exc:
        assert "FORBIDDEN_REFERENCE_BLOCKED" in str(exc)
    else:
        raise AssertionError("forbidden reference rule should block default APIs")
