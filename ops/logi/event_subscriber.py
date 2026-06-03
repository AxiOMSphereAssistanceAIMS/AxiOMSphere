"""Event Subscriber — converts incidents and events into project tasks.

Bridges EventBus with ProjectStateManager:
- CRITICAL_INCIDENT → high-priority REPAIR task with 15min deadline
- WARNING_INCIDENT → medium-priority task with 1h deadline
- REPAIR_SUCCEEDED → trigger TRAINING task
- TRAINING_COMPLETED → analysis task
- etc.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from logi.event_bus import Event, EventType, EventBus, get_bus
from logi.project_state_manager import (
    ProjectStateManager,
    TaskType,
    get_manager,
)


class IncidentToTaskDispatcher:
    """Convert incidents to orchestration tasks."""

    def __init__(
        self,
        manager: ProjectStateManager,
        bus: EventBus,
    ):
        self.manager = manager
        self.bus = bus

    async def subscribe_to_all_events(self):
        """Register handlers for all relevant events."""
        # Incident → Repair
        await self.bus.subscribe(
            EventType.ARGUS_CRITICAL_INCIDENT,
            self._handle_critical_incident,
        )
        await self.bus.subscribe(
            EventType.ARGUS_WARNING_INCIDENT,
            self._handle_warning_incident,
        )

        # Repair → Training
        await self.bus.subscribe(
            EventType.REPAIR_SUCCEEDED,
            self._handle_repair_succeeded,
        )

        # Training → Analysis
        await self.bus.subscribe(
            EventType.TRAINING_COMPLETED,
            self._handle_training_completed,
        )

    async def _handle_critical_incident(self, event: Event):
        """Create high-priority repair task for CRITICAL incidents."""
        incident_data = event.data or {}

        # Extract incident details
        service = incident_data.get("service", "unknown_service")
        error = incident_data.get("error", "unknown_error")
        incident_id = incident_data.get("incident_id", event.correlation_id or "auto")

        # Create repair task
        repair_task = await self.manager.create_task(
            task_type=TaskType.REPAIR,
            title=f"🚨 CRITICAL: Fix {service} — {error}",
            created_by="dispatcher",
            deadline=datetime.utcnow() + timedelta(minutes=15),
            priority=95,  # Highest
            estimated_duration_seconds=600,  # 10 min estimate
        )

        # Update task data with incident reference
        repair_task.result = {
            "incident_id": incident_id,
            "service": service,
            "error": error,
            "severity": "CRITICAL",
        }
        await self.manager._store_task(repair_task)

        # Publish task creation event
        task_event = Event(
            event_type=EventType.TASK_CREATED,
            source="dispatcher",
            timestamp=datetime.utcnow(),
            correlation_id=event.correlation_id,
            parent_event_id=event.correlation_id,
            data={
                "task_id": repair_task.task_id,
                "task_type": "repair",
                "incident_id": incident_id,
                "title": repair_task.title,
            },
        )
        await self.bus.publish(task_event)

        print(f"✓ Created CRITICAL repair task {repair_task.task_id} for {service}")

    async def _handle_warning_incident(self, event: Event):
        """Create medium-priority task for WARNING incidents."""
        incident_data = event.data or {}

        service = incident_data.get("service", "unknown_service")
        error = incident_data.get("error", "unknown_error")
        incident_id = incident_data.get("incident_id", event.correlation_id or "auto")

        # Create analysis/mitigation task
        task = await self.manager.create_task(
            task_type=TaskType.ANALYSIS,
            title=f"⚠️  WARNING: Investigate {service} — {error}",
            created_by="dispatcher",
            deadline=datetime.utcnow() + timedelta(hours=1),
            priority=60,  # Medium
            estimated_duration_seconds=1800,  # 30 min estimate
        )

        task.result = {
            "incident_id": incident_id,
            "service": service,
            "error": error,
            "severity": "WARNING",
        }
        await self.manager._store_task(task)

        task_event = Event(
            event_type=EventType.TASK_CREATED,
            source="dispatcher",
            timestamp=datetime.utcnow(),
            correlation_id=event.correlation_id,
            parent_event_id=event.correlation_id,
            data={
                "task_id": task.task_id,
                "task_type": "analysis",
                "incident_id": incident_id,
                "title": task.title,
            },
        )
        await self.bus.publish(task_event)

        print(f"✓ Created WARNING analysis task {task.task_id} for {service}")

    async def _handle_repair_succeeded(self, event: Event):
        """On repair success, create training task to learn from it."""
        repair_data = event.data or {}
        task_id = repair_data.get("task_id")

        if not task_id:
            return

        # Get the repair task
        repair_task = await self.manager.get_task(task_id)
        if not repair_task:
            return

        # Create training task that depends on repair
        training_task = await self.manager.create_task(
            task_type=TaskType.TRAINING,
            title=f"Train on repair: {repair_task.title}",
            created_by="dispatcher",
            depends_on=[task_id],
            priority=70,
            estimated_duration_seconds=3600,  # 1 hour
        )

        training_task.result = {
            "incident_id": repair_task.result.get("incident_id") if repair_task.result else None,
            "repair_task_id": task_id,
            "repair_title": repair_task.title,
        }
        await self.manager._store_task(training_task)

        # Publish event
        task_event = Event(
            event_type=EventType.TASK_CREATED,
            source="dispatcher",
            timestamp=datetime.utcnow(),
            correlation_id=event.correlation_id,
            parent_event_id=event.correlation_id,
            data={
                "task_id": training_task.task_id,
                "task_type": "training",
                "repair_task_id": task_id,
                "title": training_task.title,
            },
        )
        await self.bus.publish(task_event)

        print(f"✓ Created TRAINING task {training_task.task_id} after repair success")

    async def _handle_training_completed(self, event: Event):
        """On training success, create analysis task for results."""
        training_data = event.data or {}
        task_id = training_data.get("task_id")
        eval_score = training_data.get("eval_score")

        if not task_id:
            return

        training_task = await self.manager.get_task(task_id)
        if not training_task:
            return

        # Create analysis task
        analysis_task = await self.manager.create_task(
            task_type=TaskType.ANALYSIS,
            title=f"Analyze training results (score={eval_score})",
            created_by="dispatcher",
            depends_on=[task_id],
            priority=50,
            estimated_duration_seconds=900,  # 15 min
        )

        analysis_task.result = {
            "training_task_id": task_id,
            "eval_score": eval_score,
        }
        await self.manager._store_task(analysis_task)

        # Publish event
        task_event = Event(
            event_type=EventType.TASK_CREATED,
            source="dispatcher",
            timestamp=datetime.utcnow(),
            correlation_id=event.correlation_id,
            parent_event_id=event.correlation_id,
            data={
                "task_id": analysis_task.task_id,
                "task_type": "analysis",
                "training_task_id": task_id,
                "eval_score": eval_score,
            },
        )
        await self.bus.publish(task_event)

        print(f"✓ Created ANALYSIS task {analysis_task.task_id} after training")


async def create_and_start_dispatcher(
    redis_url: str = "redis://localhost:6379",
) -> IncidentToTaskDispatcher:
    """Create and start the event dispatcher."""
    manager = await get_manager(redis_url)
    bus = await get_bus(redis_url)

    dispatcher = IncidentToTaskDispatcher(manager, bus)
    await dispatcher.subscribe_to_all_events()

    return dispatcher


if __name__ == "__main__":
    # Test dispatcher
    async def test():
        dispatcher = await create_and_start_dispatcher()

        # Simulate critical incident
        from logi.event_bus import EventSeverity

        incident_event = Event(
            event_type=EventType.ARGUS_CRITICAL_INCIDENT,
            source="argus",
            timestamp=datetime.utcnow(),
            severity=EventSeverity.CRITICAL,
            correlation_id="test_incident_001",
            data={
                "service": "docagent",
                "error": "timeout in inference",
                "incident_id": "inc_001",
            },
        )

        print("Publishing incident event...")
        await dispatcher.bus.publish(incident_event)

        # Give handlers time to process
        await asyncio.sleep(1)

        # Check tasks were created
        manager = dispatcher.manager
        stats = await manager.get_stats()
        print(f"Project stats: {stats}")

        runnable = await manager.get_runnable_tasks()
        print(f"Runnable tasks: {len(runnable)}")
        for task in runnable:
            print(f"  - {task.title} (priority {task.priority})")

    asyncio.run(test())
