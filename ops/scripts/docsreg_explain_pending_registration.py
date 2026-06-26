from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CERTIFIED_THRESHOLD = 0.95
REJECTED_THRESHOLD = 0.60


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _find_first(root: Path, pattern: str) -> Path | None:
    for path in sorted(root.rglob(pattern)):
        if path.is_file():
            return path
    return None


def _find_all(root: Path, pattern: str) -> list[Path]:
    return [path for path in sorted(root.rglob(pattern)) if path.is_file()]


def _find_source_file(evidence_root: Path) -> Path | None:
    input_root = evidence_root / "input"
    if input_root.exists():
        for path in sorted(input_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {
                ".pdf",
                ".docx",
                ".pptx",
                ".xlsx",
                ".xls",
                ".csv",
                ".html",
                ".htm",
                ".txt",
                ".md",
            }:
                return path
    for path in sorted(evidence_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {
            ".pdf",
            ".docx",
            ".pptx",
            ".xlsx",
            ".xls",
            ".csv",
            ".html",
            ".htm",
            ".txt",
            ".md",
        }:
            return path
    return None


def _derive_quality(report: dict[str, Any]) -> float:
    for key in ("final_quality", "quality", "composite_quality", "quality_score"):
        value = report.get(key)
        if value is not None and value != "":
            try:
                return float(value)
            except Exception:
                pass

    component_scores = report.get("component_scores")
    if isinstance(component_scores, dict) and component_scores:
        values: list[float] = []
        for value in component_scores.values():
            try:
                values.append(float(value))
            except Exception:
                continue
        if values:
            return sum(values) / len(values)

    return 0.0


def _diagnose_from_quality_report(report: dict[str, Any]) -> tuple[list[str], str, str]:
    quality = _derive_quality(report)
    target_quality = float(report.get("target_quality", report.get("threshold", 0.0)) or 0.0)
    audit_status = str(report.get("audit_status", report.get("status", "UNKNOWN")))

    failed_gates: list[str] = []
    if quality < CERTIFIED_THRESHOLD:
        failed_gates.append("quality_below_certified_threshold")
    if quality < REJECTED_THRESHOLD:
        failed_gates.append("quality_below_rejected_threshold")
    if audit_status not in {"COMPONENT_PASS", "READY_TO_FREEZE"}:
        failed_gates.append(f"audit_status_not_certified:{audit_status}")

    qdrant_reason = "certification_status='PENDING' (must be CERTIFIED)"
    documents_reason = "certification_status='PENDING' (master_document write skipped)"
    if quality < CERTIFIED_THRESHOLD:
        qdrant_reason = (
            f"quality_score={quality:.3f} below certification threshold {CERTIFIED_THRESHOLD:.2f}"
        )
        documents_reason = (
            f"quality_score={quality:.3f} below certification threshold {CERTIFIED_THRESHOLD:.2f}"
        )

    if target_quality and quality < target_quality:
        failed_gates.append(f"below_target_quality:{quality:.3f}<{target_quality:.3f}")

    return failed_gates, qdrant_reason, documents_reason


def build_pending_registration_diagnostics(
    *,
    evidence_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    evidence_root = Path(evidence_root)
    output_root = Path(output_root)

    quality_report_path = _find_first(evidence_root, "quality_report.json")
    source_manifest_path = _find_first(evidence_root, "source_manifest.json")
    registration_manifest_path = _find_first(evidence_root, "registration_manifest.json")
    raw_extracted_path = _find_first(evidence_root, "raw_extracted_text.md")
    master_document_path = _find_first(evidence_root, "master_document.md")
    extraction_report_path = _find_first(evidence_root, "extraction_report.json")
    log_path = _find_first(evidence_root, "*.log")

    quality_report = _load_json(quality_report_path) if quality_report_path else None
    component_scores = dict(quality_report.get("component_scores", {})) if quality_report else {}
    if not component_scores and quality_report:
        for key in (
            "content_richness_score",
            "data_retention_score",
            "source_to_master_alignment_score",
            "structure_score",
            "metadata_safety_score",
        ):
            if key in quality_report:
                component_scores[key] = quality_report.get(key)

    quality = _derive_quality(quality_report) if quality_report else 0.0
    target_quality = float(quality_report.get("target_quality", quality_report.get("threshold", 0.0)) or 0.0) if quality_report else 0.0
    audit_status = str(quality_report.get("audit_status", quality_report.get("status", "UNKNOWN"))) if quality_report else "UNKNOWN"

    failed_gates, qdrant_reason, documents_reason = (
        _diagnose_from_quality_report(quality_report) if quality_report else (["quality_report_missing"], "quality_report missing", "quality_report missing")
    )

    missing_artifacts = []
    if quality_report_path is None:
        missing_artifacts.append("quality_report.json")
    if source_manifest_path is None:
        missing_artifacts.append("source_manifest.json")
    if registration_manifest_path is None:
        missing_artifacts.append("registration_manifest.json")
    if raw_extracted_path is None:
        missing_artifacts.append("raw_extracted_text.md")
    if master_document_path is None:
        missing_artifacts.append("master_document.md")
    if extraction_report_path is None:
        missing_artifacts.append("extraction_report.json")

    source_file = str(quality_report.get("source_file") or "") if quality_report else ""
    standard_id = str(quality_report.get("standard_id") or quality_report.get("document_id") or "") if quality_report else ""
    if not source_file:
        source_path = _find_source_file(evidence_root)
        if source_path is not None:
            source_file = str(source_path)
            if not standard_id:
                standard_id = source_path.stem
    registration_status = "PENDING"
    if quality_report and quality >= CERTIFIED_THRESHOLD and audit_status in {"COMPONENT_PASS", "READY_TO_FREEZE"}:
        registration_status = "CERTIFIED"
    elif quality_report and quality < REJECTED_THRESHOLD:
        registration_status = "REJECTED"

    can_certify_if_fixed = bool(
        quality_report
        and quality >= CERTIFIED_THRESHOLD
        and raw_extracted_path is not None
        and extraction_report_path is not None
        and master_document_path is not None
        and registration_manifest_path is not None
    )

    report = {
        "source_file": source_file,
        "standard_id": standard_id,
        "certification_status": registration_status,
        "registration_status": registration_status,
        "quality_report_found": quality_report is not None,
        "final_quality": quality,
        "target_quality": target_quality,
        "audit_status": audit_status,
        "component_scores": component_scores,
        "failed_gates": failed_gates,
        "missing_artifacts": missing_artifacts,
        "qdrant_skipped_reason": qdrant_reason,
        "documents_write_skipped_reason": documents_reason,
        "can_certify_if_fixed": can_certify_if_fixed,
        "required_next_fix": (
            "Raise composite quality to at least 0.95 and rerun certification so the registration gate can emit CERTIFIED."
            if registration_status == "PENDING"
            else "Restore missing registration artifacts and rerun certification."
        ),
        "source_manifest_path": str(source_manifest_path) if source_manifest_path else "",
        "quality_report_path": str(quality_report_path) if quality_report_path else "",
        "registration_manifest_path": str(registration_manifest_path) if registration_manifest_path else "",
        "raw_extracted_text_path": str(raw_extracted_path) if raw_extracted_path else "",
        "master_document_path": str(master_document_path) if master_document_path else "",
        "extraction_report_path": str(extraction_report_path) if extraction_report_path else "",
        "log_path": str(log_path) if log_path else "",
        "log_contains_pending": bool(
            log_path and "certification_status='PENDING'" in log_path.read_text(encoding="utf-8", errors="ignore")
        ),
    }

    output_root.mkdir(parents=True, exist_ok=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explain why a DOCSREG registration stayed PENDING")
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--report-out", required=True)
    args = parser.parse_args(argv)

    report = build_pending_registration_diagnostics(
        evidence_root=Path(args.evidence_root),
        output_root=Path(args.output_root),
    )

    report_path = Path(args.report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
