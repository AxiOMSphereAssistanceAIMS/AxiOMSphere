from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CERTIFIED_THRESHOLD = 0.95
ADVISORY_THRESHOLD = 0.60


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _derive_quality(report: dict[str, Any] | None) -> float:
    if not report:
        return 0.0
    for key in ("final_quality", "quality", "composite_quality", "quality_score"):
        value = report.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except Exception:
                continue
    component_scores = report.get("component_scores")
    if isinstance(component_scores, dict):
        values: list[float] = []
        for value in component_scores.values():
            try:
                values.append(float(value))
            except Exception:
                continue
        if values:
            return sum(values) / len(values)
    return 0.0


def _find_quality_reports(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("quality_report.json")) if path.is_file()]


def build_batch_diagnostics(*, evidence_root: Path, output_root: Path | None = None) -> dict[str, Any]:
    evidence_root = Path(evidence_root)
    output_root = Path(output_root) if output_root is not None else evidence_root

    if not evidence_root.exists():
        return {
            "evidence_root": str(evidence_root),
            "access_blocker": "evidence_root_missing",
            "certified": 0,
            "advisory": 0,
            "pending_needs_repair": 0,
            "real_failed": 0,
            "unsupported": 0,
            "parse_rejected": 0,
            "missing_quality_report": 0,
            "quality_reports_found": 0,
            "failed_registration": 0,
            "attempts": [],
        }

    quality_reports = _find_quality_reports(evidence_root)
    attempts: list[dict[str, Any]] = []
    counts = {
        "certified": 0,
        "advisory": 0,
        "pending_needs_repair": 0,
        "real_failed": 0,
        "unsupported": 0,
        "parse_rejected": 0,
        "missing_quality_report": 0,
    }

    for report_path in quality_reports:
        report = _load_json(report_path) or {}
        quality = _derive_quality(report)
        audit_status = str(report.get("audit_status", report.get("status", "UNKNOWN")))
        if quality >= CERTIFIED_THRESHOLD and audit_status in {"COMPONENT_PASS", "READY_TO_FREEZE"}:
            category = "certified"
        elif quality >= ADVISORY_THRESHOLD and audit_status in {"COMPONENT_PASS", "READY_TO_FREEZE"}:
            category = "advisory"
        else:
            category = "pending_needs_repair"

        counts[category] += 1
        attempts.append(
            {
                "quality_report_path": str(report_path),
                "source_file": str(report.get("source_file") or ""),
                "standard_id": str(report.get("standard_id") or report.get("document_id") or ""),
                "category": category,
                "final_quality": quality,
                "audit_status": audit_status,
                "failed_gates": [
                    gate
                    for gate in (
                        "quality_below_certified_threshold"
                        if quality < CERTIFIED_THRESHOLD
                        else "",
                        "quality_below_advisory_threshold"
                        if quality < ADVISORY_THRESHOLD
                        else "",
                    )
                    if gate
                ],
            }
        )

    if not quality_reports:
        counts["missing_quality_report"] = 1

    report = {
        "evidence_root": str(evidence_root),
        "access_blocker": "",
        "certified": counts["certified"],
        "advisory": counts["advisory"],
        "pending_needs_repair": counts["pending_needs_repair"],
        "real_failed": counts["real_failed"],
        "unsupported": counts["unsupported"],
        "parse_rejected": counts["parse_rejected"],
        "missing_quality_report": counts["missing_quality_report"],
        "quality_reports_found": len(quality_reports),
        "failed_registration": counts["real_failed"] + counts["parse_rejected"],
        "attempts": attempts,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose DOCSREG batch evidence")
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--output-root", default="")
    args = parser.parse_args(argv)

    output_root = Path(args.output_root) if args.output_root else Path(args.report_out).parent
    report = build_batch_diagnostics(
        evidence_root=Path(args.evidence_root),
        output_root=output_root,
    )
    report_path = Path(args.report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
