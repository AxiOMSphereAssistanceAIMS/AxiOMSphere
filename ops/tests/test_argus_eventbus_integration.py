"""Smoke tests for Argus → EventBus → ProjectStateManager integration.

Tests validate:
- Argus publishes MonitorEvents to EventBus
- Events create tasks in ProjectStateManager
- Tasks are scheduled with correct priority/deadline
- Full chain: monitor event → incident → repair task
"""
import asyncio
import pytest
from datetime import datetime

from ops.argus.argus_eventbus_bridge import (
    publish_monitor_event,
    publish_container_crash,
    publish_health_check_failure,
    publish_resource_exhaustion,
    create_argus_monitor_event_handler,
    get_event_bus,
)
from ops.logi.project_state_manager import (
    ProjectStateManager,
    TaskType,
    get_manager,
)
from ops.logi.event_bus import (
    EventBus,
    Event,
    EventType,
    EventSeverity,
    get_bus,
)
from ops.logi.event_subscriber import (
    IncidentToTaskDispatcher,
)


@pytest.mark.asyncio
class TestArgusEventBusBridge:
    """Test Argus → EventBus bridge."""

    async def test_publish_critical_incident(self):
        """Publish critical incident through bridge."""
        bus = await get_bus()

        result = await publish_monitor_event(
            event_type="critical",
            service="docagent",
            error="timeout in inference",
            incident_id="test_critical_001",
        )

        assert result is True

        # Verify event in ledger
        events = await bus.get_events(EventType.ARGUS_CRITICAL_INCIDENT, limit=10)
        assert len(events) > 0

        latest = events[0]
        assert latest.data["service"] == "docagent"
        assert latest.data["error"] == "timeout in inference"

        await bus.disconnect()

    async def test_publish_warning_incident(self):
        """Publish warning incident through bridge."""
        bus = await get_bus()

        result = await publish_monitor_event(
            event_type="warning",
            service="omi-bot",
            error="slow_response",
            incident_id="test_warning_001",
        )

        assert result is True

        # Verify event
        events = await bus.get_events(EventType.ARGUS_WARNING_INCIDENT, limit=10)
        assert len(events) > 0

        await bus.disconnect()

    async def test_publish_container_crash(self):
        """Publish container crash as critical incident."""
        bus = await get_bus()

        result = await publish_container_crash(
            container_name="pipeline-coordinator",
            error_message="OOM killer invoked",
            exit_code=137,
            log_tail="Last 10 lines...",
            incident_id="test_crash_001",
        )

        assert result is True

        # Verify event. The bus is shared with live production traffic during
        # concurrent runs, so find this test's own event by content rather
        # than assuming it is the most recent (events[0]).
        events = await bus.get_events(EventType.ARGUS_CRITICAL_INCIDENT, limit=20)
        matching = [
            e for e in events
            if e.data.get("service") == "pipeline-coordinator" and "137" in e.data.get("error", "")
        ]
        assert len(matching) > 0

        await bus.disconnect()

    async def test_publish_health_check_failure(self):
        """Publish health check failure."""
        bus = await get_bus()

        result = await publish_health_check_failure(
            service_name="knomi-agent",
            failure_reason="Connection timeout",
            is_critical=False,
            incident_id="test_health_001",
        )

        assert result is True

        await bus.disconnect()

    async def test_publish_resource_exhaustion(self):
        """Publish resource exhaustion event."""
        bus = await get_bus()

        result = await publish_resource_exhaustion(
            service_name="training-job",
            resource_type="memory",
            current_value=95.5,
            threshold=90.0,
            is_critical=True,
            incident_id="test_resource_001",
        )

        assert result is True

        await bus.disconnect()


@pytest.mark.asyncio
class TestArgusToTaskIntegration:
    """Test full chain: Argus → EventBus → Tasks."""

    async def test_critical_incident_creates_repair_task(self):
        """Critical incident from Argus should create repair task."""
        manager = await get_manager()
        bus = await get_bus()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Publish critical incident through bridge
        await publish_container_crash(
            container_name="docagent",
            error_message="Segmentation fault",
            exit_code=139,
            incident_id="test_argus_repair_001",
        )

        await asyncio.sleep(0.5)

        # Check repair task was created. The task list is shared with live
        # production traffic during concurrent runs, so find this test's own
        # task by content rather than assuming it is the first entry.
        repair_tasks = await manager.list_tasks(task_type=TaskType.REPAIR)
        matching = [t for t in repair_tasks if "docagent" in t.title.lower() and t.priority >= 90]
        assert len(matching) > 0

        await bus.disconnect()
        await manager.disconnect()

    async def test_warning_incident_creates_analysis_task(self):
        """Warning incident from Argus should create analysis task."""
        manager = await get_manager()
        bus = await get_bus()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Publish warning incident through bridge
        await publish_health_check_failure(
            service_name="omi-bot",
            failure_reason="High latency detected",
            is_critical=False,
            incident_id="test_argus_warning_001",
        )

        await asyncio.sleep(0.5)

        # Check analysis task was created
        analysis_tasks = await manager.list_tasks(task_type=TaskType.ANALYSIS)
        assert len(analysis_tasks) > 0

        task = analysis_tasks[0]
        assert "omi-bot" in task.title.lower()

        await bus.disconnect()
        await manager.disconnect()

    async def test_resource_exhaustion_creates_task(self):
        """Resource exhaustion should create appropriate task."""
        manager = await get_manager()
        bus = await get_bus()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Publish resource exhaustion
        await publish_resource_exhaustion(
            service_name="training-job",
            resource_type="memory",
            current_value=98.0,
            threshold=90.0,
            is_critical=True,
            incident_id="test_argus_resource_001",
        )

        await asyncio.sleep(0.5)

        # Check task was created (critical → repair)
        all_tasks = await manager.list_tasks()
        assert len(all_tasks) > 0

        await bus.disconnect()
        await manager.disconnect()

    async def test_multiple_argus_incidents_workflow(self):
        """Test multiple incidents from Argus create prioritized queue."""
        manager = await get_manager()
        bus = await get_bus()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Publish multiple incidents with different severities
        incidents = [
            ("critical", "service1", "crash"),
            ("warning", "service2", "slow"),
            ("critical", "service3", "oom"),
        ]

        for event_type, service, error in incidents:
            if event_type == "critical":
                await publish_container_crash(
                    container_name=service,
                    error_message=error,
                    exit_code=1,
                )
            else:
                await publish_health_check_failure(
                    service_name=service,
                    failure_reason=error,
                    is_critical=False,
                )

        await asyncio.sleep(1)

        # Check tasks were created
        runnable = await manager.get_runnable_tasks()
        assert len(runnable) >= 2

        # Critical incidents should have higher priority
        high_priority = [t for t in runnable if t.priority >= 90]
        assert len(high_priority) >= 2  # Two critical incidents

        await bus.disconnect()
        await manager.disconnect()


@pytest.mark.asyncio
class TestArgusMonitorEventHandler:
    """Test Argus MonitorEvent handler creation."""

    async def test_create_monitor_event_handler(self):
        """Create handler from Argus MonitorEvent."""
        manager = await get_manager()
        bus = await get_bus()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        handler = create_argus_monitor_event_handler()
        assert callable(handler)

        # Simulate MonitorEvent
        class MockMonitorEvent:
            service = "test-service"
            severity = "critical"
            message = "Test error"
            log_snippet = "Error details"
            incident_id = "mock_001"
            timestamp = datetime.utcnow()
            event_type = "health_check_failure"

        mock_event = MockMonitorEvent()
        await handler(mock_event)

        await asyncio.sleep(0.5)

        # Check task was created
        repair_tasks = await manager.list_tasks(task_type=TaskType.REPAIR)
        assert len(repair_tasks) > 0

        await bus.disconnect()
        await manager.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
