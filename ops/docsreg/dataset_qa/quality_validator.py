"""PHASE 9 Quality Validator — enforces dataset admission rules."""
from typing import List

from ops.docsreg.dataset_qa.models import (
    TrainingExample,
    DatasetAdmissionResult,
    AdmissionVerdict,
    RejectionReason,
)


# Admission thresholds
MIN_DATA_RETENTION_RATE = 0.98
MAX_DATA_LOSS_PERCENTAGE = 2.0
MIN_REQUIRED_FIELD_PRESERVATION = 1.0
MIN_SECTION_PRESERVATION = 0.98


class QualityValidator:
    """Validates training examples against dataset admission rules.

    An example is ACCEPTED only if ALL conditions pass:
    - repair_verdict == PROMOTED
    - retention_verdict == PASS
    - data_retention_rate >= 0.98
    - data_loss_percentage <= 2.0
    - required_field_preservation_rate == 1.0
    - section_preservation_rate >= 0.98
    - quality_delta > 0
    - input_sha256 != output_sha256
    - source_text != repaired_text
    """

    def validate(self, example: TrainingExample) -> DatasetAdmissionResult:
        """Validate a single example against admission rules."""
        reasons: List[RejectionReason] = []

        # Repair verdict check
        if example.repair_verdict != "PROMOTED":
            reasons.append(RejectionReason.REPAIR_NOT_PROMOTED)

        # Retention verdict check
        if example.retention_verdict == "FAIL":
            reasons.append(RejectionReason.RETENTION_FAIL)

        # Data retention rate
        if example.data_retention_rate < MIN_DATA_RETENTION_RATE:
            reasons.append(RejectionReason.RETENTION_RATE_LOW)

        # Data loss percentage
        if example.data_loss_percentage > MAX_DATA_LOSS_PERCENTAGE:
            reasons.append(RejectionReason.LOSS_TOO_HIGH)

        # Required field preservation
        if example.required_field_preservation_rate < MIN_REQUIRED_FIELD_PRESERVATION:
            reasons.append(RejectionReason.FIELD_PRESERVATION_LOW)

        # Section preservation
        if example.section_preservation_rate < MIN_SECTION_PRESERVATION:
            reasons.append(RejectionReason.SECTION_PRESERVATION_LOW)

        # Quality improvement
        if example.quality_delta <= 0:
            reasons.append(RejectionReason.QUALITY_NO_IMPROVEMENT)

        # Content identity
        if example.input_sha256 == example.output_sha256:
            reasons.append(RejectionReason.IDENTICAL_INPUT_OUTPUT)
        if example.source_text == example.repaired_text:
            reasons.append(RejectionReason.IDENTICAL_INPUT_OUTPUT)

        # Empty content
        if not example.source_text.strip():
            reasons.append(RejectionReason.EMPTY_SOURCE)
        if not example.repaired_text.strip():
            reasons.append(RejectionReason.EMPTY_REPAIR)

        # Missing metadata
        if not example.failure_class.strip():
            reasons.append(RejectionReason.MISSING_FAILURE_CLASS)
        if not example.skill_id.strip():
            reasons.append(RejectionReason.MISSING_SKILL_ID)

        # Invalid hashes
        if len(example.input_sha256) != 64 or len(example.output_sha256) != 64:
            reasons.append(RejectionReason.INVALID_HASH)

        # Deduplicate reasons
        reasons = list(dict.fromkeys(reasons))

        verdict = AdmissionVerdict.ACCEPTED if not reasons else AdmissionVerdict.REJECTED
        notes = ""
        if reasons:
            notes = f"Rejected for {len(reasons)} reason(s): {', '.join(r.value for r in reasons)}"

        return DatasetAdmissionResult(
            example_id=example.example_id,
            verdict=verdict,
            rejection_reasons=reasons,
            notes=notes,
        )

    def validate_all(self, examples: List[TrainingExample]) -> List[DatasetAdmissionResult]:
        """Validate all examples."""
        return [self.validate(ex) for ex in examples]

    def filter_accepted(
        self,
        examples: List[TrainingExample],
        results: List[DatasetAdmissionResult],
    ) -> List[TrainingExample]:
        """Return only accepted examples."""
        accepted_ids = {
            r.example_id for r in results if r.verdict == AdmissionVerdict.ACCEPTED
        }
        return [ex for ex in examples if ex.example_id in accepted_ids]

    def filter_rejected(
        self,
        examples: List[TrainingExample],
        results: List[DatasetAdmissionResult],
    ) -> List[TrainingExample]:
        """Return only rejected examples."""
        rejected_ids = {
            r.example_id for r in results if r.verdict == AdmissionVerdict.REJECTED
        }
        return [ex for ex in examples if ex.example_id in rejected_ids]
