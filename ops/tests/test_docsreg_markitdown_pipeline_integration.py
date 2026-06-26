from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.docsreg import docsreg_tasks
from ops.docsreg.batch.archive_extractor import extract_archive
from ops.docsreg.docsreg_evidence_checkpoint import DocsregEvidenceCheckpoint
from ops.docsreg.docsreg_run_manifest import DocsregRunManifest
from ops.docsreg.docsreg_tasks import task_extraction_ready
from ops.docsreg.extraction import markitdown_adapter
from ops.docsreg.docsreg_composite_quality_gate import compute_composite_quality


class _FakeMarkItDown:
    def convert(self, source_path: str):
        return SimpleNamespace(text_content=Path(source_path).read_text(encoding="utf-8"))


class _FailingMarkItDown:
    def convert(self, source_path: str):
        raise PermissionError(f"blocked: {source_path}")


def _install_fake_markitdown(monkeypatch: pytest.MonkeyPatch, fake_class=_FakeMarkItDown) -> None:
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


class _MemoryScheduler:
    run_id = "test-run"

    def __init__(self) -> None:
        self.contracts = {}

    def save_contract(self, contract) -> None:
        self.contracts[contract.stage] = contract

    def load_contract(self, stage: str):
        return self.contracts.get(stage)


def test_markitdown_failure_not_counted_as_registration_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_markitdown(monkeypatch, _FailingMarkItDown)
    monkeypatch.setenv("DOCSREG_EXTRACTOR_BACKEND", "markitdown")
    monkeypatch.setenv("DOCSREG_EXTRACTION_ARTIFACT_DIR", str(tmp_path / "evidence"))

    source = tmp_path / "source.md"
    source.write_text("# Source\n\ncontent", encoding="utf-8")
    manifest = DocsregRunManifest.create(run_id="test-run", draft_path=str(source))
    checkpoint = DocsregEvidenceCheckpoint(_MemoryScheduler())

    contract = task_extraction_ready(manifest, checkpoint)

    assert contract.gates["extraction_gate"] == "FAIL"
    assert contract.metrics["extraction_status"] == "extraction_failed"
    assert contract.metrics["extraction_method"] == "markitdown"
    assert Path(contract.output_artifacts["extraction_report"]).exists()
    assert Path(contract.output_artifacts["raw_extracted_text"]).exists()


def test_auto_backend_uses_markitdown_for_office_format_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_markitdown(monkeypatch)
    monkeypatch.setenv("DOCSREG_EXTRACTOR_BACKEND", "auto")
    source = tmp_path / "office.docx"
    source.write_text("Office document text extracted by fake MarkItDown.", encoding="utf-8")

    result = docsreg_tasks._extract_text_result(source)

    assert result.status == "extracted"
    assert result.extractor == "markitdown"
    assert "fake MarkItDown" in result.raw_markdown


def test_markitdown_raw_output_not_certified_without_master_package() -> None:
    raw_markdown = "word " * 1200

    scores = compute_composite_quality(raw_markdown, evidence_dir=None)

    assert scores.content_richness_score > scores.final_quality
    assert scores.final_quality < 0.90


def test_archive_member_can_use_markitdown_after_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_markitdown(monkeypatch)
    monkeypatch.setenv("DOCSREG_EXTRACTOR_BACKEND", "auto")

    archive = tmp_path / "standards.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/standard.docx", "Archive member text for MarkItDown.")

    result, members = extract_archive(archive, tmp_path / "extracted")
    queued = [member for member in members if member.member_path.endswith("standard.docx")]

    assert result.status.value == "extracted"
    assert queued

    extracted = docsreg_tasks._extract_text_result(queued[0].path)

    assert extracted.status == "extracted"
    assert extracted.extractor == "markitdown"
    assert "Archive member text" in extracted.raw_markdown
