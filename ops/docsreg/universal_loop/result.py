"""Final result from universal improvement loop execution.

Immutable result suitable for JSON serialization and archival.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ops.docsreg.universal_loop.stage_result import StageResult
from ops.docsreg.universal_loop.terminal_state import TerminalState


@dataclass(frozen=True)
class UniversalLoopResult:
    """Immutable aggregated result from loop execution."""

    document_id: str
    archetype_type: str
    terminal_state: TerminalState
    started_at: datetime
    completed_at: datetime
    quality_initial: float
    quality_final: float
    iterations: int
    stage_results: list[StageResult] = field(default_factory=list)
    failure_classes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    actions_executed: list[str] = field(default_factory=list)
    data_retention_rate: float = 100.0
    data_loss_percentage: float = 0.0
    requires_operator_decision: bool = False
    evidence_package: dict[str, Any] = field(default_factory=dict)
    terminal_reason: str = ""

    @property
    def quality_delta(self) -> float:
        """Quality change from initial to final."""
        return self.quality_final - self.quality_initial

    @property
    def success(self) -> bool:
        """Loop succeeded."""
        return self.terminal_state in (
            TerminalState.READY_FOR_REVIEW,
            TerminalState.QUALITY_TARGET_EXCEEDED,
            TerminalState.READY_FOR_BEST_VERSION_SELECTION,
        )

    @property
    def duration_seconds(self) -> float:
        """Total execution duration."""
        return (self.completed_at - self.started_at).total_seconds()
