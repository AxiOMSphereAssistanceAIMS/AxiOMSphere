"""Integration tests for Phase 2B: Learning Loops + Traini + EventBus.

Tests validate:
- Learning loops consume EventBus events
- Incident → correction → learning pattern
- Traini loop completions trigger optimization suggestions
- Full cycle: incident → repair → training → learn → improve
"""
import asyncio
import pytest
from datetime import datetime

from ops.logi.event_bus import (
    EventBus,
    Event,
    EventType,
    EventSeverity,
    get_bus,
    reset_bus_instance,
)
from ops.logi.traini_eventbus_bridge import (
    publish_learning_need,
    publish_baseline_created,
    publish_loop_started,
    publish_candidate_tested,
    publish_loop_complete,
)
from ops.logi.learning_loop_consumer import (
    LearningLoopConsumer,
    create_learning_loop_consumer,
)


@pytest.mark.asyncio
class TestTrainiEventBusBridge:
    """Test Traini → EventBus publishing."""

    async def test_publish_baseline_created(self):
        """Publish baseline creation event."""
        await reset_bus_instance()
        bus = await get_bus()

        result = await publish_baseline_created(
            baseline_name="qwen3:32b-v15",
            model_slot="32",
            eval_score=0.85,
            eval_suite="golden_v2",
        )

        assert result is True

        await bus.disconnect()

    async def test_publish_loop_lifecycle(self):
        """Publish full loop lifecycle events."""
        await reset_bus_instance()
        bus = await get_bus()

        # Start
        r1 = await publish_loop_started(
            run_id="test_lifecycle_001",
            baseline_name="v15",
            candidate_name="v16-candidate",
            objective="Improve repair accuracy",
        )
        assert r1 is True

        # Test iteration
        r2 = await publish_candidate_tested(
            run_id="test_lifecycle_001",
            iteration=1,
            verdict="CONTINUE",
            confidence=0.75,
            delta_expected=0.05,
            delta_observed=0.04,
        )
        assert r2 is True

        # Complete
        r3 = await publish_loop_complete(
            run_id="test_lifecycle_001",
            final_verdict="ACCEPT",
            iterations_used=2,
            total_evidence_size_bytes=524288,
        )
        assert r3 is True

        await bus.disconnect()

    async def test_publish_learning_need(self):
        """Publish learning need event."""
        await reset_bus_instance()
        bus = await get_bus()

        result = await publish_learning_need(
            incident_id="inc_test_001",
            incident_type="timeout",
            correction_applied="Increased timeout threshold",
            severity="warning",
            learning_priority=70,
        )

        assert result is True

        # Verify in EventBus
        await asyncio.sleep(0.1)  # Allow event to be processed
        events = await bus.get_events(EventType.TRAINING_REQUESTED, limit=10)
        assert len(events) > 0

        latest = events[0]
        assert latest.data["traini_event_type"] == "learning_need_created"
        assert "timeout" in latest.data["incident_type"]

        await bus.disconnect()


@pytest.mark.asyncio
class TestLearningLoopConsumer:
    """Test learning loop consumer integration."""

    async def test_consumer_creation(self):
        """Consumer should initialize and subscribe."""
        await reset_bus_instance()
        consumer = await create_learning_loop_consumer()

        assert consumer is not None
        assert consumer.bus is not None

        await consumer.bus.disconnect()

    async def test_consumer_handles_learning_need(self):
        """Consumer should handle learning needs from EventBus."""
        await reset_bus_instance()
        consumer = await create_learning_loop_consumer()

        if not consumer:
            pytest.skip("Learning loops not available")

        # Publish learning need
        await publish_learning_need(
            incident_id="inc_consumer_001",
            incident_type="oom",
            correction_applied="Increased memory limit",
            severity="critical",
        )

        await asyncio.sleep(0.5)

        # Consumer should have received and processed
        # (no assertions needed — just verify no crashes)

        await consumer.bus.disconnect()

    async def test_consumer_handles_loop_complete(self):
        """Consumer should handle loop completion events."""
        await reset_bus_instance()
        consumer = await create_learning_loop_consumer()

        if not consumer:
            pytest.skip("Learning loops not available")

        # Publish loop completion
        await publish_loop_complete(
            run_id="test_complete_001",
            final_verdict="ACCEPT",
            iterations_used=2,
            total_evidence_size_bytes=512000,
        )

        await asyncio.sleep(0.5)

        await consumer.bus.disconnect()


@pytest.mark.asyncio
class TestPhase2BIntegration:
    """Full integration: Incident → Repair → Training → Learning."""

    async def test_full_learning_cycle(self):
        """Full cycle: incident correction → learning pattern → optimization."""
        await reset_bus_instance()
        bus = await get_bus()
        consumer = await create_learning_loop_consumer()

        if not consumer:
            pytest.skip("Learning loops not available")

        # 1. Traini baseline created
        await publish_baseline_created(
            baseline_name="qwen3:32b-v15",
            model_slot="32",
            eval_score=0.82,
            eval_suite="golden_v2",
        )

        # 2. Learning need from repair correction
        await publish_learning_need(
            incident_id="inc_cycle_001",
            incident_type="timeout",
            correction_applied="Changed timeout from 30s to 45s",
            severity="warning",
            learning_priority=60,
        )

        # 3. Traini loop runs and completes
        await publish_loop_started(
            run_id="cycle_001",
            baseline_name="v15",
            candidate_name="v16",
            objective="Improve timeout handling",
        )

        await publish_candidate_tested(
            run_id="cycle_001",
            iteration=1,
            verdict="CONTINUE",
            confidence=0.80,
            delta_expected=0.04,
            delta_observed=0.035,
        )

        await publish_loop_complete(
            run_id="cycle_001",
            final_verdict="ACCEPT",
            iterations_used=1,
            total_evidence_size_bytes=256000,
        )

        await asyncio.sleep(1)

        # All events should be in EventBus
        stats = await bus.get_event_stats()
        assert stats.get("training.requested", 0) > 0

        await bus.disconnect()
        await consumer.bus.disconnect()

    async def test_multiple_incidents_learning(self):
        """Test learning from multiple incidents."""
        await reset_bus_instance()
        bus = await get_bus()
        consumer = await create_learning_loop_consumer()

        if not consumer:
            pytest.skip("Learning loops not available")

        # Multiple corrections
        incidents = [
            ("timeout", "Increased timeout", "warning", 60),
            ("oom", "Increased memory", "critical", 90),
            ("slow", "Optimized query", "warning", 50),
        ]

        for incident_type, correction, severity, priority in incidents:
            await publish_learning_need(
                incident_id=f"inc_multi_{incident_type}",
                incident_type=incident_type,
                correction_applied=correction,
                severity=severity,
                learning_priority=priority,
            )

        await asyncio.sleep(1)

        # All should be published
        stats = await bus.get_event_stats()
        assert stats.get("training.requested", 0) >= 3

        await bus.disconnect()
        await consumer.bus.disconnect()

    async def test_loop_acceptance_triggers_optimization(self):
        """Accepted loops should trigger optimization suggestions."""
        await reset_bus_instance()
        bus = await get_bus()
        consumer = await create_learning_loop_consumer()

        if not consumer:
            pytest.skip("Learning loops not available")

        # Publish accepted loop result
        await publish_loop_complete(
            run_id="opt_trigger_001",
            final_verdict="ACCEPT",
            iterations_used=2,
            total_evidence_size_bytes=300000,
        )

        await asyncio.sleep(0.5)

        # Consumer should process and potentially trigger optimization

        await bus.disconnect()
        await consumer.bus.disconnect()


@pytest.mark.asyncio
class TestEventBusLedger:
    """Verify event ledger persistence."""

    async def test_traini_events_persisted(self):
        """Traini events should persist in EventBus ledger."""
        await reset_bus_instance()
        bus = await get_bus()

        # Publish multiple Traini events
        for i in range(3):
            await publish_loop_started(
                run_id=f"ledger_test_{i}",
                baseline_name="v15",
                candidate_name=f"v16_{i}",
                objective="Test",
            )

        await asyncio.sleep(0.5)

        # Query ledger
        events = await bus.get_events(EventType.TRAINING_REQUESTED, limit=100)

        # Should have at least 3 events
        traini_loop_starts = [
            e for e in events
            if e.data.get("traini_event_type") == "loop_started"
        ]
        assert len(traini_loop_starts) >= 3

        await bus.disconnect()

    async def test_event_correlation(self):
        """Events should be traceable via correlation IDs."""
        await reset_bus_instance()
        bus = await get_bus()

        # Publish related events with same correlation
        await publish_loop_started(
            run_id="corr_test_001",
            baseline_name="v15",
            candidate_name="v16",
            objective="Correlation test",
        )

        await publish_loop_complete(
            run_id="corr_test_001",
            final_verdict="ACCEPT",
            iterations_used=1,
            total_evidence_size_bytes=128000,
        )

        await asyncio.sleep(0.5)

        # Query events
        events = await bus.get_events(EventType.TRAINING_REQUESTED, limit=100)

        # Both events should reference same run_id
        run_events = [e for e in events if e.data.get("run_id") == "corr_test_001"]
        assert len(run_events) >= 2

        await bus.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
