from __future__ import annotations

from ops.cyclic_skills import _is_stub, validate_structure


def test_validate_structure_includes_level_four_subsections() -> None:
    doc = """## Table of Contents
1.0 INTRODUCTION
1.1 Definitions
1.2 Acronyms

### 1.0 INTRODUCTION
This section contains substantive introductory content for the document.

#### 1.1 Definitions
This section defines the key terms used throughout the management framework.

#### 1.2 Acronyms
This section lists the abbreviations used throughout the management framework.
"""
    report = validate_structure(doc)

    assert report.completeness_ratio == 1.0
    assert report.empty_sections == []
    assert report.stub_sections == []
    assert report.passed is True


def test_empty_container_heading_is_satisfied_by_populated_children() -> None:
    doc = """## Table of Contents
5.0 DEFINITIONS AND ACRONYMS
5.1 Definitions
5.2 Acronyms

### 5.0 DEFINITIONS AND ACRONYMS

#### 5.1 Definitions
This child section contains substantive definitions for controlled terminology.

#### 5.2 Acronyms
This child section contains substantive acronym definitions for the document.
"""
    report = validate_structure(doc)

    assert report.completeness_ratio == 1.0
    assert report.stub_sections == []


# ---------------------------------------------------------------------------
# Regression: blank lines inside filled sections must NOT be classified as stubs
# Bug: r"^\s*$" with re.MULTILINE + .search() matched any blank line in body.
# ---------------------------------------------------------------------------


def test_is_stub_false_for_body_with_blank_lines() -> None:
    """A body with blank lines between paragraphs must not be a stub."""
    body = (
        "This section describes asset inspection procedures.\n"
        "\n"
        "Blank lines separate paragraphs in Markdown documents.\n"
        "\n"
        "The procedure must be followed at all times."
    )
    assert _is_stub(body) is False


def test_is_stub_false_for_markdown_table_with_blank_lines() -> None:
    """A Markdown table body (with surrounding blank lines) must not be a stub."""
    body = (
        "\n"
        "| Parameter | Value |\n"
        "|-----------|-------|\n"
        "| Frequency | Annual |\n"
        "| Owner     | Engineering |\n"
        "\n"
    )
    assert _is_stub(body) is False


def test_is_stub_true_for_empty_body() -> None:
    assert _is_stub("") is True


def test_is_stub_true_for_whitespace_only_body() -> None:
    assert _is_stub("   \n\n   ") is True


def test_is_stub_true_for_tbd() -> None:
    assert _is_stub("TBD") is True


def test_is_stub_true_for_refer_to_placeholder() -> None:
    assert _is_stub("(Refer to ISO 55001)") is True


def test_validate_structure_section_with_blank_lines_not_stub() -> None:
    """Regression: sections with internal blank lines must not appear in stub_sections."""
    doc = """## Table of Contents
2.0 INSPECTION PROCEDURES

### 2.0 INSPECTION PROCEDURES

This section describes the inspection procedures in detail.

The following parameters apply:

| Parameter | Value    |
|-----------|----------|
| Frequency | Annual   |
| Owner     | Engineer |

Inspections must be documented within 48 hours of completion.
"""
    report = validate_structure(doc)
    assert "2.0 INSPECTION PROCEDURES" not in report.stub_sections
