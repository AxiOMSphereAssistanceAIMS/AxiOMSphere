"""Integration tests for Week 2: Event → Task dispatch.

Tests validate:
- CRITICAL_INCIDENT → high-priority repair task
- WARNING_INCIDENT → medium-priority analysis task
- REPAIR_SUCCEEDED → training task (depends on repair)
- TRAINING_COMPLETED → analysis task
- Full workflow: incident → repair → training → analysis
"""
import json
import asyncio
import pytest
from datetime import datetime, timedelta

from ops.logi.project_state_manager import (
    ProjectStateManager,
    TaskStatus,
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
class TestEventSubscriber:
    """Test event-to-task dispatcher."""

    async def test_critical_incident_creates_repair_task(self):
        """CRITICAL incident should create high-priority repair task."""
        manager = ProjectStateManager()
        await manager.connect()

        bus = EventBus()
        await bus.connect()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Publish critical incident
        incident = Event(
            event_type=EventType.ARGUS_CRITICAL_INCIDENT,
            source="argus",
            timestamp=datetime.utcnow(),
            severity=EventSeverity.CRITICAL,
            correlation_id="test_crit_001",
            data={
                "service": "docagent",
                "error": "timeout",
                "incident_id": "inc_001",
            },
        )

        await bus.publish(incident)
        await asyncio.sleep(0.5)  # Let handler process

        # Check repair task was created
        repair_tasks = await manager.list_tasks(task_type=TaskType.REPAIR)
        assert len(repair_tasks) > 0

        repair = repair_tasks[0]
        assert repair.priority >= 90  # High priority
        assert repair.deadline is not None
        assert (repair.deadline - datetime.utcnow()).total_seconds() <= 900  # ~15min

        await bus.disconnect()
        await manager.disconnect()

    async def test_warning_incident_creates_analysis_task(self):
        """WARNING incident should create medium-priority analysis task."""
        manager = ProjectStateManager()
        await manager.connect()

        bus = EventBus()
        await bus.connect()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Publish warning incident
        incident = Event(
            event_type=EventType.ARGUS_WARNING_INCIDENT,
            source="argus",
            timestamp=datetime.utcnow(),
            severity=EventSeverity.WARNING,
            correlation_id="test_warn_001",
            data={
                "service": "omi-bot",
                "error": "slow_response",
                "incident_id": "inc_002",
            },
        )

        await bus.publish(incident)
        await asyncio.sleep(0.5)

        # Check analysis task was created
        analysis_tasks = await manager.list_tasks(task_type=TaskType.ANALYSIS)
        assert len(analysis_tasks) > 0

        analysis = analysis_tasks[0]
        assert 40 <= analysis.priority <= 80  # Medium priority
        assert analysis.deadline is not None

        await bus.disconnect()
        await manager.disconnect()

    async def test_repair_success_creates_training_task(self):
        """Repair success should trigger training task."""
        manager = ProjectStateManager()
        await manager.connect()

        bus = EventBus()
        await bus.connect()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Create initial repair task
        repair = await manager.create_task(
            task_type=TaskType.REPAIR,
            title="Fix timeout",
            created_by="test",
            priority=90,
        )

        # Publish repair success
        success_event = Event(
            event_type=EventType.REPAIR_SUCCEEDED,
            source="repairman",
            timestamp=datetime.utcnow(),
            correlation_id=f"repair_{repair.task_id}",
            data={
                "task_id": repair.task_id,
                "fix": "restart_service",
            },
        )

        await bus.publish(success_event)
        await asyncio.sleep(0.5)

        # Check training task was created
        training_tasks = await manager.list_tasks(task_type=TaskType.TRAINING)
        assert len(training_tasks) > 0

        training = training_tasks[0]
        assert repair.task_id in training.depends_on  # Should depend on repair
        assert training.priority >= 60  # Medium-high

        await bus.disconnect()
        await manager.disconnect()

    async def test_training_complete_creates_analysis_task(self):
        """Training completion should trigger analysis task."""
        manager = ProjectStateManager()
        await manager.connect()

        bus = EventBus()
        await bus.connect()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Create training task
        training = await manager.create_task(
            task_type=TaskType.TRAINING,
            title="Train model",
            created_by="test",
        )

        # Publish training complete
        complete_event = Event(
            event_type=EventType.TRAINING_COMPLETED,
            source="traini",
            timestamp=datetime.utcnow(),
            correlation_id=f"train_{training.task_id}",
            data={
                "task_id": training.task_id,
                "eval_score": 0.92,
                "model": "qwen3:32b-v17",
            },
        )

        await bus.publish(complete_event)
        await asyncio.sleep(0.5)

        # Check analysis task was created
        analysis_tasks = await manager.list_tasks(task_type=TaskType.ANALYSIS)
        assert len(analysis_tasks) > 0

        analysis = analysis_tasks[0]
        assert training.task_id in analysis.depends_on

        await bus.disconnect()
        await manager.disconnect()


@pytest.mark.asyncio
class TestWeek2Integration:
    """Integration tests for incident-to-task workflow."""

    async def test_full_incident_repair_training_workflow(self):
        """Full workflow: incident → repair → training → analysis."""
        manager = ProjectStateManager()
        await manager.connect()

        bus = EventBus()
        await bus.connect()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # 1. Argus publishes critical incident
        incident = Event(
            event_type=EventType.ARGUS_CRITICAL_INCIDENT,
            source="argus",
            timestamp=datetime.utcnow(),
            severity=EventSeverity.CRITICAL,
            correlation_id="workflow_test_001",
            data={
                "service": "pipeline-coordinator",
                "error": "oom_killer_invoked",
                "incident_id": "inc_workflow_001",
            },
        )

        await bus.publish(incident)
        await asyncio.sleep(0.5)

        # Get repair task
        repair_tasks = await manager.list_tasks(task_type=TaskType.REPAIR)
        assert len(repair_tasks) > 0
        repair_id = repair_tasks[0].task_id

        # 2. Repair completes
        await manager.update_task_status(repair_id, TaskStatus.SUCCEEDED)

        repair_event = Event(
            event_type=EventType.REPAIR_SUCCEEDED,
            source="repairman",
            timestamp=datetime.utcnow(),
            correlation_id="workflow_test_001",
            data={
                "task_id": repair_id,
                "fix": "increase_memory_limit",
            },
        )

        await bus.publish(repair_event)
        await asyncio.sleep(0.5)

        # Get training task
        training_tasks = await manager.list_tasks(task_type=TaskType.TRAINING)
        assert len(training_tasks) > 0
        training_id = training_tasks[0].task_id

        # Training should depend on repair
        training = await manager.get_task(training_id)
        assert repair_id in training.depends_on

        # 3. Training completes
        await manager.update_task_status(training_id, TaskStatus.SUCCEEDED)

        training_event = Event(
            event_type=EventType.TRAINING_COMPLETED,
            source="traini",
            timestamp=datetime.utcnow(),
            correlation_id="workflow_test_001",
            data={
                "task_id": training_id,
                "eval_score": 0.95,
            },
        )

        await bus.publish(training_event)
        await asyncio.sleep(0.5)

        # Get analysis task
        analysis_tasks = await manager.list_tasks(task_type=TaskType.ANALYSIS)
        assert len(analysis_tasks) > 0
        analysis_id = analysis_tasks[0].task_id

        # Analysis should depend on training
        analysis = await manager.get_task(analysis_id)
        assert training_id in analysis.depends_on

        # Verify DAG is valid
        is_valid = await manager.validate_dag()
        assert is_valid

        # Verify stats
        stats = await manager.get_stats()
        assert stats['total_tasks'] >= 3
        assert stats['by_type']['repair'] >= 1
        assert stats['by_type']['training'] >= 1
        assert stats['by_type']['analysis'] >= 1

        await bus.disconnect()
        await manager.disconnect()

    async def test_task_dependencies_prevent_execution(self):
        """Blocked tasks should not be runnable."""
        manager = ProjectStateManager()
        await manager.connect()

        bus = EventBus()
        await bus.connect()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Create incident → repair → training chain
        incident = Event(
            event_type=EventType.ARGUS_CRITICAL_INCIDENT,
            source="argus",
            timestamp=datetime.utcnow(),
            severity=EventSeverity.CRITICAL,
            correlation_id="deps_test_001",
            data={
                "service": "service_x",
                "error": "crash",
                "incident_id": "inc_deps_001",
            },
        )

        await bus.publish(incident)
        await asyncio.sleep(0.5)

        # Get repair task
        repair_tasks = await manager.list_tasks(task_type=TaskType.REPAIR)
        repair_id = repair_tasks[0].task_id

        # Simulate repair completion
        await manager.update_task_status(repair_id, TaskStatus.SUCCEEDED)

        repair_event = Event(
            event_type=EventType.REPAIR_SUCCEEDED,
            source="repairman",
            timestamp=datetime.utcnow(),
            data={"task_id": repair_id, "fix": "patch_applied"},
        )

        await bus.publish(repair_event)
        await asyncio.sleep(0.5)

        # Get training task
        training_tasks = await manager.list_tasks(task_type=TaskType.TRAINING)
        training_id = training_tasks[0].task_id

        # Training should only be runnable after repair is done
        training = await manager.get_task(training_id)

        # After repair completion, training should be runnable
        assert training.is_runnable()

        await bus.disconnect()
        await manager.disconnect()

    async def test_multiple_incidents_priority_scheduling(self):
        """Multiple incidents should be scheduled by priority."""
        manager = ProjectStateManager()
        await manager.connect()

        bus = EventBus()
        await bus.connect()

        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Publish multiple incidents
        for i in range(3):
            incident = Event(
                event_type=EventType.ARGUS_CRITICAL_INCIDENT,
                source="argus",
                timestamp=datetime.utcnow(),
                severity=EventSeverity.CRITICAL,
                correlation_id=f"multi_incident_{i}",
                data={
                    "service": f"service_{i}",
                    "error": f"error_{i}",
                    "incident_id": f"inc_multi_{i}",
                },
            )
            await bus.publish(incident)

        await asyncio.sleep(1)

        # Get runnable tasks
        runnable = await manager.get_runnable_tasks()

        # Should have multiple runnable tasks
        assert len(runnable) >= 3

        # Should be sorted by priority
        for i in range(len(runnable) - 1):
            assert runnable[i].priority >= runnable[i + 1].priority

        await bus.disconnect()
        await manager.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
