"""Failure event collection and emission for learning loop integration."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import uuid4

from ops.docsreg.archetype_policy_adapter.failure_classifier import (
    DocumentFailure,
    FailureClass,
)


@dataclass(frozen=True)
class FailureEvent:
    """Immutable record of failure event for learning loop."""

    event_id: str
    failure_id: str
    document_id: Optional[str]
    failure_class: FailureClass
    repair_step: str
    timestamp: datetime
    action_required: bool
    suggested_action: Optional[str] = None


class FailureEventCollector:
    """Collects and aggregates failure events for learning loop."""

    def __init__(self):
        """Initialize event collector with empty event store."""
        self._events: List[FailureEvent] = []

    def _suggest_action(self, failure_class: FailureClass) -> Optional[str]:
        """Suggest remedial action based on failure class.

        Args:
            failure_class: The classified failure type

        Returns:
            Suggested action string or None
        """
        action_map = {
            FailureClass.TIMEOUT: "retry_with_timeout_increase",
            FailureClass.RESOURCE_EXHAUSTION: "escalate_to_resource_handler",
            FailureClass.BUG: "escalate_to_skill_handler",
            FailureClass.NETWORK_ERROR: "retry_with_backoff",
            FailureClass.POLICY_VIOLATION: "escalate_to_validation_repair",
            FailureClass.OTHER: None,
        }
        return action_map.get(failure_class)

    def emit_failure_event(self, failure: DocumentFailure) -> FailureEvent:
        """Emit failure event from document failure record.

        Args:
            failure: DocumentFailure to convert to event

        Returns:
            FailureEvent that was created and stored
        """
        # Determine if action is required based on failure class
        action_required = failure.failure_class in (
            FailureClass.TIMEOUT,
            FailureClass.RESOURCE_EXHAUSTION,
            FailureClass.BUG,
        )

        # Suggest remedial action
        suggested_action = self._suggest_action(failure.failure_class)

        # Create event
        event = FailureEvent(
            event_id=str(uuid4()),
            failure_id=failure.failure_id,
            document_id=failure.document_id,
            failure_class=failure.failure_class,
            repair_step=failure.repair_step,
            timestamp=failure.timestamp,
            action_required=action_required,
            suggested_action=suggested_action,
        )

        # Store event
        self._events.append(event)

        return event

    def collect_events(
        self,
        document_id: Optional[str] = None,
        minutes: int = 60,
    ) -> List[FailureEvent]:
        """Collect failure events within time window, optionally filtered by document.

        Args:
            document_id: Optional document identifier to filter by
            minutes: Time window in minutes (default 60)

        Returns:
            List of FailureEvent records matching criteria
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
        events = [e for e in self._events if e.timestamp >= cutoff_time]

        if document_id is not None:
            events = [e for e in events if e.document_id == document_id]

        return events

    def get_event_count_by_class(
        self,
        document_id: Optional[str] = None,
        minutes: int = 60,
    ) -> Dict[str, int]:
        """Get count of events grouped by failure class.

        Args:
            document_id: Optional document identifier to filter by
            minutes: Time window in minutes (default 60)

        Returns:
            Dict mapping failure class name to count
        """
        events = self.collect_events(document_id, minutes)
        counts = {}

        for event in events:
            class_name = event.failure_class.value
            counts[class_name] = counts.get(class_name, 0) + 1

        return counts
