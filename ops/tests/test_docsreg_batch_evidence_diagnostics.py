from __future__ import annotations

import json
from pathlib import Path

from ops.scripts.docsreg_diagnose_batch_evidence import build_batch_diagnostics


def _write_quality_report(path: Path, *, quality: float, audit_status: str, source_file: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "quality_report.json").write_text(
        json.dumps(
            {
                "quality": quality,
                "audit_status": audit_status,
                "source_file": source_file,
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


def test_batch_diagnostics_reads_quality_reports(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    _write_quality_report(
        evidence_root / "001_sample_a",
        quality=0.97,
        audit_status="COMPONENT_PASS",
        source_file="/media/sample_a.pdf",
    )
    _write_quality_report(
        evidence_root / "002_sample_b",
        quality=0.82,
        audit_status="COMPONENT_PASS",
        source_file="/media/sample_b.pdf",
    )
    _write_quality_report(
        evidence_root / "003_sample_c",
        quality=0.50,
        audit_status="COMPONENT_FAIL_REPAIRABLE",
        source_file="/media/sample_c.pdf",
    )

    report = build_batch_diagnostics(evidence_root=evidence_root, output_root=tmp_path / "out")

    assert report["quality_reports_found"] == 3
    assert report["certified"] == 1
    assert report["advisory"] == 1
    assert report["pending_needs_repair"] == 1
    assert report["real_failed"] == 0
    assert report["failed_registration"] == 0
