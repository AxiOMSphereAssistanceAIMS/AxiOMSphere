from __future__ import annotations

from ops.docagent.docx_writer import markdown_to_docx, verify_docx_quality


def test_docx_writer_falls_back_when_template_styles_are_missing(tmp_path) -> None:
    output = tmp_path / "document.docx"
    markdown = """# Test Document

## 1.0 Scope

1. First numbered requirement
2. Second numbered requirement

| Role | Responsibility |
|---|---|
| Owner | Approves the document |
"""

    markdown_to_docx(markdown, output)
    quality = verify_docx_quality(output)

    assert output.is_file()
    assert quality["passed"] is True
