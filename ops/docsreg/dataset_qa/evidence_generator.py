"""PHASE 9 Evidence Generator — produces all output files for the dataset QA pipeline."""
import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from ops.docsreg.dataset_qa.models import (
    TrainingExample,
    DatasetManifest,
    DatasetQualityReport,
    DeduplicationResult,
    BalanceReport,
    LeakageFinding,
)


def _example_to_dict(ex: TrainingExample) -> dict:
    """Convert a TrainingExample to a JSON-serializable dict."""
    return asdict(ex)


def _jsonl(examples: List[TrainingExample]) -> str:
    """Convert examples to JSONL format."""
    return "\n".join(json.dumps(_example_to_dict(ex), ensure_ascii=False) for ex in examples)


class DatasetEvidenceGenerator:
    """Generates all output artifacts for the PHASE 9 Dataset QA pipeline.

    Output files:
    - docsreg_phase9_training_dataset.jsonl
    - docsreg_phase9_validation_dataset.jsonl
    - docsreg_phase9_rejected_examples.jsonl
    - docsreg_phase9_dataset_manifest.json
    - docsreg_phase9_dataset_quality_report.json
    - docsreg_phase9_leakage_report.json
    - docsreg_phase9_deduplication_report.json
    - docsreg_phase9_balance_report.json
    - docsreg_phase9_readiness_checklist.json
    """

    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.output_root.mkdir(parents=True, exist_ok=True)

    def generate_all(
        self,
        training_set: List[TrainingExample],
        validation_set: List[TrainingExample],
        rejected_examples: List[TrainingExample],
        manifest: DatasetManifest,
        quality_report: DatasetQualityReport,
        leakage_findings: List[LeakageFinding],
        dedup_result: Optional[DeduplicationResult],
        balance_report: Optional[BalanceReport],
    ) -> List[Path]:
        """Generate all evidence files. Returns list of created file paths."""
        files: List[Path] = []

        files.append(self._write_jsonl("docsreg_phase9_training_dataset.jsonl", training_set))
        files.append(self._write_jsonl("docsreg_phase9_validation_dataset.jsonl", validation_set))
        files.append(self._write_jsonl("docsreg_phase9_rejected_examples.jsonl", rejected_examples))
        files.append(self._write_json("docsreg_phase9_dataset_manifest.json", asdict(manifest)))
        files.append(self._write_json("docsreg_phase9_dataset_quality_report.json", asdict(quality_report)))
        files.append(self._write_leakage_report(leakage_findings))
        files.append(self._write_dedup_report(dedup_result))
        files.append(self._write_balance_report(balance_report))
        files.append(self._write_readiness_checklist(quality_report))

        return files

    def _write_jsonl(self, filename: str, examples: List[TrainingExample]) -> Path:
        """Write examples as JSONL."""
        path = self.output_root / filename
        content = _jsonl(examples) if examples else ""
        path.write_text(content, encoding="utf-8")
        return path

    def _write_json(self, filename: str, data: dict) -> Path:
        """Write a dict as formatted JSON."""
        path = self.output_root / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return path

    def _write_leakage_report(self, findings: List[LeakageFinding]) -> Path:
        """Write leakage detection report."""
        report = {
            "total_findings": len(findings),
            "findings_by_type": {},
            "details": [],
        }

        # Aggregate by type
        by_type: dict = {}
        for f in findings:
            key = f.leakage_type.value
            by_type[key] = by_type.get(key, 0) + 1
            report["details"].append({
                "leakage_type": key,
                "field_name": f.field_name,
                "matched_text": f.matched_text,
                "replacement": f.replacement,
                "position": f.position,
            })
        report["findings_by_type"] = by_type

        return self._write_json("docsreg_phase9_leakage_report.json", report)

    def _write_dedup_report(self, result: Optional[DeduplicationResult]) -> Path:
        """Write deduplication report."""
        if result is None:
            data = {"status": "not_run"}
        else:
            data = asdict(result)
        return self._write_json("docsreg_phase9_deduplication_report.json", data)

    def _write_balance_report(self, report: Optional[BalanceReport]) -> Path:
        """Write balance analysis report."""
        if report is None:
            data = {"status": "not_run"}
        else:
            data = asdict(report)
        return self._write_json("docsreg_phase9_balance_report.json", data)

    def _write_readiness_checklist(self, quality_report: DatasetQualityReport) -> Path:
        """Write readiness checklist."""
        checklist = quality_report.readiness_checklist.copy()
        checklist["overall_verdict"] = "READY" if quality_report.passes_quality_gate else "NOT_READY"
        return self._write_json("docsreg_phase9_readiness_checklist.json", checklist)
