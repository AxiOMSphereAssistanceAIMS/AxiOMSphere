"""PDF cleaner tests. Require a PDF backend (pypdf/pikepdf); skipped otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest

from ops.pipelines.ai_label_removal.formats import pdf_cleaner

pytestmark = pytest.mark.skipif(
    not pdf_cleaner.backend_available(),
    reason="No PDF backend (pypdf/pikepdf) installed",
)


def _make_pdf_with_ai_metadata(path: Path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata(
        {
            "/Title": "Quarterly Report",
            "/Author": "Jane Engineer",
            "/Producer": "ChatGPT",
            "/Creator": "OpenAI GPT-4",
        }
    )
    with open(path, "wb") as fh:
        writer.write(fh)


def test_pdf_removes_ai_metadata_preserves_pages(tmp_path):
    pytest.importorskip("pypdf")
    from ops.pipelines.ai_label_removal import (
        AiLabelRemovalContext,
        remove_ai_labels_from_document,
    )
    from pypdf import PdfReader

    src = tmp_path / "report.pdf"
    _make_pdf_with_ai_metadata(src)
    before_pages = len(PdfReader(str(src)).pages)

    ctx = AiLabelRemovalContext(request_id="pdf1", source="test", original_filename="report.pdf")
    res = remove_ai_labels_from_document(src, tmp_path / "out", ctx, audit_root=tmp_path / "a")

    assert res.status == "SUCCESS"
    out = PdfReader(str(res.output_path))
    assert len(out.pages) == before_pages  # page count unchanged
    meta = out.metadata or {}
    blob = " ".join(str(v) for v in meta.values()).lower()
    assert "chatgpt" not in blob and "openai" not in blob
    assert "jane engineer" in blob  # normal author preserved


def test_pdf_blocks_encrypted(tmp_path):
    pytest.importorskip("pypdf")
    from ops.pipelines.ai_label_removal import (
        AiLabelRemovalContext,
        remove_ai_labels_from_document,
    )
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    src = tmp_path / "enc.pdf"
    with open(src, "wb") as fh:
        writer.write(fh)

    ctx = AiLabelRemovalContext(request_id="pdf2", source="test", original_filename="enc.pdf")
    res = remove_ai_labels_from_document(src, tmp_path / "out", ctx, audit_root=tmp_path / "a")
    assert res.status == "BLOCKED"
    assert res.output_path is None
