from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.docsreg.extraction import markitdown_adapter
from ops.docsreg.extraction.markitdown_adapter import (
    extract_with_markitdown,
    write_extraction_artifacts,
)


class _FakeMarkItDown:
    def convert(self, source_path: str):
        return SimpleNamespace(text_content=Path(source_path).read_text(encoding="utf-8"))


def _install_fake_markitdown(monkeypatch: pytest.MonkeyPatch, fake_class= _FakeMarkItDown) -> None:
    class _FakeModule:
        MarkItDown = fake_class
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


def test_markitdown_adapter_reports_unavailable_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.md"
    source.write_text("# Sample\n\ntext", encoding="utf-8")

    def _raise_import_error(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(markitdown_adapter.importlib, "import_module", _raise_import_error)

    result = extract_with_markitdown(source)

    assert result.extractor == "markitdown"
    assert result.status == "extractor_unavailable"
    assert result.raw_markdown == ""
    assert result.word_count == 0
    assert any("extractor_unavailable" in warning for warning in result.warnings)


def test_markitdown_extracts_txt_or_md_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_markitdown(monkeypatch)
    fixture = Path("ops/tests/fixtures/docsreg_markitdown/sample.md")

    result = extract_with_markitdown(fixture)

    assert result.status == "extracted"
    assert result.extractor == "markitdown"
    assert "# Sample Standard" in result.raw_markdown
    assert result.word_count > 5
    assert result.char_count == len(result.raw_markdown)
    assert result.metadata["source_suffix"] == ".md"


def test_markitdown_extraction_writes_raw_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_markitdown(monkeypatch)
    fixture = Path("ops/tests/fixtures/docsreg_markitdown/sample.txt")
    result = extract_with_markitdown(fixture)

    paths = write_extraction_artifacts(result, tmp_path)

    raw_path = Path(paths["raw_extracted_text"])
    report_path = Path(paths["extraction_report"])
    assert raw_path.name == "raw_extracted_text.md"
    assert report_path.name == "extraction_report.json"
    assert "Sample DOCSREG source text" in raw_path.read_text(encoding="utf-8")


def test_markitdown_extraction_report_has_word_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_markitdown(monkeypatch)
    fixture = Path("ops/tests/fixtures/docsreg_markitdown/sample.txt")
    result = extract_with_markitdown(fixture)
    paths = write_extraction_artifacts(result, tmp_path)

    report = Path(paths["extraction_report"]).read_text(encoding="utf-8")

    assert '"extractor": "markitdown"' in report
    assert '"status": "extracted"' in report
    assert '"word_count":' in report
    assert '"raw_markdown"' not in report


def test_markitdown_unsupported_media_returns_unsupported_format(tmp_path: Path) -> None:
    source = tmp_path / "image.jpg"
    source.write_bytes(b"not an ocr source")

    result = extract_with_markitdown(source)

    assert result.status == "unsupported_format"
    assert result.char_count == 0
    assert result.metadata["source_suffix"] == ".jpg"
