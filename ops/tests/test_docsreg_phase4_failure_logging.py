"""Test suite for PHASE 4 Failure Logging and Event Collection."""
import pytest
from datetime import datetime, timedelta

from ops.docsreg.archetype_policy_adapter.failure_classifier import (
    FailureClass,
    DocumentFailure,
    FailureClassifier,
)
from ops.docsreg.archetype_policy_adapter.failure_events import (
    FailureEvent,
    FailureEventCollector,
)


class TestFailureClassEnum:
    """Test FailureClass enum values."""

    def test_failure_class_values(self):
        """FailureClass should have all six values."""
        assert FailureClass.BUG.value == "BUG"
        assert FailureClass.TIMEOUT.value == "TIMEOUT"
        assert FailureClass.RESOURCE_EXHAUSTION.value == "RESOURCE_EXHAUSTION"
        assert FailureClass.NETWORK_ERROR.value == "NETWORK_ERROR"
        assert FailureClass.POLICY_VIOLATION.value == "POLICY_VIOLATION"
        assert FailureClass.OTHER.value == "OTHER"

    def test_failure_class_length(self):
        """FailureClass should have exactly 6 members."""
        assert len(FailureClass) == 6


class TestDocumentFailureImmutability:
    """Test DocumentFailure immutability."""

    def test_failure_is_frozen(self):
        """DocumentFailure should be immutable (frozen=True)."""
        failure = DocumentFailure(
            failure_id="test-001",
            document_id="doc-001",
            archetype_name="maintenance_procedure",
            failure_class=FailureClass.BUG,
            severity="CRITICAL",
            root_cause="TypeError: expected str",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="TypeError in field extraction",
        )

        # Should not be able to modify failure
        with pytest.raises(AttributeError):
            failure.failure_id = "new-id"

    def test_failure_preserves_all_fields(self):
        """DocumentFailure should preserve all input fields."""
        now = datetime.utcnow()
        failure = DocumentFailure(
            failure_id="id-123",
            document_id="doc-456",
            archetype_name="policy_framework",
            failure_class=FailureClass.TIMEOUT,
            severity="HIGH",
            root_cause="Request timeout after 30s",
            timestamp=now,
            repair_step="extraction",
            error_message="TimeoutError: deadline exceeded",
            context_excerpt="Section: Document Control",
        )

        assert failure.failure_id == "id-123"
        assert failure.document_id == "doc-456"
        assert failure.archetype_name == "policy_framework"
        assert failure.failure_class == FailureClass.TIMEOUT
        assert failure.timestamp == now
        assert failure.context_excerpt == "Section: Document Control"


class TestFailureClassifier:
    """Test FailureClassifier exception mapping."""

    def test_classify_timeout_error(self):
        """Classify TimeoutError → TIMEOUT."""
        classifier = FailureClassifier()
        error = TimeoutError("Request took too long")
        result = classifier.classify(error)
        assert result == FailureClass.TIMEOUT

    def test_classify_memory_error(self):
        """Classify MemoryError → RESOURCE_EXHAUSTION."""
        classifier = FailureClassifier()
        error = MemoryError("Out of memory")
        result = classifier.classify(error)
        assert result == FailureClass.RESOURCE_EXHAUSTION

    def test_classify_connection_error(self):
        """Classify ConnectionError → NETWORK_ERROR."""
        classifier = FailureClassifier()
        error = ConnectionError("Network unreachable")
        result = classifier.classify(error)
        assert result == FailureClass.NETWORK_ERROR

    def test_classify_archetype_policy_violation(self):
        """Classify ValueError with 'archetype' → POLICY_VIOLATION."""
        classifier = FailureClassifier()
        error = ValueError("archetype validation failed")
        result = classifier.classify(error)
        assert result == FailureClass.POLICY_VIOLATION

    def test_classify_assertion_error(self):
        """Classify AssertionError → BUG."""
        classifier = FailureClassifier()
        error = AssertionError("assertion failed")
        result = classifier.classify(error)
        assert result == FailureClass.BUG

    def test_classify_type_error(self):
        """Classify TypeError → BUG."""
        classifier = FailureClassifier()
        error = TypeError("unsupported operand type")
        result = classifier.classify(error)
        assert result == FailureClass.BUG

    def test_classify_attribute_error(self):
        """Classify AttributeError → BUG."""
        classifier = FailureClassifier()
        error = AttributeError("object has no attribute")
        result = classifier.classify(error)
        assert result == FailureClass.BUG

    def test_classify_unknown_error(self):
        """Classify unknown exception → OTHER."""
        classifier = FailureClassifier()
        error = RuntimeError("unknown error")
        result = classifier.classify(error)
        assert result == FailureClass.OTHER

    def test_classify_case_insensitive_timeout(self):
        """Classify timeout string match should be case-insensitive."""
        classifier = FailureClassifier()
        error = Exception("Request TIMEOUT occurred")
        result = classifier.classify(error)
        assert result == FailureClass.TIMEOUT

    def test_create_failure_record_generates_id(self):
        """create_failure_record should generate unique failure_id."""
        classifier = FailureClassifier()
        error = ValueError("test error")

        record1 = classifier.create_failure_record(
            document_id="doc-001",
            archetype_name="maintenance_procedure",
            error=error,
            repair_step="validation",
        )
        record2 = classifier.create_failure_record(
            document_id="doc-001",
            archetype_name="maintenance_procedure",
            error=error,
            repair_step="validation",
        )

        assert record1.failure_id != record2.failure_id

    def test_create_failure_record_classifies_error(self):
        """create_failure_record should classify error correctly."""
        classifier = FailureClassifier()
        error = TimeoutError("timeout")

        record = classifier.create_failure_record(
            document_id="doc-001",
            archetype_name="test",
            error=error,
            repair_step="extraction",
        )

        assert record.failure_class == FailureClass.TIMEOUT

    def test_create_failure_record_truncates_context(self):
        """create_failure_record should truncate context_excerpt to 500 chars."""
        classifier = FailureClassifier()
        long_context = "x" * 1000
        error = Exception("test")

        record = classifier.create_failure_record(
            document_id="doc-001",
            archetype_name="test",
            error=error,
            repair_step="validation",
            context_excerpt=long_context,
        )

        assert len(record.context_excerpt) == 500
        assert record.context_excerpt == "x" * 500


class TestFailureEventCollectorInit:
    """Test FailureEventCollector initialization."""

    def test_collector_initializes_empty(self):
        """FailureEventCollector should initialize with empty event store."""
        collector = FailureEventCollector()
        events = collector.collect_events()
        assert len(events) == 0

    def test_collector_initializes_methods(self):
        """FailureEventCollector should have all required methods."""
        collector = FailureEventCollector()
        assert hasattr(collector, "emit_failure_event")
        assert hasattr(collector, "collect_events")
        assert hasattr(collector, "get_event_count_by_class")
        assert callable(collector.emit_failure_event)
        assert callable(collector.collect_events)
        assert callable(collector.get_event_count_by_class)


class TestFailureEventEmission:
    """Test FailureEvent creation and emission."""

    def test_emit_failure_event_returns_event(self):
        """emit_failure_event should return FailureEvent."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="TypeError",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="TypeError occurred",
        )

        event = collector.emit_failure_event(failure)
        assert isinstance(event, FailureEvent)

    def test_emit_creates_unique_event_id(self):
        """emit_failure_event should create unique event IDs."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="TypeError",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="error",
        )

        event1 = collector.emit_failure_event(failure)
        event2 = collector.emit_failure_event(failure)
        assert event1.event_id != event2.event_id

    def test_emit_copies_failure_fields(self):
        """emit_failure_event should copy relevant failure fields."""
        collector = FailureEventCollector()
        now = datetime.utcnow()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="maintenance_procedure",
            failure_class=FailureClass.TIMEOUT,
            severity="CRITICAL",
            root_cause="timeout",
            timestamp=now,
            repair_step="extraction",
            error_message="timeout error",
        )

        event = collector.emit_failure_event(failure)
        assert event.failure_id == "fail-001"
        assert event.document_id == "doc-001"
        assert event.failure_class == FailureClass.TIMEOUT
        assert event.repair_step == "extraction"
        assert event.timestamp == now

    def test_action_required_for_timeout(self):
        """action_required should be True for TIMEOUT failures."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.TIMEOUT,
            severity="HIGH",
            root_cause="timeout",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="timeout",
        )

        event = collector.emit_failure_event(failure)
        assert event.action_required is True

    def test_action_required_for_resource_exhaustion(self):
        """action_required should be True for RESOURCE_EXHAUSTION failures."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.RESOURCE_EXHAUSTION,
            severity="CRITICAL",
            root_cause="out of memory",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="MemoryError",
        )

        event = collector.emit_failure_event(failure)
        assert event.action_required is True

    def test_action_required_for_bug(self):
        """action_required should be True for BUG failures."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="CRITICAL",
            root_cause="TypeError",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="TypeError",
        )

        event = collector.emit_failure_event(failure)
        assert event.action_required is True

    def test_action_not_required_for_network_error(self):
        """action_required should be False for NETWORK_ERROR failures."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.NETWORK_ERROR,
            severity="HIGH",
            root_cause="connection refused",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="ConnectionError",
        )

        event = collector.emit_failure_event(failure)
        assert event.action_required is False

    def test_action_not_required_for_policy_violation(self):
        """action_required should be False for POLICY_VIOLATION failures."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.POLICY_VIOLATION,
            severity="HIGH",
            root_cause="policy violation",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="ValueError",
        )

        event = collector.emit_failure_event(failure)
        assert event.action_required is False

    def test_suggested_action_for_timeout(self):
        """Suggested action for TIMEOUT should be retry_with_timeout_increase."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.TIMEOUT,
            severity="HIGH",
            root_cause="timeout",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="timeout",
        )

        event = collector.emit_failure_event(failure)
        assert event.suggested_action == "retry_with_timeout_increase"

    def test_suggested_action_for_resource_exhaustion(self):
        """Suggested action for RESOURCE_EXHAUSTION should be escalate_to_resource_handler."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.RESOURCE_EXHAUSTION,
            severity="CRITICAL",
            root_cause="out of memory",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="MemoryError",
        )

        event = collector.emit_failure_event(failure)
        assert event.suggested_action == "escalate_to_resource_handler"

    def test_suggested_action_for_bug(self):
        """Suggested action for BUG should be escalate_to_skill_handler."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="CRITICAL",
            root_cause="TypeError",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="TypeError",
        )

        event = collector.emit_failure_event(failure)
        assert event.suggested_action == "escalate_to_skill_handler"


class TestFailureEventCollection:
    """Test collecting and filtering failure events."""

    def test_collect_events_returns_all(self):
        """collect_events should return all recent events."""
        collector = FailureEventCollector()
        failure1 = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="error1",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="error1",
        )
        failure2 = DocumentFailure(
            failure_id="fail-002",
            document_id="doc-002",
            archetype_name="test",
            failure_class=FailureClass.TIMEOUT,
            severity="HIGH",
            root_cause="error2",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="error2",
        )

        collector.emit_failure_event(failure1)
        collector.emit_failure_event(failure2)

        events = collector.collect_events()
        assert len(events) == 2

    def test_collect_events_filters_by_document(self):
        """collect_events should filter by document_id if provided."""
        collector = FailureEventCollector()
        failure1 = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="error1",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="error1",
        )
        failure2 = DocumentFailure(
            failure_id="fail-002",
            document_id="doc-002",
            archetype_name="test",
            failure_class=FailureClass.TIMEOUT,
            severity="HIGH",
            root_cause="error2",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="error2",
        )

        collector.emit_failure_event(failure1)
        collector.emit_failure_event(failure2)

        events = collector.collect_events(document_id="doc-001")
        assert len(events) == 1
        assert events[0].document_id == "doc-001"

    def test_collect_events_filters_by_time_window(self):
        """collect_events should filter by time window."""
        collector = FailureEventCollector()

        # Create old failure (70 minutes ago)
        old_time = datetime.utcnow() - timedelta(minutes=70)
        old_failure = DocumentFailure(
            failure_id="fail-old",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="old error",
            timestamp=old_time,
            repair_step="validation",
            error_message="old error",
        )

        # Create recent failure
        recent_failure = DocumentFailure(
            failure_id="fail-recent",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.TIMEOUT,
            severity="HIGH",
            root_cause="recent error",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="recent error",
        )

        collector.emit_failure_event(old_failure)
        collector.emit_failure_event(recent_failure)

        # 60-minute window should only include recent
        events = collector.collect_events(minutes=60)
        assert len(events) == 1
        assert events[0].failure_id == "fail-recent"

    def test_collect_events_with_document_and_time_filter(self):
        """collect_events should apply both document and time filters."""
        collector = FailureEventCollector()

        old_time = datetime.utcnow() - timedelta(minutes=70)
        old_failure = DocumentFailure(
            failure_id="fail-old",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="old error",
            timestamp=old_time,
            repair_step="validation",
            error_message="old error",
        )

        recent_failure = DocumentFailure(
            failure_id="fail-recent",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.TIMEOUT,
            severity="HIGH",
            root_cause="recent error",
            timestamp=datetime.utcnow(),
            repair_step="extraction",
            error_message="recent error",
        )

        other_recent = DocumentFailure(
            failure_id="fail-other",
            document_id="doc-002",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="other error",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="other error",
        )

        collector.emit_failure_event(old_failure)
        collector.emit_failure_event(recent_failure)
        collector.emit_failure_event(other_recent)

        events = collector.collect_events(document_id="doc-001", minutes=60)
        assert len(events) == 1
        assert events[0].failure_id == "fail-recent"


class TestFailureEventClassAggregation:
    """Test aggregating events by failure class."""

    def test_get_event_count_by_class_empty(self):
        """get_event_count_by_class should return empty dict for no events."""
        collector = FailureEventCollector()
        counts = collector.get_event_count_by_class()
        assert len(counts) == 0

    def test_get_event_count_by_class_single(self):
        """get_event_count_by_class should count single event."""
        collector = FailureEventCollector()
        failure = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="error",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="error",
        )

        collector.emit_failure_event(failure)

        counts = collector.get_event_count_by_class()
        assert counts["BUG"] == 1

    def test_get_event_count_by_class_multiple(self):
        """get_event_count_by_class should aggregate multiple events."""
        collector = FailureEventCollector()

        for i in range(3):
            failure = DocumentFailure(
                failure_id=f"fail-{i}",
                document_id="doc-001",
                archetype_name="test",
                failure_class=FailureClass.BUG,
                severity="HIGH",
                root_cause="error",
                timestamp=datetime.utcnow(),
                repair_step="validation",
                error_message="error",
            )
            collector.emit_failure_event(failure)

        counts = collector.get_event_count_by_class()
        assert counts["BUG"] == 3

    def test_get_event_count_by_class_mixed(self):
        """get_event_count_by_class should handle multiple failure classes."""
        collector = FailureEventCollector()

        classes = [
            FailureClass.BUG,
            FailureClass.BUG,
            FailureClass.TIMEOUT,
            FailureClass.RESOURCE_EXHAUSTION,
        ]

        for i, cls in enumerate(classes):
            failure = DocumentFailure(
                failure_id=f"fail-{i}",
                document_id="doc-001",
                archetype_name="test",
                failure_class=cls,
                severity="HIGH",
                root_cause="error",
                timestamp=datetime.utcnow(),
                repair_step="validation",
                error_message="error",
            )
            collector.emit_failure_event(failure)

        counts = collector.get_event_count_by_class()
        assert counts["BUG"] == 2
        assert counts["TIMEOUT"] == 1
        assert counts["RESOURCE_EXHAUSTION"] == 1

    def test_get_event_count_respects_time_window(self):
        """get_event_count_by_class should respect time window filter."""
        collector = FailureEventCollector()

        old_time = datetime.utcnow() - timedelta(minutes=70)
        old_failure = DocumentFailure(
            failure_id="fail-old",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="old error",
            timestamp=old_time,
            repair_step="validation",
            error_message="old error",
        )

        recent_failure = DocumentFailure(
            failure_id="fail-recent",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="recent error",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="recent error",
        )

        collector.emit_failure_event(old_failure)
        collector.emit_failure_event(recent_failure)

        counts = collector.get_event_count_by_class(minutes=60)
        assert counts["BUG"] == 1

    def test_get_event_count_respects_document_filter(self):
        """get_event_count_by_class should respect document filter."""
        collector = FailureEventCollector()

        failure1 = DocumentFailure(
            failure_id="fail-001",
            document_id="doc-001",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="error",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="error",
        )

        failure2 = DocumentFailure(
            failure_id="fail-002",
            document_id="doc-002",
            archetype_name="test",
            failure_class=FailureClass.BUG,
            severity="HIGH",
            root_cause="error",
            timestamp=datetime.utcnow(),
            repair_step="validation",
            error_message="error",
        )

        collector.emit_failure_event(failure1)
        collector.emit_failure_event(failure2)

        counts = collector.get_event_count_by_class(document_id="doc-001")
        assert counts["BUG"] == 1
