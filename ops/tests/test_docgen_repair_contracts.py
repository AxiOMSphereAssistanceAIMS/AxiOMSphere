from __future__ import annotations

from ops import cyclic_doc_generation_pipeline as pipeline
from ops.agents.skills import section_editor
from ops.agents.skills.context_grounded_document_generation import (
    GenerationContext,
    apply_reference_baseline,
    build_section_contract,
    extract_reference_baseline,
    match_reference_section,
    resolve_document_archetype,
)
from ops.docagent.doc_skills import skill_search
from ops.models.model_registry import CANONICAL_REGISTRY_PATH, registry_path
from ops.agents.skills.document_failure_diagnostics import (
    diagnose_document_failures,
)


REFERENCE = """TABLE OF CONTENTS
1.0 TERMINOLOGY 3
2.0 SOURCE REGISTER 4
3.0 REQUIREMENT CROSSWALK 5
1.0 TERMINOLOGY
Code Description
ABC Alpha Beta Control
XYZ Extended Yield Zone
2.0 SOURCE REGISTER
Reference Title
STD-01 Primary governed source
STD-02 Secondary governed source
3.0 REQUIREMENT CROSSWALK
Source Requirement Target
1 Scope requirement mapped to target A
2 Context requirement mapped to target B
3 Control requirement mapped to target C
"""


def test_model_registry_defaults_to_canonical_ops_registry(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AIMS_MODEL_REGISTRY", raising=False)
    assert registry_path() == CANONICAL_REGISTRY_PATH
    assert pipeline.ModelConfig.SLOT14_SEARCH == "qwen25-chat-14-v19:latest"
    assert pipeline.ModelConfig.SLOT120_REASONING == (
        "qwen36-reasoning-35b-v1:latest"
    )


def test_doc_search_rejects_unsupported_mode() -> None:
    result = skill_search("asset integrity", mode="internet")
    assert result["status"] == "failed"
    assert result["results"] == []
    assert "Unsupported search mode" in result["notes"]


def test_reference_baseline_is_deterministic_and_applied_atomically() -> None:
    baseline = extract_reference_baseline(REFERENCE)
    assert baseline["counts"]["sections"] == 3
    assert baseline["counts"]["structured_blocks"] == 3
    assert any(
        block["role"] == "compliance_matrix"
        for block in baseline["structured_blocks"]
    )

    document = """## 1.0 Terminology

Old terminology.

## 2.0 Source Register

Old sources.

## 3.0 Requirement Crosswalk

Old crosswalk.
"""
    improved, report = apply_reference_baseline(document, baseline)

    assert report["status"] == "APPLIED"
    assert len(report["applied_blocks"]) == 3
    assert "Old terminology." not in improved
    assert "Old sources." not in improved
    assert "Old crosswalk." not in improved
    assert "Alpha Beta Control" in improved


def test_editor_uses_object_json_schema() -> None:
    schema = section_editor._ollama_response_schema(
        '{"section_id":"1.0","revised_body":"...","applied":[],"skipped":[]}'
    )
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "section_id",
        "revised_body",
        "applied",
        "skipped",
    ]


def test_judge_recommendations_require_exact_reference_evidence() -> None:
    evidence = (
        "RACI Responsible, Accountable, Contributor, Informed"
    )
    finding = {
        "recommendations": [
            {
                "text": "Section 8.6: Preserve Contributor in the RACI model",
                "evidence_quote": evidence,
            },
            {
                "text": "Section 8.6: Change Contributor to Consulted",
                "evidence_quote": (
                    "RACI Responsible, Accountable, Consulted, Informed"
                ),
            },
        ]
    }
    accepted, rejected = pipeline._ground_audit_recommendations(
        finding,
        evidence,
    )

    assert accepted == [
        "Section 8.6: Preserve Contributor in the RACI model"
    ]
    assert rejected[0]["reason"] == "evidence_quote_not_in_reference"


def test_standard_reference_register_lists_only_used_evidenced_standards() -> None:
    document, report = pipeline._ensure_standard_reference_register(
        doc_text=(
            "# Pump Maintenance Procedure\n\n"
            "Vibration assessment shall follow API 610."
        ),
        internal_standards=[],
        external_standards={
            "sources": [
                {
                    "source_title": (
                        "API 610 — Centrifugal Pumps for Petroleum, "
                        "Petrochemical and Natural Gas Industries"
                    ),
                    "excerpt": "Requirements for centrifugal pumps.",
                    "source_authority_level": "high",
                },
                {
                    "source_title": "ISO 18436 — Condition monitoring",
                    "excerpt": "Competence requirements.",
                    "source_authority_level": "high",
                },
            ]
        },
        formatting_standards=["ISO 10013:2021"],
        forbidden_references=[],
    )

    assert report["status"] == "PASS"
    assert [item["identifier"] for item in report["used_standards"]] == [
        "API 610",
        "ISO 10013:2021",
    ]
    assert "ISO 18436" not in document
    assert "ISO 55001" not in document
    assert document.rstrip().endswith(
        "| ISO 10013:2021 | Quality management systems — Guidance for "
        "documented information |"
    )


def test_standard_reference_register_blocks_unverified_body_citation() -> None:
    _document, report = pipeline._ensure_standard_reference_register(
        doc_text=(
            "# Pump Maintenance Procedure\n\n"
            "Apply ISO 99999 requirements."
        ),
        internal_standards=[],
        external_standards={"sources": []},
        formatting_standards=["ISO 10013:2021"],
        forbidden_references=[],
    )

    assert report["status"] == "PASS"
    assert report["unverified_citations"] == ["ISO 99999"]
    assert report["fallback_mode"] is True


def test_standard_reference_register_ignores_generic_api_phrase() -> None:
    _document, report = pipeline._ensure_standard_reference_register(
        doc_text=(
            "# Pump Maintenance Procedure\n\n"
            "Applicable API standards shall be selected by context."
        ),
        internal_standards=[],
        external_standards={"sources": []},
        formatting_standards=["ISO 10013:2021"],
        forbidden_references=[],
    )

    assert report["status"] == "PASS"
    assert report["body_citations"] == []
    assert report["unverified_citations"] == []


def test_policy_framework_blocks_unbound_default_api_reference() -> None:
    _document, report = pipeline._ensure_standard_reference_register(
        doc_text=(
            "# Asset Integrity Policy\n\n"
            "Inspection governance shall follow API 580 by default."
        ),
        internal_standards=[],
        external_standards={"sources": []},
        formatting_standards=["ISO 10013:2021"],
        forbidden_references=["API 580"],
        document_type="policy_framework",
    )

    assert report["status"] == "FAIL"
    assert report["document_type"] == "policy_framework"
    assert report["profile_unbound_references"] == ["API 580"]
    assert report["branch_blockers"] == [
        "profile_forbidden_unbound_reference"
    ]


def test_policy_framework_allows_source_bound_api_reference() -> None:
    _document, report = pipeline._ensure_standard_reference_register(
        doc_text=(
            "# Asset Integrity Policy\n\n"
            "Where explicitly required by the source document, API 580 is "
            "listed as a related technical reference."
        ),
        internal_standards=[],
        external_standards={
            "sources": [
                {
                    "source_title": "API 580 — Risk-Based Inspection",
                    "excerpt": "Referenced by the bound source document.",
                    "source_authority_level": "high",
                }
            ]
        },
        formatting_standards=["ISO 10013:2021"],
        forbidden_references=["API 580"],
        document_type="policy_framework",
    )

    assert report["status"] == "PASS"
    assert report["profile_unbound_references"] == []
    assert report["branch_blockers"] == []
    assert [item["identifier"] for item in report["used_standards"]] == [
        "API 580",
        "ISO 10013:2021",
    ]


def test_maintenance_procedure_allows_source_bound_api_reference() -> None:
    _document, report = pipeline._ensure_standard_reference_register(
        doc_text=(
            "# Maintenance Procedure\n\n"
            "Pressure vessel inspection intervals shall consider API 510."
        ),
        internal_standards=["API 510 — Pressure Vessel Inspection Code"],
        external_standards={"sources": []},
        formatting_standards=["ISO 10013:2021"],
        document_type="maintenance_procedure",
        forbidden_references=[],
    )

    assert report["status"] == "PASS"
    assert report["profile_unbound_references"] == []
    assert report["branch_blockers"] == []
    assert [item["identifier"] for item in report["used_standards"]] == [
        "API 510",
        "ISO 10013:2021",
    ]


def test_standard_reference_register_renders_as_final_two_column_docx_table(
    tmp_path,
) -> None:
    from docx import Document

    from ops.docagent.docx_writer import markdown_to_docx

    document, report = pipeline._ensure_standard_reference_register(
        doc_text="# Procedure\n\nUse API 610 for pump requirements.",
        internal_standards=["API 610 — Centrifugal Pumps"],
        external_standards={"sources": []},
        formatting_standards=["ISO 10013:2021"],
        forbidden_references=[],
    )
    output = tmp_path / "standard-register.docx"
    markdown_to_docx(document, output, title="Procedure")

    docx = Document(output)
    final_table = docx.tables[-1]
    rows = [[cell.text for cell in row.cells] for row in final_table.rows]

    assert report["status"] == "PASS"
    assert len(final_table.columns) == 2
    assert rows[0] == ["Standard Number", "Description"]
    assert rows[1][0] == "API 610"
    assert rows[2][0] == "ISO 10013:2021"


def test_failure_diagnostics_classifies_stage_not_document_content() -> None:
    class Structure:
        empty_sections = ["2.0 Empty"]
        stub_sections = ["3.0 Stub"]

    diagnostics = diagnose_document_failures(
        structure_report=Structure(),
        retrieval_result={"standards": [], "provider": "unavailable"},
        baseline_report={"status": "SKIPPED"},
        section_edit_result={
            "section_results": [
                {
                    "section_id": "4.0",
                    "status": "ROLLED_BACK",
                    "reason": "invalid_response: JSON decode",
                }
            ],
            "unresolved_recs": ["Unknown target"],
            "global_recs": [],
        },
    )

    assert diagnostics["cause_counts"] == {
        "EDITOR_INVALID_SCHEMA": 1,
        "EMPTY_SECTION": 1,
        "NO_GOVERNED_SOURCES": 1,
        "NO_SEMANTIC_BASELINE_MATCH": 1,
        "STUB_SECTION": 1,
        "UNRESOLVED_SECTION_TARGET": 1,
    }


def test_maintenance_task_selects_maintenance_archetype() -> None:
    context = GenerationContext(
        topic="Preventive maintenance of centrifugal pumps",
        doc_type="maintenance_plan",
        task_context="Plan equipment servicing and defect control.",
        standards=[],
        reference=None,
        templates=[],
        similar_documents=[],
        provenance=[],
        warnings=[],
    )

    archetype = resolve_document_archetype(context)
    contract = build_section_contract(context)
    titles = [item.title for item in contract]

    assert archetype["archetype_id"] == "maintenance_management"
    assert any("Maintenance Strategy" in title for title in titles)
    assert any("Planning and Scheduling" in title for title in titles)
    assert any("Records and Documented Information" in title for title in titles)
    assert archetype["standards"] == []
    assert archetype["governance"]["active_document_formation_standards"] == [
        "ISO 10013:2021",
        "ISO 2145:1978",
        "ISO 690:2021",
    ]
    assert archetype["governance"]["registration_taxonomy_standards"] == [
        "ISO 55001",
        "ISO 55002",
    ]


def test_reference_matching_uses_heading_semantics_not_section_number() -> None:
    reference = """TABLE OF CONTENTS
1.0 Introduction 2
2.0 Scope and Applicability 3
3.0 Records and Retention 4
1.0 Introduction
Reference introduction.
2.0 Scope and Applicability
Governed scope evidence.
3.0 Records and Retention
Retention evidence.
"""
    matched = match_reference_section(
        reference,
        "1.0 Scope, Assets, and Boundaries",
    )
    assert "Governed scope evidence." in matched
    assert "Reference introduction." not in matched
