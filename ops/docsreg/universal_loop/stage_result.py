"""Stage execution result tracking.

Frozen dataclass captures immutable execution results enabling audit trail.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional


class StageOutcome(StrEnum):
    """Outcome classification for each stage."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StageResult:
    """Immutable result from single stage execution."""

    stage_name: str
    outcome: StageOutcome
    started_at: datetime
    completed_at: datetime
    quality_before: float
    quality_after: float
    content_before: str
    content_after: str
    errors: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    failure_detected: bool = False
    failure_class: Optional[str] = None

    @property
    def success(self) -> bool:
        """Stage succeeded."""
        return self.outcome == StageOutcome.SUCCESS

    @property
    def failed(self) -> bool:
        """Stage failed."""
        return self.outcome == StageOutcome.FAILURE

    @property
    def duration_seconds(self) -> float:
        """Execution duration in seconds."""
        return (self.completed_at - self.started_at).total_seconds()

    @property
    def quality_delta(self) -> float:
        """Quality change from before to after."""
        return self.quality_after - self.quality_before
