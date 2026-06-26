from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ops.docsreg.docsreg_learning_capture import record_attempted_cycle_learning
from ops.docsreg.pipelines.run_batch import _run_batch
from ops.scripts.docsreg_explain_pending_registration import (
    build_pending_registration_diagnostics,
)


def _write_quality_report(source_dir: Path, *, quality: float, audit_status: str) -> Path:
    source_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "quality": quality,
        "target_quality": 0.95,
        "audit_status": audit_status,
        "component_scores": {
            "content_richness_score": 0.97,
            "data_retention_score": 0.96,
            "source_to_master_alignment_score": 0.95,
            "structure_score": 0.94,
            "metadata_safety_score": 0.92,
        },
        "source_file": str(source_dir / "ABS vessels classification.pdf"),
    }
    path = source_dir / "quality_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_pending_registration_writes_learning_entry(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source = source_dir / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ABS content", encoding="utf-8")
    _write_quality_report(source_dir, quality=0.85, audit_status="COMPONENT_PASS")

    workspace = tmp_path / "workspace"
    result = SimpleNamespace(job_id="job-1", doc_id="doc-1", cycle_id="cycle-1", outcome="PENDING")

    entry = record_attempted_cycle_learning(
        result=result,
        source_file=source,
        evidence_root=tmp_path / "evidence",
        workspace_dir=workspace,
    )

    learning = _read_jsonl(workspace / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["outcome"]["passed"] is False
    assert learning[0]["outcome"]["audit_status"] == "COMPONENT_PASS"
    assert learning[0]["approved_for_training"] is False
    assert entry["training"]["approved_for_training"] is False


def test_quality_report_without_certification_writes_learning_entry(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source = source_dir / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ABS content", encoding="utf-8")
    _write_quality_report(source_dir, quality=0.50, audit_status="COMPONENT_FAIL_REPAIRABLE")

    workspace = tmp_path / "workspace"
    record_attempted_cycle_learning(
        result=SimpleNamespace(outcome="FAILED"),
        source_file=source,
        evidence_root=tmp_path / "evidence",
        workspace_dir=workspace,
    )

    learning = _read_jsonl(workspace / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["outcome"]["passed"] is False
    assert learning[0]["outcome"]["audit_status"] == "COMPONENT_FAIL_REPAIRABLE"


def test_missing_master_document_skips_gold_but_writes_learning(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source = source_dir / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ABS content", encoding="utf-8")
    (source_dir / "raw_extracted_text.md").write_text("source text", encoding="utf-8")
    _write_quality_report(source_dir, quality=0.97, audit_status="COMPONENT_PASS")

    workspace = tmp_path / "workspace"
    record_attempted_cycle_learning(
        result=SimpleNamespace(outcome="CERTIFIED"),
        source_file=source,
        evidence_root=tmp_path / "evidence",
        workspace_dir=workspace,
    )

    learning = _read_jsonl(workspace / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert not (workspace / "axi_ft_log" / "gold_pairs.jsonl").exists()


def test_component_blocked_skips_gold_but_writes_learning(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source = source_dir / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ABS content", encoding="utf-8")
    (source_dir / "raw_extracted_text.md").write_text("source text", encoding="utf-8")
    (source_dir / "master_document.md").write_text("master text", encoding="utf-8")
    _write_quality_report(source_dir, quality=0.97, audit_status="COMPONENT_BLOCKED")

    workspace = tmp_path / "workspace"
    record_attempted_cycle_learning(
        result=SimpleNamespace(outcome="BLOCKED"),
        source_file=source,
        evidence_root=tmp_path / "evidence",
        workspace_dir=workspace,
    )

    learning = _read_jsonl(workspace / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["outcome"]["audit_status"] == "COMPONENT_BLOCKED"
    assert not (workspace / "axi_ft_log" / "gold_pairs.jsonl").exists()


def test_batch_attempt_writes_learning_entry(tmp_path: Path) -> None:
    input_root = tmp_path / "batch_input"
    source = input_root / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ABS content", encoding="utf-8")
    _write_quality_report(input_root, quality=0.85, audit_status="COMPONENT_PASS")

    captured = SimpleNamespace(passed=False, outcome="PENDING")

    def _mock_cycle(**kwargs):
        return captured

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", _mock_cycle), patch(
        "aims_paths.workspace_root",
        lambda: tmp_path,
    ):
        _run_batch(
            input_root=input_root,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
            workspace_dir=tmp_path,
            redis_url="redis://127.0.0.1:6379/0",
            document_type="standard",
        )

    learning = _read_jsonl(tmp_path / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["outcome"]["passed"] is False
    assert learning[0]["outcome"]["audit_status"] == "COMPONENT_PASS"


def test_nested_cycle_quality_report_writes_learning_entry(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source = source_dir / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ABS content", encoding="utf-8")

    nested_cycle_dir = tmp_path / "evidence" / "0001_ABS vessels classification" / "procedure" / "procedure_cycle000_123"
    _write_quality_report(nested_cycle_dir, quality=0.85, audit_status="COMPONENT_PASS")

    workspace = tmp_path / "workspace"
    record_attempted_cycle_learning(
        result=SimpleNamespace(outcome="PENDING"),
        source_file=source,
        evidence_root=tmp_path / "evidence",
        workspace_dir=workspace,
    )

    learning = _read_jsonl(workspace / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["outcome"]["audit_status"] == "COMPONENT_PASS"


def test_pending_diagnostics_reports_failed_gates(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    input_dir = evidence_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "raw_extracted_text.md").write_text("raw", encoding="utf-8")
    (input_dir / "extraction_report.json").write_text(json.dumps({"extractor": "markitdown"}), encoding="utf-8")
    (input_dir / "source_manifest.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    _write_quality_report(input_dir, quality=0.85, audit_status="COMPONENT_PASS")

    report = build_pending_registration_diagnostics(
        evidence_root=evidence_root,
        output_root=tmp_path / "output",
    )

    assert report["certification_status"] == "PENDING"
    assert report["quality_report_found"] is True
    assert "quality_below_certified_threshold" in report["failed_gates"]
    assert report["qdrant_skipped_reason"]
    assert report["documents_write_skipped_reason"]
    assert report["can_certify_if_fixed"] is False


def test_pending_diagnostics_does_not_certify(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    input_dir = evidence_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "raw_extracted_text.md").write_text("raw", encoding="utf-8")
    (input_dir / "extraction_report.json").write_text(json.dumps({"extractor": "markitdown"}), encoding="utf-8")
    _write_quality_report(input_dir, quality=0.85, audit_status="COMPONENT_PASS")

    report = build_pending_registration_diagnostics(
        evidence_root=evidence_root,
        output_root=tmp_path / "output",
    )

    assert report["certification_status"] != "CERTIFIED"
    assert report["can_certify_if_fixed"] is False


def test_learning_entry_never_auto_approved_for_training(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source = source_dir / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ABS content", encoding="utf-8")
    _write_quality_report(source_dir, quality=0.85, audit_status="COMPONENT_PASS")

    workspace = tmp_path / "workspace"
    record_attempted_cycle_learning(
        result=SimpleNamespace(outcome="PENDING"),
        source_file=source,
        evidence_root=tmp_path / "evidence",
        workspace_dir=workspace,
    )

    learning = _read_jsonl(workspace / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["approved_for_training"] is False
