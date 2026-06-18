"""PHASE 9 Example Builder — constructs TrainingExample records from Phase 7/8 evidence."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ops.docsreg.dataset_qa.models import TrainingExample


def _sha256(text: str) -> str:
    """Compute SHA-256 hex digest of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExampleBuilder:
    """Builds TrainingExample records from Phase 7 skill testing evidence.

    Consumes evidence packages produced by the Phase 7 framework and
    Phase 8 recovery orchestrator to create structured training examples.
    """

    def __init__(self):
        self._examples: List[TrainingExample] = []

    @property
    def examples(self) -> List[TrainingExample]:
        return list(self._examples)

    def build_from_evidence(self, evidence_root: Path) -> List[TrainingExample]:
        """Build examples from an evidence directory.

        Looks for skill_results.json or similar evidence files.
        """
        self._examples = []
        results_file = evidence_root / "skill_results.json"
        if results_file.exists():
            data = json.loads(results_file.read_text())
            self._build_from_results_dict(data)
        return list(self._examples)

    def build_from_records(self, records: List[Dict]) -> List[TrainingExample]:
        """Build examples from a list of record dicts (programmatic API)."""
        self._examples = []
        for rec in records:
            example = self._record_to_example(rec)
            if example is not None:
                self._examples.append(example)
        return list(self._examples)

    def build_single(
        self,
        document_id: str,
        archetype: str,
        failure_class: str,
        skill_id: str,
        skill_version: str,
        source_text: str,
        failure_context: str,
        repair_instruction: str,
        repaired_text: str,
        quality_before: float,
        quality_after: float,
        data_retention_rate: float,
        data_loss_percentage: float,
        required_field_preservation_rate: float,
        section_preservation_rate: float,
        retention_verdict: str,
        repair_verdict: str,
    ) -> TrainingExample:
        """Build a single training example with computed fields."""
        quality_delta = round(quality_after - quality_before, 4)
        input_sha = _sha256(source_text)
        output_sha = _sha256(repaired_text)
        example_id = f"ex_{document_id}_{failure_class}_{input_sha[:8]}"

        return TrainingExample(
            example_id=example_id,
            document_id=document_id,
            archetype=archetype,
            failure_class=failure_class,
            skill_id=skill_id,
            skill_version=skill_version,
            source_text=source_text,
            failure_context=failure_context,
            repair_instruction=repair_instruction,
            repaired_text=repaired_text,
            quality_before=quality_before,
            quality_after=quality_after,
            quality_delta=quality_delta,
            data_retention_rate=data_retention_rate,
            data_loss_percentage=data_loss_percentage,
            required_field_preservation_rate=required_field_preservation_rate,
            section_preservation_rate=section_preservation_rate,
            retention_verdict=retention_verdict,
            repair_verdict=repair_verdict,
            input_sha256=input_sha,
            output_sha256=output_sha,
            created_at=_now_iso(),
        )

    def _build_from_results_dict(self, data: Dict) -> None:
        """Build examples from a Phase 7 results dict."""
        for skill_name, skill_data in data.items():
            cases = skill_data.get("cases", [])
            for case in cases:
                example = self._case_to_example(skill_name, case)
                if example is not None:
                    self._examples.append(example)

    def _case_to_example(self, skill_name: str, case: Dict) -> Optional[TrainingExample]:
        """Convert a Phase 7 test case dict to a TrainingExample."""
        source = case.get("source_text", "")
        repaired = case.get("repaired_text", "")
        if not source or not repaired:
            return None

        return self.build_single(
            document_id=case.get("document_id", "unknown"),
            archetype=case.get("archetype", "unknown"),
            failure_class=case.get("failure_class", ""),
            skill_id=skill_name,
            skill_version=case.get("skill_version", "v1"),
            source_text=source,
            failure_context=case.get("failure_context", ""),
            repair_instruction=case.get("repair_instruction", ""),
            repaired_text=repaired,
            quality_before=case.get("quality_before", 0.0),
            quality_after=case.get("quality_after", 0.0),
            data_retention_rate=case.get("data_retention_rate", 0.0),
            data_loss_percentage=case.get("data_loss_percentage", 100.0),
            required_field_preservation_rate=case.get("required_field_preservation_rate", 0.0),
            section_preservation_rate=case.get("section_preservation_rate", 0.0),
            retention_verdict=case.get("retention_verdict", "FAIL"),
            repair_verdict=case.get("repair_verdict", "BLOCKED"),
        )

    def _record_to_example(self, rec: Dict) -> Optional[TrainingExample]:
        """Convert a flat record dict to a TrainingExample."""
        source = rec.get("source_text", "")
        repaired = rec.get("repaired_text", "")
        if not source or not repaired:
            return None

        return self.build_single(
            document_id=rec.get("document_id", "unknown"),
            archetype=rec.get("archetype", "unknown"),
            failure_class=rec.get("failure_class", ""),
            skill_id=rec.get("skill_id", ""),
            skill_version=rec.get("skill_version", "v1"),
            source_text=source,
            failure_context=rec.get("failure_context", ""),
            repair_instruction=rec.get("repair_instruction", ""),
            repaired_text=repaired,
            quality_before=rec.get("quality_before", 0.0),
            quality_after=rec.get("quality_after", 0.0),
            data_retention_rate=rec.get("data_retention_rate", 0.0),
            data_loss_percentage=rec.get("data_loss_percentage", 100.0),
            required_field_preservation_rate=rec.get("required_field_preservation_rate", 0.0),
            section_preservation_rate=rec.get("section_preservation_rate", 0.0),
            retention_verdict=rec.get("retention_verdict", "FAIL"),
            repair_verdict=rec.get("repair_verdict", "BLOCKED"),
        )
