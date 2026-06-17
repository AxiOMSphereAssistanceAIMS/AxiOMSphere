"""Execution context and dependencies for universal improvement loop.

Centralizes execution state and pluggable dependencies.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ops.docsreg.universal_loop.contracts import (
    ContentAuditor,
    DocumentGenerator,
    QualityScorer,
    QualityValidator,
    RepairService,
    SnapshotBuilder,
)


@dataclass
class LoopDependencies:
    """Injected dependencies for loop execution."""

    generator: DocumentGenerator
    validator: QualityValidator
    scorer: QualityScorer
    auditor: ContentAuditor
    repair_service: RepairService
    snapshot_builder: SnapshotBuilder
    event_bus: Optional[Any] = None
    logger: Optional[Any] = None


@dataclass
class UniversalLoopContext:
    """Mutable execution state for bi-nested improvement loop."""

    document_id: str
    archetype_type: str
    content: str
    quality_score: float
    iteration_count: int = 0
    repair_attempts: int = 0
    validation_failures: int = 0
    failure_history: list[str] = field(default_factory=list)
    quality_history: list[float] = field(default_factory=list)
    actions_executed: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)

    def record_action(self, action: str) -> None:
        """Record executed action."""
        self.actions_executed.append(action)

    def record_quality(self, score: float) -> None:
        """Record quality score in history."""
        self.quality_history.append(score)
        self.quality_score = score

    def record_failure(self, failure: str) -> None:
        """Record failure event."""
        self.failure_history.append(failure)
