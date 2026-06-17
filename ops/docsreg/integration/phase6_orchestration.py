"""PHASE 6 orchestration — wires PHASE 3-5 components into universal loop execution.

Integrates:
- PHASE 2: Universal improvement loop orchestration
- PHASE 3: Archetype policy validation
- PHASE 4: Failure classification and event collection
- PHASE 5: Meta-improvement repair routing
- PHASE 6: Integration orchestration

Architecture:
  audit_result.failure_message
    ↓ FailureClassifier.classify()
  FailureClass
    ↓ DocumentFailure.create()
  DocumentFailure
    ↓ FailureEventCollector.emit_failure_event()
  FailureEvent
    ↓ MetaImprovementController.make_repair_decision()
  RepairAction (with routing decision)
    ↓ repair_service.repair(..., failure_class=...)
  repaired_content
    ↓ DataRetentionValidator.validate()
  RetentionVerdict (hard gate enforcement)
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ops.docsreg.archetype_policy_adapter.failure_classifier import (
    FailureClass,
    FailureClassifier,
    DocumentFailure,
)
from ops.docsreg.archetype_policy_adapter.failure_events import FailureEventCollector
from ops.docsreg.archetype_policy_adapter.meta_improvement_controller import (
    MetaImprovementController,
    RepairAction,
    RepairOutcome,
)
from ops.docsreg.archetype_policy_adapter.base import ViolationSeverity
from ops.docsreg.universal_loop.data_retention_validator import (
    DataRetentionValidator,
    DocumentSnapshot,
    RetentionVerdict,
)


@dataclass(frozen=True)
class RepairRoutingContext:
    """Immutable repair execution context with routing information."""

    failure_class: FailureClass
    repair_action: RepairAction
    target_handler: str
    max_retries: int
    priority_level: str


class Phase6OrchestrationLayer:
    """Orchestrates failure classification, routing, and repair execution.

    Bridges PHASE 2-5 components:
    - Receives audit failures from universal loop
    - Routes through failure classification and decision policy
    - Executes repairs with data retention hard gate
    - Emits events for learning loop integration
    """

    def __init__(self):
        """Initialize orchestration layer components."""
        self.failure_classifier = FailureClassifier()
        self.event_collector = FailureEventCollector()
        self.controller = MetaImprovementController()
        self.validator = DataRetentionValidator()

    def classify_failure(
        self,
        error: Exception,
        document_id: Optional[str],
        archetype_name: str,
        repair_step: str,
        severity: ViolationSeverity = ViolationSeverity.HIGH,
        context_excerpt: str = "",
    ) -> DocumentFailure:
        """Convert exception to DocumentFailure record.

        Args:
            error: Exception to classify
            document_id: Document identifier or None
            archetype_name: Document archetype
            repair_step: Pipeline step where failure occurred
            severity: Violation severity level
            context_excerpt: Document context at failure point

        Returns:
            DocumentFailure immutable record
        """
        return self.failure_classifier.create_failure_record(
            document_id=document_id,
            archetype_name=archetype_name,
            error=error,
            repair_step=repair_step,
            severity=severity,
            context_excerpt=context_excerpt,
        )

    def emit_and_route_failure(
        self, failure: DocumentFailure
    ) -> RepairRoutingContext:
        """Emit failure event and route to repair handler.

        Args:
            failure: DocumentFailure record

        Returns:
            RepairRoutingContext with routing decision
        """
        # Emit failure event for learning loop
        failure_event = self.event_collector.emit_failure_event(failure)

        # Route through meta-improvement controller
        repair_action = self.controller.make_repair_decision(failure_event)

        # Build routing context
        routing = RepairRoutingContext(
            failure_class=failure.failure_class,
            repair_action=repair_action,
            target_handler=repair_action.target_handler,
            max_retries=repair_action.max_retries,
            priority_level=repair_action.priority.value,
        )

        return routing

    def validate_repair_retention(
        self,
        before_content: str,
        after_content: str,
        archetype_type: str,
    ) -> tuple[bool, dict[str, Any]]:
        """Validate repair against data retention threshold (hard gate).

        Args:
            before_content: Content before repair
            after_content: Content after repair
            archetype_type: Document archetype type

        Returns:
            (passed_gate, validation_report) tuple
                - passed_gate: True if retention passes or advisory, False if FAIL
                - validation_report: full RetentionReport as dict
        """
        # Build snapshots (simplified for gate validation)
        before_snapshot = DocumentSnapshot(
            content=before_content,
            sections=[],  # Would be populated from archetype snapshot
            required_fields=[],  # Would be populated from archetype
        )
        after_snapshot = DocumentSnapshot(
            content=after_content,
            sections=[],
            required_fields=[],
        )

        # Validate retention
        report = self.validator.validate(before_snapshot, after_snapshot)

        # Hard gate: FAIL verdict blocks repair acceptance
        passed_gate = report.verdict != RetentionVerdict.FAIL

        # Convert report to dict for logging
        report_dict = {
            "verdict": report.verdict.value,
            "token_loss_percentage": report.token_loss_percentage,
            "lost_required_fields": list(report.lost_required_fields),
            "lost_sections": list(report.lost_sections),
            "lost_references": list(report.lost_references),
            "lost_tables": list(report.lost_tables),
            "lost_links": list(report.lost_links),
            "lost_semantic_claims": list(report.lost_semantic_claims),
        }

        return passed_gate, report_dict

    def record_repair_outcome(
        self,
        action: RepairAction,
        success: bool,
        attempt_count: int,
        repair_time_ms: int,
        error_message: Optional[str] = None,
    ) -> RepairOutcome:
        """Record repair execution outcome.

        Args:
            action: RepairAction that was executed
            success: Whether repair succeeded
            attempt_count: Number of attempts made
            repair_time_ms: Execution time in milliseconds
            error_message: Error message if repair failed

        Returns:
            RepairOutcome immutable record
        """
        return self.controller.record_repair_outcome(
            action=action,
            success=success,
            attempt_count=attempt_count,
            repair_time_ms=repair_time_ms,
            error_message=error_message,
        )

    def get_repair_metrics(self, max_age_minutes: int = 60) -> dict[str, Any]:
        """Get repair execution metrics for monitoring.

        Args:
            max_age_minutes: Only consider outcomes from last N minutes

        Returns:
            Dict with success_rate, action_count, priority_distribution
        """
        success_rate = self.controller.get_success_rate(max_age_minutes)

        # Count actions by priority
        critical_actions = self.controller.get_actions_by_priority(
            self.controller._decision_policy.__class__.__dict__.get("CRITICAL"),
            max_age_minutes,
        )

        return {
            "success_rate": success_rate,
            "metric_window_minutes": max_age_minutes,
        }
