"""PHASE 6 orchestration layer integration tests.

Tests exception classification → failure routing → repair decision → hard gate validation pipeline.
Verifies bridging of PHASE 2-5 components into unified repair workflow.
"""
import pytest
import dataclasses
from datetime import datetime
from ops.docsreg.integration.phase6_orchestration import (
    Phase6OrchestrationLayer,
    RepairRoutingContext,
)
from ops.docsreg.archetype_policy_adapter.failure_classifier import (
    FailureClass,
    FailureClassifier,
)
from ops.docsreg.archetype_policy_adapter.meta_improvement_controller import (
    RepairDecision,
    RepairPriority,
)
from ops.docsreg.archetype_policy_adapter.base import ViolationSeverity
from ops.docsreg.universal_loop.data_retention_validator import RetentionVerdict


class TestExceptionClassification:
    """Test exception → FailureClass classification pipeline."""

    def test_timeout_exception_classification(self):
        """Verify TimeoutError maps to TIMEOUT class."""
        layer = Phase6OrchestrationLayer()
        error = TimeoutError("operation timed out")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft_generation",
        )

        assert failure.failure_class == FailureClass.TIMEOUT
        assert failure.document_id == "doc_123"
        assert failure.archetype_name == "maintenance_procedure"
        assert failure.repair_step == "draft_generation"

    def test_memory_error_classification(self):
        """Verify MemoryError maps to RESOURCE_EXHAUSTION."""
        layer = Phase6OrchestrationLayer()
        error = MemoryError("out of memory")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_456",
            archetype_name="policy_framework",
            repair_step="rewrite_phase",
        )

        assert failure.failure_class == FailureClass.RESOURCE_EXHAUSTION

    def test_connection_error_classification(self):
        """Verify ConnectionError maps to NETWORK_ERROR."""
        layer = Phase6OrchestrationLayer()
        error = ConnectionError("failed to connect")

        failure = layer.classify_failure(
            error=error,
            document_id=None,
            archetype_name="maintenance_procedure",
            repair_step="api_call",
        )

        assert failure.failure_class == FailureClass.NETWORK_ERROR

    def test_assertion_error_classification(self):
        """Verify AssertionError maps to BUG."""
        layer = Phase6OrchestrationLayer()
        error = AssertionError("assertion failed in repair logic")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_789",
            archetype_name="technical_report",
            repair_step="validation",
        )

        assert failure.failure_class == FailureClass.BUG

    def test_policy_violation_classification(self):
        """Verify ValueError with 'archetype' maps to POLICY_VIOLATION."""
        layer = Phase6OrchestrationLayer()
        error = ValueError("archetype constraint violated")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_100",
            archetype_name="unknown_type",
            repair_step="validation",
        )

        assert failure.failure_class == FailureClass.POLICY_VIOLATION

    def test_unknown_error_classification(self):
        """Verify unrecognized errors map to OTHER."""
        layer = Phase6OrchestrationLayer()
        error = RuntimeError("unknown runtime error")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_200",
            archetype_name="maintenance_procedure",
            repair_step="generation",
        )

        assert failure.failure_class == FailureClass.OTHER

    def test_context_excerpt_truncation(self):
        """Verify context_excerpt limited to 500 characters."""
        layer = Phase6OrchestrationLayer()
        error = TimeoutError("test")
        long_context = "x" * 1000

        failure = layer.classify_failure(
            error=error,
            document_id="doc_300",
            archetype_name="maintenance_procedure",
            repair_step="draft",
            context_excerpt=long_context,
        )

        assert len(failure.context_excerpt) == 500


class TestFailureRouting:
    """Test failure → routing decision pipeline."""

    def test_timeout_routes_to_accept_repair_high_priority(self):
        """Verify TIMEOUT routes to ACCEPT_REPAIR with HIGH priority."""
        layer = Phase6OrchestrationLayer()
        error = TimeoutError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)

        assert routing.failure_class == FailureClass.TIMEOUT
        assert routing.repair_action.decision == RepairDecision.ACCEPT_REPAIR
        assert routing.repair_action.priority == RepairPriority.HIGH
        assert routing.target_handler == "timeout_recovery_handler"
        assert routing.max_retries == 3

    def test_resource_exhaustion_routes_to_defer_critical_priority(self):
        """Verify RESOURCE_EXHAUSTION routes to DEFER with CRITICAL priority."""
        layer = Phase6OrchestrationLayer()
        error = MemoryError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.decision == RepairDecision.DEFER_REPAIR
        assert routing.repair_action.priority == RepairPriority.CRITICAL
        assert routing.target_handler == "resource_recovery_handler"
        assert routing.max_retries == 1

    def test_bug_routes_to_escalate_critical_priority(self):
        """Verify BUG routes to ESCALATE_TO_HUMAN with CRITICAL priority."""
        layer = Phase6OrchestrationLayer()
        error = AssertionError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.decision == RepairDecision.ESCALATE_TO_HUMAN
        assert routing.repair_action.priority == RepairPriority.CRITICAL
        assert routing.target_handler == "skill_handler"
        assert routing.max_retries == 1

    def test_network_error_routes_to_accept_medium_priority(self):
        """Verify NETWORK_ERROR routes to ACCEPT with MEDIUM priority."""
        layer = Phase6OrchestrationLayer()
        error = ConnectionError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="api_call",
        )

        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.decision == RepairDecision.ACCEPT_REPAIR
        assert routing.repair_action.priority == RepairPriority.MEDIUM
        assert routing.target_handler == "network_recovery_handler"

    def test_policy_violation_routes_to_accept_high_priority(self):
        """Verify POLICY_VIOLATION routes to ACCEPT with HIGH priority."""
        layer = Phase6OrchestrationLayer()
        error = ValueError("archetype constraint violated")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="validation",
        )

        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.decision == RepairDecision.ACCEPT_REPAIR
        assert routing.repair_action.priority == RepairPriority.HIGH
        assert routing.target_handler == "validation_repair_handler"

    def test_other_routes_to_skip_low_priority(self):
        """Verify OTHER routes to SKIP with LOW priority."""
        layer = Phase6OrchestrationLayer()
        error = RuntimeError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="generation",
        )

        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.decision == RepairDecision.SKIP_REPAIR
        assert routing.repair_action.priority == RepairPriority.LOW
        assert routing.target_handler == "unclassified_handler"

    def test_routing_context_immutability(self):
        """Verify RepairRoutingContext is frozen (immutable)."""
        layer = Phase6OrchestrationLayer()
        error = TimeoutError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            routing.target_handler = "different_handler"


class TestHardGateEnforcement:
    """Test data retention hard gate enforcement."""

    def test_pass_verdict_accepts_repair(self):
        """Verify PASS verdict allows repair acceptance."""
        layer = Phase6OrchestrationLayer()
        before = "Original content with many sections and references"
        after = "Repaired content with sections and references intact"

        passed_gate, report = layer.validate_repair_retention(
            before_content=before,
            after_content=after,
            archetype_type="maintenance_procedure",
        )

        # PASS verdict should return True
        assert passed_gate is True
        assert report["verdict"] in ("pass", "advisory")  # Actual enum values are lowercase

    def test_advisory_verdict_accepts_repair(self):
        """Verify ADVISORY verdict allows repair acceptance."""
        layer = Phase6OrchestrationLayer()
        # Simulate content with minimal loss (only minor word changes)
        before = "Section A with content\nSection B with content\nSection C with content"
        after = "Section A with updated content\nSection B with updated content\nSection C with updated content"

        passed_gate, report = layer.validate_repair_retention(
            before_content=before,
            after_content=after,
            archetype_type="maintenance_procedure",
        )

        # ADVISORY or PASS verdict should return True (no major loss)
        assert passed_gate is True
        assert report["verdict"] in ("advisory", "pass")

    def test_fail_verdict_rejects_repair(self):
        """Verify FAIL verdict blocks repair acceptance."""
        layer = Phase6OrchestrationLayer()
        before = "Long original content" * 100
        after = "Short"  # Massive data loss

        passed_gate, report = layer.validate_repair_retention(
            before_content=before,
            after_content=after,
            archetype_type="maintenance_procedure",
        )

        # FAIL verdict should return False, blocking repair
        assert passed_gate is False
        assert report["verdict"] == "fail"

    def test_retention_report_includes_all_metrics(self):
        """Verify retention report contains all tracking metrics."""
        layer = Phase6OrchestrationLayer()
        before = "Content with sections, required fields, tables, and links"
        after = "Minimal content"

        passed_gate, report = layer.validate_repair_retention(
            before_content=before,
            after_content=after,
            archetype_type="maintenance_procedure",
        )

        # Verify report has all required fields
        assert "verdict" in report
        assert "token_loss_percentage" in report
        assert "lost_required_fields" in report
        assert "lost_sections" in report
        assert "lost_references" in report
        assert "lost_tables" in report
        assert "lost_links" in report
        assert "lost_semantic_claims" in report


class TestOutcomeRecording:
    """Test repair outcome tracking."""

    def test_record_successful_outcome(self):
        """Verify successful repair outcome is recorded."""
        layer = Phase6OrchestrationLayer()
        error = TimeoutError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)

        outcome = layer.record_repair_outcome(
            action=routing.repair_action,
            success=True,
            attempt_count=1,
            repair_time_ms=1500,
        )

        assert outcome.success is True
        assert outcome.attempt_count == 1
        assert outcome.repair_time_ms == 1500
        assert outcome.error_message is None

    def test_record_failed_outcome(self):
        """Verify failed repair outcome is recorded with error message."""
        layer = Phase6OrchestrationLayer()
        error = TimeoutError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)

        outcome = layer.record_repair_outcome(
            action=routing.repair_action,
            success=False,
            attempt_count=3,
            repair_time_ms=45000,
            error_message="Repair exceeded max retries",
        )

        assert outcome.success is False
        assert outcome.attempt_count == 3
        assert outcome.error_message == "Repair exceeded max retries"

    def test_outcome_immutability(self):
        """Verify RepairOutcome is frozen."""
        layer = Phase6OrchestrationLayer()
        error = TimeoutError("test")

        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)
        outcome = layer.record_repair_outcome(
            action=routing.repair_action,
            success=True,
            attempt_count=1,
            repair_time_ms=1500,
        )

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            outcome.success = False


class TestMetricsCollection:
    """Test repair metrics and monitoring support."""

    def test_get_repair_metrics_returns_success_rate(self):
        """Verify get_repair_metrics returns success_rate and window."""
        layer = Phase6OrchestrationLayer()

        # Record some outcomes
        error = TimeoutError("test")
        failure = layer.classify_failure(
            error=error,
            document_id="doc_123",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )
        routing = layer.emit_and_route_failure(failure)

        # Success
        layer.record_repair_outcome(
            action=routing.repair_action,
            success=True,
            attempt_count=1,
            repair_time_ms=1000,
        )

        # Get metrics
        metrics = layer.get_repair_metrics(max_age_minutes=60)

        assert "success_rate" in metrics
        assert "metric_window_minutes" in metrics
        assert 0.0 <= metrics["success_rate"] <= 1.0
        assert metrics["metric_window_minutes"] == 60

    def test_metrics_default_window_60_minutes(self):
        """Verify default metrics window is 60 minutes."""
        layer = Phase6OrchestrationLayer()
        metrics = layer.get_repair_metrics()

        assert metrics["metric_window_minutes"] == 60

    def test_metrics_custom_window(self):
        """Verify custom metrics window is respected."""
        layer = Phase6OrchestrationLayer()
        metrics = layer.get_repair_metrics(max_age_minutes=120)

        assert metrics["metric_window_minutes"] == 120


class TestEndToEndPipeline:
    """Test complete exception → repair decision → outcome pipeline."""

    def test_timeout_pipeline_end_to_end(self):
        """Verify complete TIMEOUT exception handling pipeline."""
        layer = Phase6OrchestrationLayer()

        # 1. Classify exception
        error = TimeoutError("operation took too long")
        failure = layer.classify_failure(
            error=error,
            document_id="doc_001",
            archetype_name="maintenance_procedure",
            repair_step="draft_generation",
            severity=ViolationSeverity.HIGH,
            context_excerpt="Timeout during LLM call",
        )

        assert failure.failure_class == FailureClass.TIMEOUT
        assert failure.severity == ViolationSeverity.HIGH

        # 2. Emit and route failure
        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.decision == RepairDecision.ACCEPT_REPAIR
        assert routing.repair_action.priority == RepairPriority.HIGH
        assert routing.target_handler == "timeout_recovery_handler"

        # 3. Validate repair retention
        before_content = "Original draft content"
        after_content = "Repaired draft content with same sections"
        passed_gate, retention_report = layer.validate_repair_retention(
            before_content=before_content,
            after_content=after_content,
            archetype_type="maintenance_procedure",
        )

        assert passed_gate is True
        assert retention_report["verdict"] in ("pass", "advisory")

        # 4. Record outcome
        outcome = layer.record_repair_outcome(
            action=routing.repair_action,
            success=True,
            attempt_count=1,
            repair_time_ms=2000,
        )

        assert outcome.success is True
        assert outcome.action_id == routing.repair_action.action_id

    def test_resource_exhaustion_pipeline_escalates_critical(self):
        """Verify RESOURCE_EXHAUSTION escalates to critical priority."""
        layer = Phase6OrchestrationLayer()

        error = MemoryError("ran out of memory")
        failure = layer.classify_failure(
            error=error,
            document_id="doc_002",
            archetype_name="policy_framework",
            repair_step="rewrite_phase",
        )

        routing = layer.emit_and_route_failure(failure)

        # Should escalate to CRITICAL priority despite deferring repair
        assert routing.repair_action.priority == RepairPriority.CRITICAL
        assert routing.repair_action.decision == RepairDecision.DEFER_REPAIR

    def test_bug_pipeline_escalates_to_human(self):
        """Verify BUG exception escalates to human review."""
        layer = Phase6OrchestrationLayer()

        error = AssertionError("invariant violation in repair handler")
        failure = layer.classify_failure(
            error=error,
            document_id="doc_003",
            archetype_name="technical_report",
            repair_step="validation",
        )

        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.decision == RepairDecision.ESCALATE_TO_HUMAN
        assert routing.target_handler == "skill_handler"


class TestRegressionPreviousPhases:
    """Verify PHASE 3-5 components still work correctly via PHASE 6."""

    def test_phase3_failure_classifier_integration(self):
        """Verify PHASE 3 FailureClassifier works through PHASE 6."""
        layer = Phase6OrchestrationLayer()

        errors = [
            (TimeoutError("timeout"), FailureClass.TIMEOUT),
            (MemoryError("memory"), FailureClass.RESOURCE_EXHAUSTION),
            (ConnectionError("network"), FailureClass.NETWORK_ERROR),
            (AssertionError("bug"), FailureClass.BUG),
            (ValueError("archetype x"), FailureClass.POLICY_VIOLATION),
            (RuntimeError("other"), FailureClass.OTHER),
        ]

        for error, expected_class in errors:
            failure = layer.classify_failure(
                error=error,
                document_id="test",
                archetype_name="maintenance_procedure",
                repair_step="test",
            )
            assert failure.failure_class == expected_class

    def test_phase4_failure_events_integration(self):
        """Verify PHASE 4 FailureEventCollector works through PHASE 6."""
        layer = Phase6OrchestrationLayer()

        error = TimeoutError("test")
        failure = layer.classify_failure(
            error=error,
            document_id="doc_test",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        # Emit failure event
        routing = layer.emit_and_route_failure(failure)

        assert routing.repair_action.event_id is not None
        assert routing.repair_action.failure_class == failure.failure_class

    def test_phase5_meta_improvement_controller_integration(self):
        """Verify PHASE 5 MetaImprovementController works through PHASE 6."""
        layer = Phase6OrchestrationLayer()

        error = TimeoutError("test")
        failure = layer.classify_failure(
            error=error,
            document_id="doc_test",
            archetype_name="maintenance_procedure",
            repair_step="draft",
        )

        routing = layer.emit_and_route_failure(failure)

        # Verify decision policy applied correctly
        assert routing.repair_action.decision == RepairDecision.ACCEPT_REPAIR
        assert routing.repair_action.priority == RepairPriority.HIGH
        assert routing.repair_action.max_retries == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
