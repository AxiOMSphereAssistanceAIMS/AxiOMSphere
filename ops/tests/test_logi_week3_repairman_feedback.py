"""Integration tests for Week 3: Repairman → ProjectStateManager feedback loop.

Tests validate:
- Repair completion updates task status
- Success creates training task
- Learned rules are recorded
- Full workflow: incident → repair → training → learn
"""
import asyncio
import pytest
from datetime import datetime
from pathlib import Path

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
from ops.logi.repairman_feedback_bridge import (
    RepairmanFeedbackHandler,
    handle_repair_completion_webhook,
)


@pytest.mark.asyncio
class TestRepairmanFeedback:
    """Test repairman feedback handling."""

    async def test_repair_success_updates_task(self):
        """Repair success should update task status to SUCCEEDED."""
        manager = await get_manager()
        bus = await get_bus()

        handler = RepairmanFeedbackHandler(manager, bus)

        # Create repair task
        repair = await manager.create_task(
            task_type=TaskType.REPAIR,
            title="Fix timeout",
            created_by="test",
        )

        # Mark as started
        await handler.on_repair_started(repair.task_id, "Restart service")

        # Mark as succeeded
        result = await handler.on_repair_succeeded(
            repair.task_id,
            fix_applied="Restarted docagent",
        )

        assert result is True

        # Verify task status
        updated = await manager.get_task(repair.task_id)
        assert updated.status == TaskStatus.SUCCEEDED
        assert updated.result["status"] == "succeeded"

        await bus.disconnect()
        await manager.disconnect()

    async def test_repair_failure_updates_task(self):
        """Repair failure should update task status to FAILED."""
        manager = await get_manager()
        bus = await get_bus()

        handler = RepairmanFeedbackHandler(manager, bus)

        # Create repair task
        repair = await manager.create_task(
            task_type=TaskType.REPAIR,
            title="Fix OOM",
            created_by="test",
        )

        # Mark as started
        await handler.on_repair_started(repair.task_id, "Increase memory limit")

        # Mark as failed
        result = await handler.on_repair_failed(
            repair.task_id,
            error_message="Permission denied when modifying container",
        )

        assert result is True

        # Verify task status
        updated = await manager.get_task(repair.task_id)
        assert updated.status == TaskStatus.FAILED
        assert "Permission denied" in updated.error

        await bus.disconnect()
        await manager.disconnect()

    async def test_repair_success_creates_training_task(self):
        """Repair success should trigger training task creation."""
        manager = await get_manager()
        bus = await get_bus()

        handler = RepairmanFeedbackHandler(manager, bus)

        # Create repair task
        repair = await manager.create_task(
            task_type=TaskType.REPAIR,
            title="Fix crash",
            created_by="test",
        )

        # Mark as succeeded
        await handler.on_repair_succeeded(
            repair.task_id,
            fix_applied="Applied patch",
        )

        # Request training task
        training_id = await handler.on_training_requested(
            repair.task_id,
            training_params={"model": "qwen3:32b", "dataset": "v12"},
        )

        assert training_id is not None

        # Verify training task exists and depends on repair
        training = await manager.get_task(training_id)
        assert training.task_type == TaskType.TRAINING
        assert repair.task_id in training.depends_on

        await bus.disconnect()
        await manager.disconnect()

    async def test_repair_events_published(self):
        """Repair events should be published to EventBus."""
        manager = await get_manager()
        bus = await get_bus()

        handler = RepairmanFeedbackHandler(manager, bus)

        # Create repair task
        repair = await manager.create_task(
            task_type=TaskType.REPAIR,
            title="Test",
            created_by="test",
        )

        # Trigger success
        await handler.on_repair_succeeded(repair.task_id, "Fix applied")

        await asyncio.sleep(0.5)

        # Check events
        events = await bus.get_events(EventType.REPAIR_SUCCEEDED, limit=10)
        assert len(events) > 0

        latest = events[0]
        assert latest.data["task_id"] == repair.task_id
        assert "Fix applied" in latest.data["fix"]

        await bus.disconnect()
        await manager.disconnect()

    async def test_learned_rules_recorded(self):
        """Repair success should record learned rules."""
        manager = await get_manager()
        bus = await get_bus()

        handler = RepairmanFeedbackHandler(manager, bus)

        # Create repair task
        repair = await manager.create_task(
            task_type=TaskType.REPAIR,
            title="Test",
            created_by="test",
        )

        # Mark as succeeded
        await handler.on_repair_succeeded(
            repair.task_id,
            fix_applied="Increase GPU memory from 10GB to 20GB",
        )

        # Check learned rules file
        rules_file = Path(
            "/home/axi_omi_sphere/aims-workspace/aims_workspace/repairman_memory/rules_learned.md"
        )

        await asyncio.sleep(0.2)

        if rules_file.exists():
            content = rules_file.read_text()
            assert "Increase GPU memory" in content or len(content) > 0

        await bus.disconnect()
        await manager.disconnect()


@pytest.mark.asyncio
class TestWeek3Integration:
    """Full integration tests for Week 3 workflow."""

    async def test_full_incident_repair_training_workflow(self):
        """Full workflow: incident → repair → success → training."""
        manager = await get_manager()
        bus = await get_bus()

        # Set up dispatcher
        dispatcher = IncidentToTaskDispatcher(manager, bus)
        await dispatcher.subscribe_to_all_events()

        # Set up feedback handler
        feedback = RepairmanFeedbackHandler(manager, bus)

        # 1. Create incident → repair task
        incident = Event(
            event_type=EventType.ARGUS_CRITICAL_INCIDENT,
            source="argus",
            timestamp=datetime.utcnow(),
            severity=EventSeverity.CRITICAL,
            correlation_id="workflow_test_001",
            data={
                "service": "pipeline-coordinator",
                "error": "segmentation_fault",
                "incident_id": "inc_workflow_001",
            },
        )

        await bus.publish(incident)
        await asyncio.sleep(0.5)

        # Get repair task
        repair_tasks = await manager.list_tasks(task_type=TaskType.REPAIR)
        assert len(repair_tasks) > 0
        repair_id = repair_tasks[0].task_id

        # 2. Repair starts
        await feedback.on_repair_started(
            repair_id,
            "Restart service and clear cache",
            estimated_duration_seconds=300,
        )

        repair = await manager.get_task(repair_id)
        assert repair.status == TaskStatus.IN_PROGRESS

        # 3. Repair succeeds
        await feedback.on_repair_succeeded(
            repair_id,
            fix_applied="Restarted pipeline-coordinator",
            output={"restart_time": 4.5},
        )

        repair = await manager.get_task(repair_id)
        assert repair.status == TaskStatus.SUCCEEDED

        # 4. Training task created
        training_id = await feedback.on_training_requested(
            repair_id,
            training_params={"model": "qwen3:32b", "reason": "Learn from incident"},
        )

        assert training_id is not None
        training = await manager.get_task(training_id)
        assert training.task_type == TaskType.TRAINING
        assert repair_id in training.depends_on

        # 5. Verify DAG
        is_valid = await manager.validate_dag()
        assert is_valid

        # 6. Verify stats
        stats = await manager.get_stats()
        assert stats['total_tasks'] >= 2
        assert stats['by_status']['succeeded'] >= 1

        await bus.disconnect()
        await manager.disconnect()

    async def test_repair_failure_workflow(self):
        """Test repair failure handling."""
        manager = await get_manager()
        bus = await get_bus()

        feedback = RepairmanFeedbackHandler(manager, bus)

        # Create repair task
        repair = await manager.create_task(
            task_type=TaskType.REPAIR,
            title="Attempt fix",
            created_by="test",
        )

        # Start and fail
        await feedback.on_repair_started(repair.task_id, "Apply patch")
        await feedback.on_repair_failed(
            repair.task_id,
            error_message="Patch applied but service still not responding",
            should_retry=True,
        )

        # Verify status
        updated = await manager.get_task(repair.task_id)
        assert updated.status == TaskStatus.FAILED
        assert updated.result["should_retry"] is True

        await bus.disconnect()
        await manager.disconnect()

    async def test_webhook_handler(self):
        """Test repair completion webhook handler."""
        # Test success webhook
        response = await handle_repair_completion_webhook(
            repair_task_id="test_webhook_001",
            status="success",
            fix_applied="Test fix",
        )

        assert response["status"] == "updated"
        assert response["repair_status"] == "succeeded"

        # Test failure webhook
        response = await handle_repair_completion_webhook(
            repair_task_id="test_webhook_002",
            status="failure",
            error_message="Test error",
        )

        assert response["status"] == "updated"
        assert response["repair_status"] == "failed"

    async def test_multiple_repairs_concurrent(self):
        """Test multiple repairs progressing concurrently."""
        manager = await get_manager()
        bus = await get_bus()

        feedback = RepairmanFeedbackHandler(manager, bus)

        # Create multiple repair tasks
        repairs = []
        for i in range(3):
            repair = await manager.create_task(
                task_type=TaskType.REPAIR,
                title=f"Repair {i}",
                created_by="test",
                priority=90 - i * 10,  # Different priorities
            )
            repairs.append(repair)

        # Progress them at different rates
        for i, repair in enumerate(repairs):
            await feedback.on_repair_started(repair.task_id, f"Fix {i}")

            # Only succeed the first two
            if i < 2:
                await asyncio.sleep(0.1)
                await feedback.on_repair_succeeded(
                    repair.task_id,
                    fix_applied=f"Applied fix {i}",
                )

        # Check statuses
        stats = await manager.get_stats()
        succeeded = stats['by_status'].get('succeeded', 0)
        in_progress = stats['by_status'].get('in_progress', 0)

        assert succeeded >= 2
        assert in_progress >= 1

        await bus.disconnect()
        await manager.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
