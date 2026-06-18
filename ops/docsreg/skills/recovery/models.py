"""PHASE 8 Recovery Models — data structures for skill recovery analysis and proposals."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from ops.docsreg.skills.testing.models import SkillName, SkillVerdict, DataRetentionStatus


class LossCategory(Enum):
    """Classification of what was lost during repair."""
    SECTION_LOSS = "section_loss"
    FIELD_LOSS = "field_loss"
    REFERENCE_LOSS = "reference_loss"
    MIXED_LOSS = "mixed_loss"


class RecoveryStrategy(Enum):
    """Available recovery strategies for blocked skills."""
    PRESERVE_BEFORE_REPAIR = "preserve_before_repair"
    SECTION_LEVEL_DIFF = "section_level_diff"
    FIELD_MERGE_BACK = "field_merge_back"
    REFERENCE_REBIND = "reference_rebind"
    CHUNKED_REPAIR = "chunked_repair"
    CONSERVATIVE_REPAIR = "conservative_repair"


class RecoveryVerdict(Enum):
    """Outcome of recovery simulation."""
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class RetentionDiagnosis:
    """Diagnosis of a single retention failure."""
    skill_name: SkillName
    test_case_id: str
    original_loss_pct: float
    loss_category: LossCategory
    sections_lost: List[str]
    fields_lost: List[str]
    references_lost: List[str]
    root_cause: str
    severity: str  # "critical" (>3%), "moderate" (2-3%), "marginal" (just over 2%)


@dataclass(frozen=True)
class RecoveryProposal:
    """A proposed recovery strategy for a blocked skill."""
    skill_name: SkillName
    test_case_id: str
    diagnosis: RetentionDiagnosis
    strategy: RecoveryStrategy
    rationale: str
    expected_loss_reduction_pct: float
    estimated_new_loss_pct: float
    confidence: float  # 0.0-1.0


@dataclass(frozen=True)
class RecoveryOutcome:
    """Result of simulating a recovery strategy."""
    proposal: RecoveryProposal
    simulated_loss_pct: float
    original_loss_pct: float
    improvement_pct: float
    passes_retention_gate: bool  # simulated_loss_pct <= 2.0
    verdict: RecoveryVerdict
    simulation_notes: str


@dataclass(frozen=True)
class SkillRecoveryReport:
    """Complete recovery report for a single skill."""
    skill_name: SkillName
    blocked_case_count: int
    diagnoses: List[RetentionDiagnosis]
    proposals: List[RecoveryProposal]
    outcomes: List[RecoveryOutcome]
    overall_verdict: RecoveryVerdict
    recovery_feasibility: str  # "high", "medium", "low"


@dataclass(frozen=True)
class RecoverySummary:
    """Summary across all blocked skills."""
    total_blocked_skills: int
    total_blocked_cases: int
    resolved_count: int
    partially_resolved_count: int
    unresolved_count: int
    overall_verdict: RecoveryVerdict
    recommendation: str
    skill_reports: List[SkillRecoveryReport]
