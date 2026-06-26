from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.docgen.universal_pipeline import standard_markitdown_normalizer as normalizer
from ops.docgen.universal_pipeline import standards_binder
from ops.docsreg.extraction import markitdown_adapter


class _FakeMarkItDown:
    def convert(self, source_path: str):
        return SimpleNamespace(text_content=Path(source_path).read_text(encoding="utf-8"))


def _install_fake_markitdown(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeModule:
        MarkItDown = _FakeMarkItDown
        __version__ = "test"

    monkeypatch.setattr(
        markitdown_adapter.importlib,
        "import_module",
        lambda name: _FakeModule() if name == "markitdown" else pytest.fail(name),
    )
    monkeypatch.setattr(
        markitdown_adapter.importlib_metadata,
        "version",
        lambda name: "test" if name == "markitdown" else pytest.fail(name),
    )


def test_docgen_standard_normalizer_disabled_by_default(tmp_path: Path) -> None:
    standards = {"selected_standards": [{"standard_id": "ISO 55001"}]}

    summary = normalizer.normalize_standards_for_comparison(
        standards,
        tmp_path / "normalized",
        enabled=False,
    )

    assert summary["status"] == "DISABLED"
    assert summary["generation_context_allowed"] is False
    assert summary["entries"] == []


def test_docgen_standard_normalizer_writes_comparison_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_markitdown(monkeypatch)
    source = tmp_path / "ISO_55001.docx"
    source.write_text("# ISO 55001\n\nstandard comparison text " * 40, encoding="utf-8")
    standards = {
        "selected_standards": [
            {
                "standard_id": "ISO 55001",
                "registered_source_path": str(source),
            }
        ]
    }

    summary = normalizer.normalize_standards_for_comparison(
        standards,
        tmp_path / "normalized",
        enabled=True,
    )

    assert summary["status"] == "PASS"
    assert summary["standards_extracted"] == 1
    entry = summary["entries"][0]
    assert entry["generation_context_allowed"] is False
    assert entry["raw_markdown_in_generation_context"] is False
    assert Path(entry["raw_extracted_text_path"]).exists()
    report = Path(entry["extraction_report_path"]).read_text(encoding="utf-8")
    assert '"extractor": "markitdown"' in report
    assert "raw_markdown" not in report


def test_docgen_standard_normalizer_blocks_etalon_source(tmp_path: Path) -> None:
    source = tmp_path / "approved_etalon.docx"
    source.write_text("must not enter generation context", encoding="utf-8")
    standards = {
        "selected_standards": [
            {
                "standard_id": "ETALON-ISO-55001",
                "registered_source_path": str(source),
            }
        ]
    }

    summary = normalizer.normalize_standards_for_comparison(
        standards,
        tmp_path / "normalized",
        enabled=True,
    )

    assert summary["status"] == "WARN"
    assert summary["standards_skipped"] == 1
    assert summary["entries"][0]["status"] == "BLOCKED"
    assert "ETALON" in summary["entries"][0]["reason"]


def test_docgen_standards_binder_preserves_registered_source_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "ISO_55001.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        standards_binder,
        "official_standard_metadata",
        lambda standard_id: {},
    )
    monkeypatch.setattr(
        standards_binder,
        "list_registered_standard_records",
        lambda: [
            {
                "standard_id": "ISO 55001",
                "domain": "standards.ingested.iso",
                "title": "Asset management systems",
                "source": str(source),
                "status": "certified",
                "official_url": "",
                "metadata": {"source_path": str(source)},
            }
        ],
    )

    result = standards_binder.bind_standards(
        {"request": "use ISO 55001", "title": "AIMS"},
        {"standards": ["ISO 55001"]},
    )

    record = result["selected_standards"][0]
    assert record["registered_source_path"] == str(source)
    assert record["registered_source_exists"] is True


def test_docgen_standards_binder_selects_explicit_registered_abs_standard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "ABS vessels classification.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        standards_binder,
        "official_standard_metadata",
        lambda standard_id: {},
    )
    monkeypatch.setattr(
        standards_binder,
        "list_registered_standard_records",
        lambda: [
            {
                "standard_id": "ABS vessels classification",
                "domain": "standards.ingested.abs",
                "title": "ABS vessels classification",
                "source": str(source),
                "status": "pending",
                "official_url": "",
                "metadata": {"source_path": str(source)},
            }
        ],
    )

    result = standards_binder.bind_standards(
        {
            "request": "Generate a comparison-aware policy using ABS vessels classification.",
            "title": "AIMS ABS comparison",
        },
        {"standards": []},
    )

    record = result["selected_standards"][0]
    assert record["standard_id"] == "ABS vessels classification"
    assert record["use"] == "registered_request_match"
    assert record["registered_source_path"] == str(source)
