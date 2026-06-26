from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CERTIFIED_THRESHOLD = 0.95
ADVISORY_THRESHOLD = 0.60


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
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


def _derive_quality(report: dict[str, Any] | None) -> float:
    if not report:
        return 0.0
    for key in ("final_quality", "quality", "composite_quality", "quality_score"):
        value = report.get(key)
        if value is not None and value != "":
            try:
                return float(value)
            except Exception:
                continue
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


def classify_docsreg_attempt(
    *,
    source_file: Path,
    evidence_root: Path,
    result: Any | None = None,
) -> dict[str, Any]:
    """Classify a DOCSREG attempt without confusing pending with failure."""
    source_file = Path(source_file)
    evidence_root = Path(evidence_root)
    quality_report_path = _find_first(evidence_root, "quality_report.json")
    if quality_report_path is None:
        quality_report_path = _find_first(source_file.parent, "quality_report.json")
    quality_report = _load_json(quality_report_path)

    quality = _derive_quality(quality_report)
    audit_status = str((quality_report or {}).get("audit_status", (quality_report or {}).get("status", "UNKNOWN")))
    passed = bool(getattr(result, "passed", False))
    outcome = str(getattr(result, "outcome", "UNKNOWN"))
    error_text = " ".join(
        str(part)
        for part in (
            getattr(result, "error", ""),
            getattr(result, "notes", ""),
            outcome,
        )
        if part
    ).lower()

    if passed:
        category = "certified"
    elif quality_report is not None:
        if quality >= ADVISORY_THRESHOLD and quality < CERTIFIED_THRESHOLD and audit_status in {
            "COMPONENT_PASS",
            "READY_TO_FREEZE",
            "READY_TO_FREEZE_FOR_DOCUMENT_TYPE",
        }:
            category = "advisory"
        else:
            category = "pending_needs_repair"
    elif any(token in error_text for token in ("parse", "parser", "validation", "rejected", "structure")):
        category = "parse_rejected"
    else:
        category = "real_failed"

    learning_entry_required = quality_report is not None
    approved_for_training = False

    return {
        "category": category,
        "quality_report_found": quality_report is not None,
        "quality": quality,
        "audit_status": audit_status,
        "passed": passed,
        "failed_registration": category in {"real_failed", "parse_rejected"},
        "learning_entry_required": learning_entry_required,
        "approved_for_training": approved_for_training,
        "quality_report_path": str(quality_report_path) if quality_report_path else "",
    }
