"""Data models for PHASE 7 skill testing framework."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List


class SkillName(Enum):
    """Enumeration of skill suites under test."""
    FIX_TIMEOUT = "FIX_TIMEOUT"
    FIX_STRUCTURE = "FIX_STRUCTURE"
    FIX_POLICY_VIOLATION = "FIX_POLICY_VIOLATION"
    FIX_QUALITY_GATE = "FIX_QUALITY_GATE"
    FIX_DATA_LOSS = "FIX_DATA_LOSS"
    FIX_RESOURCE_EXHAUSTION = "FIX_RESOURCE_EXHAUSTION"


class SkillVerdict(Enum):
    """Verdict on skill test case execution."""
    PROMOTED = "PROMOTED"  # All metrics met, no FAIL cases
    ADVISORY = "ADVISORY"  # Some metrics below target, no FAIL cases
    BLOCKED = "BLOCKED"    # Any FAIL case present (data loss > 2.0%)


class DataRetentionStatus(Enum):
    """Data retention validation outcome."""
    PASS = "pass"          # ≤ 1.5% token loss
    ADVISORY = "advisory"  # 1.5% < loss ≤ 2.0%
    FAIL = "fail"          # > 2.0% token loss


@dataclass(frozen=True)
class SkillTestInput:
    """Immutable input to a skill test case."""

    skill_name: SkillName
    test_case_id: str  # e.g., "timeout_001"
    scenario_description: str
    input_content: str  # The document content before repair
    input_hash: str    # SHA256 of input_content
    expected_repair_type: str  # e.g., "retry_with_backoff", "structural_fix"
    archetype_type: str  # Document archetype


@dataclass(frozen=True)
class SkillTestOutput:
    """Immutable output of skill execution."""

    test_case_id: str
    repaired_content: str  # Content after repair
    output_hash: str  # SHA256 of repaired_content
    repair_applied: bool  # Whether repair was actually performed
    quality_before: float  # Quality score before repair (0.0–1.0)
    quality_after: float   # Quality score after repair (0.0–1.0)
    quality_delta: float   # quality_after - quality_before
    repair_time_ms: int    # Milliseconds to execute repair


@dataclass(frozen=True)
class DataRetentionReport:
    """Immutable data retention validation result."""

    status: DataRetentionStatus
    token_loss_percentage: float
    sections_lost: List[str] = field(default_factory=list)
    fields_lost: List[str] = field(default_factory=list)
    references_lost: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillTestCase:
    """Immutable record of a single skill test case execution."""

    skill_name: SkillName
    test_case_id: str
    scenario_description: str
    test_input: SkillTestInput
    test_output: SkillTestOutput
    retention_report: DataRetentionReport
    executed_at: datetime
    verdict: SkillVerdict  # PROMOTED, ADVISORY, or BLOCKED
    reasoning: str  # Why this verdict was assigned

    @property
    def passed_retention_gate(self) -> bool:
        """Returns True if retention status is not FAIL."""
        return self.retention_report.status != DataRetentionStatus.FAIL


@dataclass(frozen=True)
class SkillSuiteResult:
    """Immutable aggregation of 5 test cases for a single skill."""

    skill_name: SkillName
    total_cases: int  # Always 5 for PHASE 7
    cases: List[SkillTestCase]  # The 5 test cases
    cases_promoted: int
    cases_advisory: int
    cases_blocked: int
    overall_verdict: SkillVerdict  # PROMOTED, ADVISORY, or BLOCKED
    executed_at: datetime

    @property
    def cases_without_fail(self) -> int:
        """Count of cases that passed retention gate (status != FAIL)."""
        return sum(1 for c in self.cases if c.passed_retention_gate)

    @property
    def has_any_fail_verdict(self) -> bool:
        """True if any case has BLOCKED verdict (due to FAIL retention)."""
        return any(c.verdict == SkillVerdict.BLOCKED for c in self.cases)
