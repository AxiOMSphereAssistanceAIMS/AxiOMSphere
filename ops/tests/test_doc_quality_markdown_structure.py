from __future__ import annotations

from ops.docagent.doc_quality_eval import _check_structure


def test_quality_structure_accepts_markdown_numbered_headings() -> None:
    doc = """# Corporate Standard

## Document Control
**Document Number:** AIM-001
**Approved By:** COO

### Revision Control
| Issue | Description of Change | Date |
|---|---|---|
| 01 | Initial issue | 2026-06-06 |

### Table of Contents
1.0 Introduction
2.0 Purpose and Objective
3.0 Scope
5.0 Definitions and Acronyms
6.0 References
10.0 Appendices

### 2.0 Purpose and Objective
The purpose is to establish asset integrity requirements.

### 3.0 Scope
The scope covers all operated assets.

### 5.0 Definitions and Acronyms
Definitions and acronyms are controlled here.

### 6.0 References
ISO 55001 is an applicable reference.

### 10.0 Appendices
Supporting material is maintained here.
"""
    score, details = _check_structure(doc)

    assert score == 1.0
    assert all(item["found"] for item in details)
