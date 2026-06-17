"""Meta-improvement controller for failure-driven document repair routing."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import uuid4

from ops.docsreg.archetype_policy_adapter.failure_classifier import FailureClass
from ops.docsreg.archetype_policy_adapter.failure_events import FailureEvent


class RepairDecision(Enum):
    """Decision outcome from meta-improvement controller."""
    ACCEPT_REPAIR = "ACCEPT_REPAIR"  # Proceed with repair execution
    DEFER_REPAIR = "DEFER_REPAIR"  # Defer to next cycle
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"  # Requires manual review
    SKIP_REPAIR = "SKIP_REPAIR"  # No repair attempted


class RepairPriority(Enum):
    """Priority level for repair execution."""
    CRITICAL = "CRITICAL"  # Execute immediately
    HIGH = "HIGH"  # Execute in current cycle
    MEDIUM = "MEDIUM"  # Execute if resources available
    LOW = "LOW"  # Execute in next cycle


@dataclass(frozen=True)
class RepairAction:
    """Immutable record of repair action decision."""

    action_id: str
    event_id: str
    failure_class: FailureClass
    decision: RepairDecision
    priority: RepairPriority
    target_handler: str
    reasoning: str
    timestamp: datetime
    max_retries: int = 3


@dataclass(frozen=True)
class RepairOutcome:
    """Immutable record of repair execution result."""

    outcome_id: str
    action_id: str
    event_id: str
    success: bool
    attempt_count: int
    error_message: Optional[str]
    repair_time_ms: int
    timestamp: datetime


class MetaImprovementController:
    """Routes failure events to appropriate repair handlers based on decision policy."""

    def __init__(self):
        """Initialize controller with empty action and outcome tracking."""
        self._actions: List[RepairAction] = []
        self._outcomes: List[RepairOutcome] = []
        self._decision_policy = self._build_decision_policy()

    def _build_decision_policy(self) -> Dict[FailureClass, tuple]:
        """Build policy mapping failure classes to (decision, priority, handler).

        Returns:
            Dict mapping FailureClass to (RepairDecision, RepairPriority, handler_name)
        """
        return {
            FailureClass.TIMEOUT: (
                RepairDecision.ACCEPT_REPAIR,
                RepairPriority.HIGH,
                "timeout_recovery_handler",
            ),
            FailureClass.RESOURCE_EXHAUSTION: (
                RepairDecision.DEFER_REPAIR,
                RepairPriority.CRITICAL,
                "resource_recovery_handler",
            ),
            FailureClass.BUG: (
                RepairDecision.ESCALATE_TO_HUMAN,
                RepairPriority.CRITICAL,
                "skill_handler",
            ),
            FailureClass.NETWORK_ERROR: (
                RepairDecision.ACCEPT_REPAIR,
                RepairPriority.MEDIUM,
                "network_recovery_handler",
            ),
            FailureClass.POLICY_VIOLATION: (
                RepairDecision.ACCEPT_REPAIR,
                RepairPriority.HIGH,
                "validation_repair_handler",
            ),
            FailureClass.OTHER: (
                RepairDecision.SKIP_REPAIR,
                RepairPriority.LOW,
                "unclassified_handler",
            ),
        }

    def make_repair_decision(self, event: FailureEvent) -> RepairAction:
        """Make repair decision based on failure event.

        Args:
            event: FailureEvent to make decision for

        Returns:
            RepairAction containing decision, priority, and target handler
        """
        policy_entry = self._decision_policy.get(
            event.failure_class,
            (
                RepairDecision.SKIP_REPAIR,
                RepairPriority.LOW,
                "unclassified_handler",
            ),
        )
        decision, priority, handler = policy_entry

        # Build reasoning based on event and policy
        reasoning = self._build_reasoning(event, decision, priority)

        action = RepairAction(
            action_id=str(uuid4()),
            event_id=event.event_id,
            failure_class=event.failure_class,
            decision=decision,
            priority=priority,
            target_handler=handler,
            reasoning=reasoning,
            timestamp=datetime.utcnow(),
            max_retries=3 if decision == RepairDecision.ACCEPT_REPAIR else 1,
        )

        self._actions.append(action)
        return action

    def _build_reasoning(
        self, event: FailureEvent, decision: RepairDecision, priority: RepairPriority
    ) -> str:
        """Build human-readable reasoning for repair decision.

        Args:
            event: FailureEvent being processed
            decision: RepairDecision made
            priority: RepairPriority assigned

        Returns:
            Reasoning string explaining the decision
        """
        return f"Failure class {event.failure_class.value} at step {event.repair_step} routed to {decision.value} with {priority.value} priority. Action required: {event.action_required}. Suggested: {event.suggested_action}"

    def record_repair_outcome(
        self,
        action: RepairAction,
        success: bool,
        attempt_count: int,
        repair_time_ms: int,
        error_message: Optional[str] = None,
    ) -> RepairOutcome:
        """Record outcome of repair execution attempt.

        Args:
            action: RepairAction that was executed
            success: Whether repair was successful
            attempt_count: Number of attempts made
            repair_time_ms: Execution time in milliseconds
            error_message: Error message if repair failed

        Returns:
            RepairOutcome record that was stored
        """
        outcome = RepairOutcome(
            outcome_id=str(uuid4()),
            action_id=action.action_id,
            event_id=action.event_id,
            success=success,
            attempt_count=attempt_count,
            error_message=error_message,
            repair_time_ms=repair_time_ms,
            timestamp=datetime.utcnow(),
        )

        self._outcomes.append(outcome)
        return outcome

    def get_actions_by_decision(
        self, decision: RepairDecision, max_age_minutes: int = 60
    ) -> List[RepairAction]:
        """Get repair actions filtered by decision type.

        Args:
            decision: RepairDecision to filter by
            max_age_minutes: Only return actions from last N minutes

        Returns:
            List of matching RepairAction records
        """
        cutoff = datetime.utcnow() - __import__("datetime").timedelta(
            minutes=max_age_minutes
        )
        return [
            a
            for a in self._actions
            if a.decision == decision and a.timestamp >= cutoff
        ]

    def get_actions_by_priority(
        self, priority: RepairPriority, max_age_minutes: int = 60
    ) -> List[RepairAction]:
        """Get repair actions filtered by priority level.

        Args:
            priority: RepairPriority to filter by
            max_age_minutes: Only return actions from last N minutes

        Returns:
            List of matching RepairAction records
        """
        cutoff = datetime.utcnow() - __import__("datetime").timedelta(
            minutes=max_age_minutes
        )
        return [
            a
            for a in self._actions
            if a.priority == priority and a.timestamp >= cutoff
        ]

    def get_outcomes_for_action(self, action_id: str) -> List[RepairOutcome]:
        """Get all outcomes associated with a repair action.

        Args:
            action_id: Action identifier to retrieve outcomes for

        Returns:
            List of RepairOutcome records for the action
        """
        return [o for o in self._outcomes if o.action_id == action_id]

    def get_success_rate(self, max_age_minutes: int = 60) -> float:
        """Calculate repair success rate for recent outcomes.

        Args:
            max_age_minutes: Only consider outcomes from last N minutes

        Returns:
            Success rate as float between 0.0 and 1.0
        """
        cutoff = datetime.utcnow() - __import__("datetime").timedelta(
            minutes=max_age_minutes
        )
        recent_outcomes = [o for o in self._outcomes if o.timestamp >= cutoff]

        if not recent_outcomes:
            return 0.0

        successes = sum(1 for o in recent_outcomes if o.success)
        return successes / len(recent_outcomes)
