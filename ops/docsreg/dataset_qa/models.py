"""PHASE 9 Dataset QA Models — data structures for training dataset preparation."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class AdmissionVerdict(Enum):
    """Whether an example is admitted to the training dataset."""
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LeakageType(Enum):
    """Types of data leakage that disqualify an example."""
    PERSON_NAME = "person_name"
    EMAIL = "email"
    PHONE = "phone"
    COMPANY_NAME = "company_name"
    DOCUMENT_OWNER = "document_owner"
    APPROVER_ROLE = "approver_role"
    LOGO_MARKER = "logo_marker"
    INTERNAL_ID = "internal_id"
    AUTHOR_METADATA = "author_metadata"
    LAST_MODIFIED_BY = "last_modified_by"
    COMMENTS = "comments"
    TRACKED_CHANGES = "tracked_changes"
    HIDDEN_TEXT = "hidden_text"
    DOCUMENT_PATH = "document_path"
    AI_MARKER = "ai_marker"


class RejectionReason(Enum):
    """Reasons an example may be rejected."""
    RETENTION_FAIL = "retention_fail"
    REQUIRED_FIELD_LOST = "required_field_lost"
    REQUIRED_SECTION_LOST = "required_section_lost"
    QUALITY_NO_IMPROVEMENT = "quality_no_improvement"
    EMPTY_SOURCE = "empty_source"
    EMPTY_REPAIR = "empty_repair"
    DUPLICATE_CONTENT = "duplicate_content"
    PII_LEAKAGE = "pii_leakage"
    AI_MARKER_LEAKAGE = "ai_marker_leakage"
    INVALID_HASH = "invalid_hash"
    MISSING_FAILURE_CLASS = "missing_failure_class"
    MISSING_SKILL_ID = "missing_skill_id"
    REPAIR_NOT_PROMOTED = "repair_not_promoted"
    RETENTION_RATE_LOW = "retention_rate_low"
    LOSS_TOO_HIGH = "loss_too_high"
    FIELD_PRESERVATION_LOW = "field_preservation_low"
    SECTION_PRESERVATION_LOW = "section_preservation_low"
    IDENTICAL_INPUT_OUTPUT = "identical_input_output"


@dataclass
class TrainingExample:
    """A single training example for the repair dataset."""
    example_id: str
    document_id: str
    archetype: str
    failure_class: str
    skill_id: str
    skill_version: str
    source_text: str
    failure_context: str
    repair_instruction: str
    repaired_text: str
    quality_before: float
    quality_after: float
    quality_delta: float
    data_retention_rate: float
    data_loss_percentage: float
    required_field_preservation_rate: float
    section_preservation_rate: float
    retention_verdict: str  # "PASS", "ADVISORY", "FAIL"
    repair_verdict: str  # "PROMOTED", "BLOCKED", "ADVISORY"
    input_sha256: str
    output_sha256: str
    created_at: str  # ISO 8601


@dataclass
class LeakageFinding:
    """A single leakage detection finding."""
    leakage_type: LeakageType
    field_name: str  # Which field contained the leakage
    matched_text: str
    replacement: str
    position: int  # Character offset in the field


@dataclass
class DatasetAdmissionResult:
    """Result of evaluating an example for dataset admission."""
    example_id: str
    verdict: AdmissionVerdict
    rejection_reasons: List[RejectionReason] = field(default_factory=list)
    leakage_findings: List[LeakageFinding] = field(default_factory=list)
    notes: str = ""


@dataclass
class DeduplicationResult:
    """Result of deduplication across the dataset."""
    total_before: int
    total_after: int
    duplicates_removed: int
    exact_duplicates: int
    normalized_duplicates: int
    near_duplicates: int
    same_doc_class_output: int
    kept_example_ids: List[str] = field(default_factory=list)
    removed_example_ids: List[str] = field(default_factory=list)


@dataclass
class BalanceBucket:
    """Statistics for a single bucket in balance analysis."""
    key: str
    count: int
    percentage: float


@dataclass
class BalanceReport:
    """Balance analysis across dataset dimensions."""
    total_examples: int
    by_archetype: List[BalanceBucket] = field(default_factory=list)
    by_failure_class: List[BalanceBucket] = field(default_factory=list)
    by_skill_id: List[BalanceBucket] = field(default_factory=list)
    by_verdict: List[BalanceBucket] = field(default_factory=list)
    by_quality_delta_bucket: List[BalanceBucket] = field(default_factory=list)
    by_retention_bucket: List[BalanceBucket] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    passes_balance_gate: bool = True


@dataclass
class DatasetManifest:
    """Manifest for the complete dataset output."""
    phase: str = "PHASE_9"
    generated_at: str = ""
    training_count: int = 0
    validation_count: int = 0
    rejected_count: int = 0
    total_processed: int = 0
    split_strategy: str = "document_id"
    split_ratio: str = "80/20"
    train_document_ids: List[str] = field(default_factory=list)
    validation_document_ids: List[str] = field(default_factory=list)
    leakage_findings_count: int = 0
    duplicates_removed: int = 0
    balance_violations: List[str] = field(default_factory=list)
    passes_all_gates: bool = False


@dataclass
class DatasetQualityReport:
    """Overall quality report for the dataset."""
    total_examples_processed: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    acceptance_rate: float = 0.0
    avg_quality_delta: float = 0.0
    avg_retention_rate: float = 0.0
    min_retention_rate: float = 0.0
    max_loss_percentage: float = 0.0
    all_retention_above_98: bool = False
    all_quality_delta_positive: bool = False
    zero_pii_leakage: bool = False
    zero_duplicates: bool = False
    passes_quality_gate: bool = False
    readiness_checklist: Dict[str, bool] = field(default_factory=dict)
