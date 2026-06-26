from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.docgen.universal_pipeline.standard_markitdown_normalizer import (
    normalize_standards_for_comparison,
)
from ops.docsreg.docsreg_evidence_checkpoint import DocsregEvidenceCheckpoint
from ops.docsreg.docsreg_run_manifest import DocsregRunManifest
from ops.docsreg.docsreg_tasks import task_extraction_ready
from ops.docsreg.extraction.markitdown_adapter import extract_with_markitdown


ABS_STANDARD = Path(
    "/media/axi_omi_sphere/FDF0-25E2/Documents/Standards/ABS/ABS/"
    "ABS vessels classification.pdf"
)

pytestmark = pytest.mark.integration


class _MemoryScheduler:
    run_id = "real-abs-markitdown"

    def __init__(self) -> None:
        self.contracts = {}

    def save_contract(self, contract) -> None:
        self.contracts[contract.stage] = contract

    def load_contract(self, stage: str):
        return self.contracts.get(stage)


def _require_abs_standard() -> Path:
    if not ABS_STANDARD.exists():
        pytest.skip(f"ABS real standard fixture not mounted: {ABS_STANDARD}")
    return ABS_STANDARD


def test_real_abs_standard_extracts_with_markitdown_from_default_python() -> None:
    source = _require_abs_standard()

    result = extract_with_markitdown(source)

    assert result.status == "extracted"
    assert result.extractor == "markitdown"
    assert result.word_count >= 1000
    assert result.char_count >= 5000
    assert result.metadata["markitdown_version"] != "unavailable"


def test_real_abs_standard_docsreg_extraction_contract_writes_raw_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _require_abs_standard()
    evidence_dir = tmp_path / "docsreg_extraction"
    monkeypatch.setenv("DOCSREG_EXTRACTOR_BACKEND", "markitdown")
    monkeypatch.setenv("DOCSREG_EXTRACTION_ARTIFACT_DIR", str(evidence_dir))

    manifest = DocsregRunManifest.create(
        run_id="real-abs-markitdown",
        draft_path=str(source),
    )
    checkpoint = DocsregEvidenceCheckpoint(_MemoryScheduler())

    contract = task_extraction_ready(manifest, checkpoint)

    assert contract.gates["extraction_gate"] == "PASS"
    assert contract.metrics["extraction_method"] == "markitdown"
    assert contract.metrics["extraction_status"] == "extracted"
    assert contract.metrics["word_count"] >= 1000
    raw_path = Path(contract.output_artifacts["raw_extracted_text"])
    report_path = Path(contract.output_artifacts["extraction_report"])
    assert raw_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["extractor"] == "markitdown"
    assert report["status"] == "extracted"
    assert "raw_markdown" not in report


def test_real_abs_standard_docgen_comparison_normalization_writes_artifacts(
    tmp_path: Path,
) -> None:
    source = _require_abs_standard()
    standards = {
        "selected_standards": [
            {
                "standard_id": "ABS Vessels Classification",
                "title": "ABS vessels classification",
                "registered_source_path": str(source),
            }
        ]
    }

    summary = normalize_standards_for_comparison(
        standards,
        tmp_path / "docgen_standard_comparison",
        enabled=True,
    )

    assert summary["status"] == "PASS"
    assert summary["standards_extracted"] == 1
    assert summary["comparison_only"] is True
    assert summary["generation_context_allowed"] is False
    entry = summary["entries"][0]
    assert entry["generation_context_allowed"] is False
    assert entry["raw_markdown_in_generation_context"] is False
    assert Path(entry["raw_extracted_text_path"]).exists()
    report = json.loads(Path(entry["extraction_report_path"]).read_text(encoding="utf-8"))
    assert report["extractor"] == "markitdown"
    assert report["word_count"] >= 1000
    assert "raw_markdown" not in report
