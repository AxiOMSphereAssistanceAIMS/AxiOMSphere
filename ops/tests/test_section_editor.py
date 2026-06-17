from __future__ import annotations

import json

import pytest

from ops.agents.skills import section_editor


DOC = """# Asset Integrity Framework

## 1.0 Scope
Existing scope requirements and asset boundaries are defined here.

## 2.0 Risk Management
Existing risk controls and assessment requirements are defined here.
"""


def test_strict_response_rejects_markdown_wrapper() -> None:
    wrapped = """```json
{"section_id":"1.0","revised_body":"body","applied":["REC-001"],"skipped":[]}
```"""
    with pytest.raises(json.JSONDecodeError):
        section_editor._parse_section_response(
            wrapped,
            expected_section_id="1.0",
            expected_rec_ids={"REC-001"},
        )


def test_unknown_section_is_unresolved_without_fuzzy_routing(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("model must not be called for unresolved targets")

    monkeypatch.setattr(section_editor, "_ollama", fail_if_called)
    result = section_editor.apply_section_edits(
        DOC,
        ["Section 9.9: Add corrosion monitoring requirements"],
    )

    assert result["improved_doc"] == DOC
    assert result["changes_applied"] == []
    assert result["unresolved_recs"] == [
        "Section 9.9: Add corrosion monitoring requirements"
    ]


def test_partial_verification_rolls_back_whole_section(monkeypatch) -> None:
    def fake_ollama(prompt: str, timeout: int = 300) -> str:
        return json.dumps(
            {
                "section_id": "1.0",
                "revised_body": (
                    "Existing scope requirements and asset boundaries are "
                    "defined here. Corrosion monitoring requirements added."
                ),
                "applied": ["REC-001"],
                "skipped": ["REC-002"],
            }
        )

    monkeypatch.setattr(section_editor, "_ollama", fake_ollama)
    result = section_editor.apply_section_edits(
        DOC,
        [
            "Section 1.0: Add corrosion monitoring requirements",
            "Section 1.0: Add inspection frequency requirements",
        ],
    )

    assert result["improved_doc"] == DOC
    assert result["changes_applied"] == []
    assert result["section_results"][0]["status"] == "ROLLED_BACK"


def test_multiple_sections_commit_deterministically_from_snapshot(monkeypatch) -> None:
    def fake_ollama(prompt: str, timeout: int = 300) -> str:
        if "Heading: 1.0 Scope" in prompt:
            return json.dumps(
                {
                    "section_id": "1.0",
                    "revised_body": (
                        "Existing scope requirements and asset boundaries are "
                        "defined here. Corrosion monitoring requirements apply."
                    ),
                    "applied": ["REC-001"],
                    "skipped": [],
                }
            )
        return json.dumps(
            {
                "section_id": "2.0",
                "revised_body": (
                    "Existing risk controls and assessment requirements are "
                    "defined here. Criticality matrix requirements apply."
                ),
                "applied": ["REC-002"],
                "skipped": [],
            }
        )

    monkeypatch.setattr(section_editor, "_ollama", fake_ollama)
    result = section_editor.apply_section_edits(
        DOC,
        [
            "Section 1.0: Add corrosion monitoring requirements",
            "Section 2.0: Add criticality matrix requirements",
        ],
        max_workers=2,
    )

    assert result["rolled_back"] is False
    assert result["changes_applied"] == ["REC-001", "REC-002"]
    assert result["verified_recommendations"] == [
        "Section 1.0: Add corrosion monitoring requirements",
        "Section 2.0: Add criticality matrix requirements",
    ]
    assert "Corrosion monitoring requirements apply." in result["improved_doc"]
    assert "Criticality matrix requirements apply." in result["improved_doc"]


def test_heading_injection_triggers_full_rollback(monkeypatch) -> None:
    def fake_ollama(prompt: str, timeout: int = 300) -> str:
        return json.dumps(
            {
                "section_id": "1.0",
                "revised_body": (
                    "Existing scope requirements and asset boundaries are "
                    "defined here. Corrosion monitoring requirements apply.\n\n"
                    "## 99.0 Injected Heading\nUnexpected structure."
                ),
                "applied": ["REC-001"],
                "skipped": [],
            }
        )

    monkeypatch.setattr(section_editor, "_ollama", fake_ollama)
    result = section_editor.apply_section_edits(
        DOC,
        ["Section 1.0: Add corrosion monitoring requirements"],
    )

    assert result["rolled_back"] is True
    assert result["improved_doc"] == DOC
    assert result["changes_applied"] == []


def test_new_section_recommendation_is_pending_global(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("new sections require the separate global pass")

    monkeypatch.setattr(section_editor, "_ollama", fail_if_called)
    result = section_editor.apply_section_edits(
        DOC,
        ["Add new Section 9.0 — Asset Register and Criticality Assessment"],
    )

    assert result["improved_doc"] == DOC
    assert result["global_recs"] == [
        "Add new Section 9.0 — Asset Register and Criticality Assessment"
    ]
    assert result["changes_applied"] == []


def test_new_section_is_generated_and_inserted_by_code(monkeypatch) -> None:
    recommendation = (
        "Add new Section 9.0 — Asset Register and Criticality Assessment"
    )
    body = " ".join(
        ["asset register criticality assessment requirements"] * 25
    )

    def fake_ollama(prompt: str, timeout: int = 300) -> str:
        return json.dumps(
            {
                "section_id": "9.0",
                "body": body,
                "applied": ["REC-001"],
            }
        )

    monkeypatch.setattr(section_editor, "_ollama", fake_ollama)
    result = section_editor.apply_section_edits(DOC, [recommendation])

    assert result["global_recs"] == []
    assert result["rolled_back"] is False
    assert result["changes_applied"] == ["REC-001"]
    assert "## 9.0 Asset Register and Criticality Assessment" in result[
        "improved_doc"
    ]


def test_new_child_section_is_inserted_inside_parent_subtree() -> None:
    doc = """### 8.0 Elements

#### 8.1 Existing Element
Existing substantive content.

### 9.0 Guidance
Existing guidance.
"""
    generated = [
        (
            "8.18",
            "8.18 Element 18: Supplier Management",
            "Substantive supplier management requirements.",
        )
    ]

    improved = section_editor._insert_new_sections(doc, generated)

    assert "#### 8.18 Element 18: Supplier Management" in improved
    assert improved.index("#### 8.18") < improved.index("### 9.0")


def test_numeric_order_normalizer_repairs_late_child_sections() -> None:
    doc = """### 8.0 Elements

#### 8.1 Existing Element
Existing content.

### 9.0 Guidance
Guidance content.

## 8.18 Supplier Management
Supplier content.

## 9.1 Compliance Matrix
Matrix content.
"""

    normalized, changed = section_editor._normalize_numeric_section_order(doc)

    assert changed is True
    assert normalized.index("#### 8.18") < normalized.index("### 9.0")
    assert normalized.index("#### 9.1") > normalized.index("### 9.0")


def test_numeric_order_does_not_override_numbering_for_appendices() -> None:
    doc = """### 9.0 Guidance
Guidance.

### 10.0 APPENDICES
End of Document.

### 11.0 Emergency Response Integration
Emergency response content.

### 13.0 KPI Register
KPI content.
"""

    normalized, changed = section_editor._normalize_numeric_section_order(doc)

    assert changed is True
    assert normalized.index("### 10.0 APPENDICES") < normalized.index("### 11.0")
    assert normalized.index("### 11.0") < normalized.index("### 13.0")


def test_missing_declared_toc_section_becomes_new_section(monkeypatch) -> None:
    doc = """## Table of Contents
1.0 Scope
1.1 Integrity Policy

## 1.0 Scope
Existing scope requirements and asset boundaries are defined here.
"""
    body = " ".join(["integrity policy management commitment review"] * 25)

    def fake_ollama(prompt: str, timeout: int = 300) -> str:
        return json.dumps(
            {
                "section_id": "1.1",
                "body": body,
                "applied": ["REC-001"],
            }
        )

    monkeypatch.setattr(section_editor, "_ollama", fake_ollama)
    result = section_editor.apply_section_edits(
        doc,
        ["Section 1.1: Add integrity policy management commitment review"],
    )

    assert result["unresolved_recs"] == []
    assert result["global_recs"] == []
    assert result["changes_applied"] == ["REC-001"]
    assert "## 1.1 Integrity Policy" in result["improved_doc"]


def test_add_element_targets_new_element_not_parent_section() -> None:
    rec = section_editor.normalize_rec(
        "REC-001",
        "Section 8.0: Add Element 8.18 Supplier and Contractor Management",
    )

    assert rec.target == "8.18"
    assert rec.operation == "NEW_SECTION"


def test_new_section_heading_excludes_requirement_detail() -> None:
    rec = section_editor.normalize_rec(
        "REC-001",
        "Add new Section 8.18 Element 18: Supplier Management — "
        "defines vendor qualification requirements",
    )

    assert section_editor._new_section_heading(rec, "8.18") == (
        "8.18 Element 18: Supplier Management"
    )


def test_code_owned_section_rename_updates_body_heading_and_toc(
    monkeypatch,
) -> None:
    doc = """## Table of Contents
8.17 Element 17: Performance Monitoring and Audit

#### 8.17 Element 17: Performance Monitoring and Audit
Existing performance monitoring content is present in this section.
"""

    def fake_ollama(prompt: str, timeout: int = 300) -> str:
        return json.dumps(
            {
                "section_id": "8.17",
                "revised_body": (
                    "Emergency response and emergency recovery requirements "
                    "define activation, repair, and verification controls."
                ),
                "applied": ["REC-001"],
                "skipped": [],
            }
        )

    monkeypatch.setattr(section_editor, "_ollama", fake_ollama)
    result = section_editor.apply_section_edits(
        doc,
        [
            "Section 8.17: Correct the element title to "
            "'Emergency Response and Emergency Recovery and Repairs'"
        ],
    )

    expected = (
        "8.17 Element 17: Emergency Response and Emergency Recovery and Repairs"
    )
    assert result["changes_applied"] == ["REC-001"]
    assert f"#### {expected}" in result["improved_doc"]
    assert expected in result["improved_doc"].split(
        "####",
        maxsplit=1,
    )[0]


def test_new_element_mention_does_not_override_explicit_target() -> None:
    rec = section_editor.normalize_rec(
        "REC-001",
        "Section 8.17: Relocate current content to new Element 8.19",
    )

    assert rec.target == "8.17"
    assert rec.operation == "ADD_CONTENT"


def test_toc_recommendation_is_global_even_with_section_numbers() -> None:
    rec = section_editor.normalize_rec(
        "REC-001",
        "TABLE OF CONTENTS: Add Elements 8.18 through 8.23",
    )

    assert rec.target == "GLOBAL"
    assert rec.operation == "GLOBAL"


def test_section_prefixed_toc_recommendation_is_global() -> None:
    rec = section_editor.normalize_rec(
        "REC-001",
        "Section TABLE OF CONTENTS: Add Elements 8.18 through 8.23",
    )

    assert rec.target == "GLOBAL"
    assert rec.operation == "GLOBAL"


def test_distinct_sections_share_one_parallel_snapshot_batch() -> None:
    assert section_editor._can_run_parallel(
        ["3.0", "5.1", "8.17"],
        [],
    ) == [["3.0", "5.1", "8.17"]]


def test_appendix_global_resolves_to_appendices_heading() -> None:
    catalog = section_editor.build_catalog("""## 9.1 Annexure 1
Existing annexure material.

## 10.0 APPENDICES
Existing appendix material.
""")
    rec = section_editor.normalize_rec(
        "REC-001",
        "Appendix B: Add RBI methodology flowchart",
    )

    assert section_editor._resolve_global_target(rec, catalog) == "10.0"


def test_element_decimal_target_is_not_truncated() -> None:
    rec = section_editor.normalize_rec(
        "REC-001",
        "Element 8.15 Anomaly Management: Add API 579 decision tree",
    )
    assert rec.target == "8.15"
