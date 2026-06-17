"""Test suite for PHASE 5 Meta-Improvement Controller."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from ops.docsreg.archetype_policy_adapter.failure_classifier import FailureClass
from ops.docsreg.archetype_policy_adapter.failure_events import FailureEvent
from ops.docsreg.archetype_policy_adapter.meta_improvement_controller import (
    RepairDecision,
    RepairPriority,
    RepairAction,
    RepairOutcome,
    MetaImprovementController,
)


class TestRepairDecisionEnum:
    """Test RepairDecision enum values."""

    def test_repair_decision_values(self):
        """RepairDecision should have four defined values."""
        assert RepairDecision.ACCEPT_REPAIR.value == "ACCEPT_REPAIR"
        assert RepairDecision.DEFER_REPAIR.value == "DEFER_REPAIR"
        assert RepairDecision.ESCALATE_TO_HUMAN.value == "ESCALATE_TO_HUMAN"
        assert RepairDecision.SKIP_REPAIR.value == "SKIP_REPAIR"

    def test_repair_decision_comparison(self):
        """RepairDecision values should be comparable."""
        assert RepairDecision.ACCEPT_REPAIR != RepairDecision.DEFER_REPAIR
        assert RepairDecision.ACCEPT_REPAIR == RepairDecision.ACCEPT_REPAIR


class TestRepairPriorityEnum:
    """Test RepairPriority enum values."""

    def test_repair_priority_values(self):
        """RepairPriority should have four defined priority levels."""
        assert RepairPriority.CRITICAL.value == "CRITICAL"
        assert RepairPriority.HIGH.value == "HIGH"
        assert RepairPriority.MEDIUM.value == "MEDIUM"
        assert RepairPriority.LOW.value == "LOW"

    def test_repair_priority_comparison(self):
        """RepairPriority values should be comparable."""
        assert RepairPriority.CRITICAL != RepairPriority.HIGH
        assert RepairPriority.CRITICAL == RepairPriority.CRITICAL


class TestRepairActionImmutability:
    """Test that RepairAction is immutable (frozen)."""

    def test_repair_action_is_frozen(self):
        """RepairAction should be immutable."""
        action = RepairAction(
            action_id=str(uuid4()),
            event_id=str(uuid4()),
            failure_class=FailureClass.TIMEOUT,
            decision=RepairDecision.ACCEPT_REPAIR,
            priority=RepairPriority.HIGH,
            target_handler="timeout_recovery_handler",
            reasoning="Timeout failure detected",
            timestamp=datetime.utcnow(),
        )

        # Should not be able to modify action
        with pytest.raises(AttributeError):
            action.action_id = "new_id"

    def test_repair_action_fields(self):
        """RepairAction should have all required fields."""
        now = datetime.utcnow()
        action = RepairAction(
            action_id="test_action_1",
            event_id="test_event_1",
            failure_class=FailureClass.BUG,
            decision=RepairDecision.ESCALATE_TO_HUMAN,
            priority=RepairPriority.CRITICAL,
            target_handler="skill_handler",
            reasoning="Bug detected in code logic",
            timestamp=now,
            max_retries=3,
        )

        assert action.action_id == "test_action_1"
        assert action.event_id == "test_event_1"
        assert action.failure_class == FailureClass.BUG
        assert action.decision == RepairDecision.ESCALATE_TO_HUMAN
        assert action.priority == RepairPriority.CRITICAL
        assert action.target_handler == "skill_handler"
        assert action.reasoning == "Bug detected in code logic"
        assert action.timestamp == now
        assert action.max_retries == 3


class TestRepairOutcomeImmutability:
    """Test that RepairOutcome is immutable (frozen)."""

    def test_repair_outcome_is_frozen(self):
        """RepairOutcome should be immutable."""
        outcome = RepairOutcome(
            outcome_id=str(uuid4()),
            action_id=str(uuid4()),
            event_id=str(uuid4()),
            success=True,
            attempt_count=1,
            error_message=None,
            repair_time_ms=150,
            timestamp=datetime.utcnow(),
        )

        # Should not be able to modify outcome
        with pytest.raises(AttributeError):
            outcome.success = False

    def test_repair_outcome_fields(self):
        """RepairOutcome should have all required fields."""
        now = datetime.utcnow()
        outcome = RepairOutcome(
            outcome_id="outcome_1",
            action_id="action_1",
            event_id="event_1",
            success=False,
            attempt_count=2,
            error_message="Timeout during repair execution",
            repair_time_ms=500,
            timestamp=now,
        )

        assert outcome.outcome_id == "outcome_1"
        assert outcome.action_id == "action_1"
        assert outcome.event_id == "event_1"
        assert outcome.success is False
        assert outcome.attempt_count == 2
        assert outcome.error_message == "Timeout during repair execution"
        assert outcome.repair_time_ms == 500
        assert outcome.timestamp == now


class TestMetaImprovementControllerInit:
    """Test MetaImprovementController initialization."""

    def test_controller_initializes(self):
        """Controller should initialize with empty tracking lists."""
        controller = MetaImprovementController()
        assert controller._actions == []
        assert controller._outcomes == []
        assert controller._decision_policy is not None

    def test_controller_decision_policy_built(self):
        """Controller should build decision policy on init."""
        controller = MetaImprovementController()
        policy = controller._decision_policy

        # Verify policy has entries for all failure classes
        assert FailureClass.TIMEOUT in policy
        assert FailureClass.RESOURCE_EXHAUSTION in policy
        assert FailureClass.BUG in policy
        assert FailureClass.NETWORK_ERROR in policy
        assert FailureClass.POLICY_VIOLATION in policy
        assert FailureClass.OTHER in policy


class TestDecisionPolicyMapping:
    """Test decision policy mapping for each failure class."""

    def test_timeout_policy(self):
        """TIMEOUT should map to ACCEPT_REPAIR, HIGH, timeout_recovery_handler."""
        controller = MetaImprovementController()
        decision, priority, handler = controller._decision_policy[FailureClass.TIMEOUT]
        assert decision == RepairDecision.ACCEPT_REPAIR
        assert priority == RepairPriority.HIGH
        assert handler == "timeout_recovery_handler"

    def test_resource_exhaustion_policy(self):
        """RESOURCE_EXHAUSTION should map to DEFER_REPAIR, CRITICAL, resource_recovery_handler."""
        controller = MetaImprovementController()
        decision, priority, handler = controller._decision_policy[
            FailureClass.RESOURCE_EXHAUSTION
        ]
        assert decision == RepairDecision.DEFER_REPAIR
        assert priority == RepairPriority.CRITICAL
        assert handler == "resource_recovery_handler"

    def test_bug_policy(self):
        """BUG should map to ESCALATE_TO_HUMAN, CRITICAL, skill_handler."""
        controller = MetaImprovementController()
        decision, priority, handler = controller._decision_policy[FailureClass.BUG]
        assert decision == RepairDecision.ESCALATE_TO_HUMAN
        assert priority == RepairPriority.CRITICAL
        assert handler == "skill_handler"

    def test_network_error_policy(self):
        """NETWORK_ERROR should map to ACCEPT_REPAIR, MEDIUM, network_recovery_handler."""
        controller = MetaImprovementController()
        decision, priority, handler = controller._decision_policy[
            FailureClass.NETWORK_ERROR
        ]
        assert decision == RepairDecision.ACCEPT_REPAIR
        assert priority == RepairPriority.MEDIUM
        assert handler == "network_recovery_handler"

    def test_policy_violation_policy(self):
        """POLICY_VIOLATION should map to ACCEPT_REPAIR, HIGH, validation_repair_handler."""
        controller = MetaImprovementController()
        decision, priority, handler = controller._decision_policy[
            FailureClass.POLICY_VIOLATION
        ]
        assert decision == RepairDecision.ACCEPT_REPAIR
        assert priority == RepairPriority.HIGH
        assert handler == "validation_repair_handler"

    def test_other_policy(self):
        """OTHER should map to SKIP_REPAIR, LOW, unclassified_handler."""
        controller = MetaImprovementController()
        decision, priority, handler = controller._decision_policy[FailureClass.OTHER]
        assert decision == RepairDecision.SKIP_REPAIR
        assert priority == RepairPriority.LOW
        assert handler == "unclassified_handler"


class TestMakeRepairDecision:
    """Test repair decision making from failure events."""

    def test_make_decision_from_timeout_event(self):
        """Should create ACCEPT_REPAIR action for TIMEOUT failure."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft_generation",
            timestamp=datetime.utcnow(),
            action_required=True,
            suggested_action="retry_with_timeout_increase",
        )

        action = controller.make_repair_decision(event)

        assert action.event_id == "event_1"
        assert action.failure_class == FailureClass.TIMEOUT
        assert action.decision == RepairDecision.ACCEPT_REPAIR
        assert action.priority == RepairPriority.HIGH
        assert action.target_handler == "timeout_recovery_handler"

    def test_make_decision_from_bug_event(self):
        """Should create ESCALATE_TO_HUMAN action for BUG failure."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_2",
            failure_id="failure_2",
            document_id="doc_1",
            failure_class=FailureClass.BUG,
            repair_step="rewrite",
            timestamp=datetime.utcnow(),
            action_required=True,
            suggested_action="escalate_to_skill_handler",
        )

        action = controller.make_repair_decision(event)

        assert action.failure_class == FailureClass.BUG
        assert action.decision == RepairDecision.ESCALATE_TO_HUMAN
        assert action.priority == RepairPriority.CRITICAL

    def test_decision_stored_in_actions_list(self):
        """Created action should be stored in controller._actions."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_3",
            failure_id="failure_3",
            document_id="doc_1",
            failure_class=FailureClass.NETWORK_ERROR,
            repair_step="scoring",
            timestamp=datetime.utcnow(),
            action_required=False,
            suggested_action="retry_with_backoff",
        )

        action = controller.make_repair_decision(event)

        assert len(controller._actions) == 1
        assert controller._actions[0] == action

    def test_max_retries_set_based_on_decision(self):
        """ACCEPT_REPAIR should have max_retries=3, others max_retries=1."""
        controller = MetaImprovementController()

        # ACCEPT_REPAIR → 3 retries
        event_accept = FailureEvent(
            event_id="event_a",
            failure_id="failure_a",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action_accept = controller.make_repair_decision(event_accept)
        assert action_accept.max_retries == 3

        # ESCALATE_TO_HUMAN → 1 retry
        event_escalate = FailureEvent(
            event_id="event_b",
            failure_id="failure_b",
            document_id="doc_1",
            failure_class=FailureClass.BUG,
            repair_step="rewrite",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action_escalate = controller.make_repair_decision(event_escalate)
        assert action_escalate.max_retries == 1


class TestReasoningGeneration:
    """Test reasoning string generation."""

    def test_reasoning_includes_failure_class(self):
        """Reasoning should include failure class value."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft_generation",
            timestamp=datetime.utcnow(),
            action_required=True,
            suggested_action="retry_with_timeout_increase",
        )

        action = controller.make_repair_decision(event)

        assert "TIMEOUT" in action.reasoning
        assert "draft_generation" in action.reasoning
        assert action.reasoning is not None

    def test_reasoning_includes_decision_and_priority(self):
        """Reasoning should include decision and priority values."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_2",
            failure_id="failure_2",
            document_id="doc_1",
            failure_class=FailureClass.BUG,
            repair_step="rewrite",
            timestamp=datetime.utcnow(),
            action_required=True,
            suggested_action="escalate_to_skill_handler",
        )

        action = controller.make_repair_decision(event)

        assert "ESCALATE_TO_HUMAN" in action.reasoning
        assert "CRITICAL" in action.reasoning


class TestRecordRepairOutcome:
    """Test recording repair execution outcomes."""

    def test_record_successful_outcome(self):
        """Should record successful repair outcome."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action = controller.make_repair_decision(event)

        outcome = controller.record_repair_outcome(
            action=action,
            success=True,
            attempt_count=1,
            repair_time_ms=250,
        )

        assert outcome.success is True
        assert outcome.attempt_count == 1
        assert outcome.repair_time_ms == 250
        assert outcome.error_message is None
        assert outcome.action_id == action.action_id

    def test_record_failed_outcome(self):
        """Should record failed repair outcome with error message."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_2",
            failure_id="failure_2",
            document_id="doc_1",
            failure_class=FailureClass.NETWORK_ERROR,
            repair_step="scoring",
            timestamp=datetime.utcnow(),
            action_required=False,
        )
        action = controller.make_repair_decision(event)

        outcome = controller.record_repair_outcome(
            action=action,
            success=False,
            attempt_count=3,
            repair_time_ms=1500,
            error_message="Network timeout after 3 retries",
        )

        assert outcome.success is False
        assert outcome.attempt_count == 3
        assert outcome.error_message == "Network timeout after 3 retries"

    def test_outcome_stored_in_outcomes_list(self):
        """Recorded outcome should be stored in controller._outcomes."""
        controller = MetaImprovementController()
        event = FailureEvent(
            event_id="event_3",
            failure_id="failure_3",
            document_id="doc_1",
            failure_class=FailureClass.POLICY_VIOLATION,
            repair_step="validation",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action = controller.make_repair_decision(event)

        outcome = controller.record_repair_outcome(
            action=action,
            success=True,
            attempt_count=1,
            repair_time_ms=100,
        )

        assert len(controller._outcomes) == 1
        assert controller._outcomes[0] == outcome


class TestGetActionsByDecision:
    """Test filtering actions by decision type."""

    def test_get_accept_repair_actions(self):
        """Should retrieve only ACCEPT_REPAIR actions."""
        controller = MetaImprovementController()

        # Create ACCEPT_REPAIR action (TIMEOUT)
        event1 = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action1 = controller.make_repair_decision(event1)

        # Create ESCALATE_TO_HUMAN action (BUG)
        event2 = FailureEvent(
            event_id="event_2",
            failure_id="failure_2",
            document_id="doc_1",
            failure_class=FailureClass.BUG,
            repair_step="rewrite",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action2 = controller.make_repair_decision(event2)

        # Get ACCEPT_REPAIR actions
        accept_actions = controller.get_actions_by_decision(RepairDecision.ACCEPT_REPAIR)

        assert len(accept_actions) == 1
        assert accept_actions[0].action_id == action1.action_id

    def test_get_escalate_actions(self):
        """Should retrieve only ESCALATE_TO_HUMAN actions."""
        controller = MetaImprovementController()

        # Create multiple actions
        for failure_class in [FailureClass.BUG, FailureClass.BUG, FailureClass.TIMEOUT]:
            event = FailureEvent(
                event_id=str(uuid4()),
                failure_id=str(uuid4()),
                document_id="doc_1",
                failure_class=failure_class,
                repair_step="test",
                timestamp=datetime.utcnow(),
                action_required=True,
            )
            controller.make_repair_decision(event)

        # Get ESCALATE actions (should be 2 BUG actions)
        escalate_actions = controller.get_actions_by_decision(
            RepairDecision.ESCALATE_TO_HUMAN
        )

        assert len(escalate_actions) == 2
        for action in escalate_actions:
            assert action.decision == RepairDecision.ESCALATE_TO_HUMAN

    def test_get_actions_respects_max_age(self):
        """Should filter actions by max_age_minutes."""
        controller = MetaImprovementController()

        # Create old action (61 minutes ago)
        old_time = datetime.utcnow() - timedelta(minutes=61)
        old_event = FailureEvent(
            event_id="old_event",
            failure_id="old_failure",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=old_time,
            action_required=True,
        )
        old_action = RepairAction(
            action_id=str(uuid4()),
            event_id="old_event",
            failure_class=FailureClass.TIMEOUT,
            decision=RepairDecision.ACCEPT_REPAIR,
            priority=RepairPriority.HIGH,
            target_handler="timeout_recovery_handler",
            reasoning="Old action",
            timestamp=old_time,
        )
        controller._actions.append(old_action)

        # Create recent action
        recent_event = FailureEvent(
            event_id="recent_event",
            failure_id="recent_failure",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        recent_action = controller.make_repair_decision(recent_event)

        # Get actions within 60 minutes
        recent_actions = controller.get_actions_by_decision(
            RepairDecision.ACCEPT_REPAIR, max_age_minutes=60
        )

        assert len(recent_actions) == 1
        assert recent_actions[0].action_id == recent_action.action_id


class TestGetActionsByPriority:
    """Test filtering actions by priority level."""

    def test_get_critical_priority_actions(self):
        """Should retrieve only CRITICAL priority actions."""
        controller = MetaImprovementController()

        # Create CRITICAL priority actions (BUG, RESOURCE_EXHAUSTION)
        for failure_class in [FailureClass.BUG, FailureClass.RESOURCE_EXHAUSTION]:
            event = FailureEvent(
                event_id=str(uuid4()),
                failure_id=str(uuid4()),
                document_id="doc_1",
                failure_class=failure_class,
                repair_step="test",
                timestamp=datetime.utcnow(),
                action_required=True,
            )
            controller.make_repair_decision(event)

        # Create HIGH priority action (TIMEOUT)
        event_high = FailureEvent(
            event_id=str(uuid4()),
            failure_id=str(uuid4()),
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        controller.make_repair_decision(event_high)

        # Get CRITICAL actions
        critical_actions = controller.get_actions_by_priority(RepairPriority.CRITICAL)

        assert len(critical_actions) == 2
        for action in critical_actions:
            assert action.priority == RepairPriority.CRITICAL

    def test_get_actions_by_priority_respects_max_age(self):
        """Should filter by priority and max_age_minutes."""
        controller = MetaImprovementController()

        # Create old CRITICAL action
        old_time = datetime.utcnow() - timedelta(minutes=90)
        old_action = RepairAction(
            action_id=str(uuid4()),
            event_id="old",
            failure_class=FailureClass.BUG,
            decision=RepairDecision.ESCALATE_TO_HUMAN,
            priority=RepairPriority.CRITICAL,
            target_handler="skill_handler",
            reasoning="Old critical",
            timestamp=old_time,
        )
        controller._actions.append(old_action)

        # Create recent CRITICAL action
        recent_event = FailureEvent(
            event_id="recent",
            failure_id="recent_failure",
            document_id="doc_1",
            failure_class=FailureClass.BUG,
            repair_step="rewrite",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        recent_action = controller.make_repair_decision(recent_event)

        # Get CRITICAL actions within 60 minutes
        actions = controller.get_actions_by_priority(
            RepairPriority.CRITICAL, max_age_minutes=60
        )

        assert len(actions) == 1
        assert actions[0].action_id == recent_action.action_id


class TestGetOutcomesForAction:
    """Test retrieving outcomes for specific action."""

    def test_get_outcomes_for_action_id(self):
        """Should retrieve all outcomes associated with action."""
        controller = MetaImprovementController()

        # Create action
        event = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action = controller.make_repair_decision(event)

        # Record multiple outcomes for same action
        outcome1 = controller.record_repair_outcome(
            action=action, success=False, attempt_count=1, repair_time_ms=100,
            error_message="First attempt timeout"
        )
        outcome2 = controller.record_repair_outcome(
            action=action, success=True, attempt_count=2, repair_time_ms=150
        )

        # Get outcomes
        outcomes = controller.get_outcomes_for_action(action.action_id)

        assert len(outcomes) == 2
        assert outcome1 in outcomes
        assert outcome2 in outcomes

    def test_get_outcomes_for_nonexistent_action(self):
        """Should return empty list for nonexistent action."""
        controller = MetaImprovementController()

        outcomes = controller.get_outcomes_for_action("nonexistent_action_id")

        assert outcomes == []

    def test_outcomes_isolated_by_action(self):
        """Outcomes should be isolated to their action."""
        controller = MetaImprovementController()

        # Create two actions
        event1 = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action1 = controller.make_repair_decision(event1)

        event2 = FailureEvent(
            event_id="event_2",
            failure_id="failure_2",
            document_id="doc_1",
            failure_class=FailureClass.NETWORK_ERROR,
            repair_step="scoring",
            timestamp=datetime.utcnow(),
            action_required=False,
        )
        action2 = controller.make_repair_decision(event2)

        # Record outcomes for each action
        controller.record_repair_outcome(
            action=action1, success=True, attempt_count=1, repair_time_ms=100
        )
        controller.record_repair_outcome(
            action=action2, success=False, attempt_count=2, repair_time_ms=200,
            error_message="Network error"
        )

        # Verify isolation
        outcomes1 = controller.get_outcomes_for_action(action1.action_id)
        outcomes2 = controller.get_outcomes_for_action(action2.action_id)

        assert len(outcomes1) == 1
        assert len(outcomes2) == 1
        assert outcomes1[0].action_id == action1.action_id
        assert outcomes2[0].action_id == action2.action_id


class TestGetSuccessRate:
    """Test repair success rate calculation."""

    def test_success_rate_all_successful(self):
        """Success rate should be 1.0 if all outcomes successful."""
        controller = MetaImprovementController()

        # Create action and record 3 successful outcomes
        event = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action = controller.make_repair_decision(event)

        for i in range(3):
            controller.record_repair_outcome(
                action=action,
                success=True,
                attempt_count=1,
                repair_time_ms=100 + i * 50,
            )

        rate = controller.get_success_rate()

        assert rate == 1.0

    def test_success_rate_all_failed(self):
        """Success rate should be 0.0 if all outcomes failed."""
        controller = MetaImprovementController()

        # Create action and record 3 failed outcomes
        event = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.NETWORK_ERROR,
            repair_step="scoring",
            timestamp=datetime.utcnow(),
            action_required=False,
        )
        action = controller.make_repair_decision(event)

        for i in range(3):
            controller.record_repair_outcome(
                action=action,
                success=False,
                attempt_count=i + 1,
                repair_time_ms=200,
                error_message="Network timeout",
            )

        rate = controller.get_success_rate()

        assert rate == 0.0

    def test_success_rate_mixed(self):
        """Success rate should be 0.5 for 2 successes and 2 failures."""
        controller = MetaImprovementController()

        # Create action
        event = FailureEvent(
            event_id="event_1",
            failure_id="failure_1",
            document_id="doc_1",
            failure_class=FailureClass.POLICY_VIOLATION,
            repair_step="validation",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action = controller.make_repair_decision(event)

        # Record 2 successes and 2 failures
        controller.record_repair_outcome(action=action, success=True, attempt_count=1, repair_time_ms=100)
        controller.record_repair_outcome(action=action, success=False, attempt_count=1, repair_time_ms=100)
        controller.record_repair_outcome(action=action, success=True, attempt_count=1, repair_time_ms=100)
        controller.record_repair_outcome(action=action, success=False, attempt_count=1, repair_time_ms=100)

        rate = controller.get_success_rate()

        assert rate == 0.5

    def test_success_rate_no_outcomes(self):
        """Success rate should be 0.0 with no outcomes."""
        controller = MetaImprovementController()

        rate = controller.get_success_rate()

        assert rate == 0.0

    def test_success_rate_respects_max_age(self):
        """Success rate should only consider recent outcomes."""
        controller = MetaImprovementController()

        # Create old outcome (90 minutes ago)
        old_time = datetime.utcnow() - timedelta(minutes=90)
        old_outcome = RepairOutcome(
            outcome_id=str(uuid4()),
            action_id="action_1",
            event_id="event_1",
            success=False,
            attempt_count=1,
            error_message="Test error",
            repair_time_ms=100,
            timestamp=old_time,
        )
        controller._outcomes.append(old_outcome)

        # Create recent successful outcome
        event = FailureEvent(
            event_id="event_2",
            failure_id="failure_2",
            document_id="doc_1",
            failure_class=FailureClass.TIMEOUT,
            repair_step="draft",
            timestamp=datetime.utcnow(),
            action_required=True,
        )
        action = controller.make_repair_decision(event)
        controller.record_repair_outcome(
            action=action, success=True, attempt_count=1, repair_time_ms=100
        )

        # Get success rate for last 60 minutes (should only count recent success)
        rate = controller.get_success_rate(max_age_minutes=60)

        assert rate == 1.0
