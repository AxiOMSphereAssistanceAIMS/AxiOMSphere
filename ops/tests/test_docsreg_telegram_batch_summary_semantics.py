from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ops.docsreg.docsreg_batch_semantics import classify_docsreg_attempt


def _write_quality_report(path: Path, *, quality: float, audit_status: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / "quality_report.json"
    report_path.write_text(
        json.dumps(
            {
                "quality": quality,
                "audit_status": audit_status,
                "source_file": str(path / "ABS vessels classification.pdf"),
                "component_scores": {
                    "content_richness_score": quality,
                    "data_retention_score": quality,
                    "source_to_master_alignment_score": quality,
                    "structure_score": quality,
                    "metadata_safety_score": quality,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return report_path


def test_pending_docs_not_counted_as_failed_registration(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    source = evidence / "input" / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("abs", encoding="utf-8")
    _write_quality_report(source.parent, quality=0.55, audit_status="COMPONENT_PASS")

    classification = classify_docsreg_attempt(
        source_file=source,
        evidence_root=evidence,
        result=SimpleNamespace(passed=False, outcome="DOCUMENT_TYPE_STALLED"),
    )

    assert classification["category"] == "pending_needs_repair"
    assert classification["failed_registration"] is False


def test_advisory_docs_not_counted_as_failed_registration(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    source = evidence / "input" / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("abs", encoding="utf-8")
    _write_quality_report(source.parent, quality=0.82, audit_status="COMPONENT_PASS")

    classification = classify_docsreg_attempt(
        source_file=source,
        evidence_root=evidence,
        result=SimpleNamespace(passed=False, outcome="DOCUMENT_TYPE_STALLED"),
    )

    assert classification["category"] in {"advisory", "pending_needs_repair"}
    assert classification["failed_registration"] is False


def test_real_exception_counted_as_failed_registration(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    source = evidence / "input" / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("abs", encoding="utf-8")

    classification = classify_docsreg_attempt(
        source_file=source,
        evidence_root=evidence,
        result=SimpleNamespace(passed=False, outcome="FAILED", error="RuntimeError: broken"),
    )

    assert classification["category"] == "real_failed"
    assert classification["failed_registration"] is True


def test_telegram_summary_reports_certified_advisory_pending_failed(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    source = evidence / "input" / "ABS vessels classification.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("abs", encoding="utf-8")
    _write_quality_report(source.parent, quality=0.97, audit_status="COMPONENT_PASS")

    certified = classify_docsreg_attempt(
        source_file=source,
        evidence_root=evidence,
        result=SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED"),
    )
    pending = classify_docsreg_attempt(
        source_file=source,
        evidence_root=evidence,
        result=SimpleNamespace(passed=False, outcome="DOCUMENT_TYPE_STALLED"),
    )

    assert certified["category"] == "certified"
    assert pending["approved_for_training"] is False
