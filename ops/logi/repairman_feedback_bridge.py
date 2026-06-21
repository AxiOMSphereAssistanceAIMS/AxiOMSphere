"""Repairman → ProjectStateManager Feedback Loop.

Integrates repair completion with orchestration:
- Repair success/failure updates task status
- Creates training tasks on success
- Updates learned rules
- Publishes events for dashboard/alerts

This completes the self-healing cycle:
Incident → Repair → Learn → Train → Deploy
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional, Dict, Any

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


class RepairmanFeedbackHandler:
    """Handle repairman outputs and update orchestration."""

    def __init__(
        self,
        manager: ProjectStateManager,
        bus: EventBus,
    ):
        self.manager = manager
        self.bus = bus

    async def on_repair_started(
        self,
        repair_task_id: str,
        repair_plan: str,
        estimated_duration_seconds: int = 600,
    ) -> bool:
        """Mark repair as in_progress."""
        try:
            task = await self.manager.update_task_status(
                repair_task_id,
                TaskStatus.IN_PROGRESS,
                result={"status": "started", "plan": repair_plan},
            )

            # Publish event
            event = Event(
                event_type=EventType.REPAIR_STARTED,
                source="repairman",
                timestamp=datetime.utcnow(),
                severity=EventSeverity.INFO,
                data={
                    "task_id": repair_task_id,
                    "plan": repair_plan,
                    "estimated_duration": estimated_duration_seconds,
                },
            )
            await self.bus.publish(event)

            return True
        except Exception as e:
            print(f"⚠ Repair start update failed: {e}")
            return False

    async def on_repair_succeeded(
        self,
        repair_task_id: str,
        fix_applied: str,
        output: Optional[Dict[str, Any]] = None,
        should_trigger_training: bool = True,
    ) -> bool:
        """Repair succeeded: update task, create training task, publish event."""
        try:
            # Update repair task status
            result = {
                "status": "succeeded",
                "fix": fix_applied,
                "timestamp": datetime.utcnow().isoformat(),
                **(output or {}),
            }

            repair_task = await self.manager.update_task_status(
                repair_task_id,
                TaskStatus.SUCCEEDED,
                result=result,
            )

            # Publish repair succeeded event
            event = Event(
                event_type=EventType.REPAIR_SUCCEEDED,
                source="repairman",
                timestamp=datetime.utcnow(),
                severity=EventSeverity.INFO,
                data={
                    "task_id": repair_task_id,
                    "fix": fix_applied,
                },
            )
            await self.bus.publish(event)

            # Trigger training task creation (via EventBus dispatcher)
            # The IncidentToTaskDispatcher will create it automatically

            # Update learned rules file
            if should_trigger_training:
                await self._record_learned_rule(repair_task_id, fix_applied, True)

            return True
        except Exception as e:
            print(f"⚠ Repair success update failed: {e}")
            return False

    async def on_repair_failed(
        self,
        repair_task_id: str,
        error_message: str,
        should_retry: bool = False,
        output: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Repair failed: update task status, record failure."""
        try:
            result = {
                "status": "failed",
                "error": error_message,
                "should_retry": should_retry,
                "timestamp": datetime.utcnow().isoformat(),
                **(output or {}),
            }

            task = await self.manager.update_task_status(
                repair_task_id,
                TaskStatus.FAILED,
                error=error_message,
                result=result,
            )

            # Publish repair failed event
            event = Event(
                event_type=EventType.REPAIR_FAILED,
                source="repairman",
                timestamp=datetime.utcnow(),
                severity=EventSeverity.WARNING,
                data={
                    "task_id": repair_task_id,
                    "error": error_message,
                    "should_retry": should_retry,
                },
            )
            await self.bus.publish(event)

            # Record failure for learning
            await self._record_learned_rule(repair_task_id, error_message, False)

            return True
        except Exception as e:
            print(f"⚠ Repair failure update failed: {e}")
            return False

    async def on_training_requested(
        self,
        parent_repair_task_id: str,
        training_params: Dict[str, Any],
    ) -> Optional[str]:
        """Create training task dependent on repair."""
        try:
            training_task = await self.manager.create_task(
                task_type=TaskType.TRAINING,
                title=f"Train on repair outcome",
                created_by="repairman",
                depends_on=[parent_repair_task_id],
                priority=70,
                estimated_duration_seconds=3600,
            )

            # Update result with training task reference
            training_task.result = {
                "repair_task_id": parent_repair_task_id,
                "training_type": "dpo_from_repair",
                **training_params,
            }
            await self.manager._store_task(training_task)

            # Publish event
            event = Event(
                event_type=EventType.TRAINING_REQUESTED,
                source="repairman",
                timestamp=datetime.utcnow(),
                severity=EventSeverity.INFO,
                data={
                    "task_id": training_task.task_id,
                    "parent_repair_task_id": parent_repair_task_id,
                    "params": training_params,
                },
            )
            await self.bus.publish(event)

            return training_task.task_id
        except Exception as e:
            print(f"⚠ Training task creation failed: {e}")
            return None

    async def _record_learned_rule(
        self,
        repair_task_id: str,
        content: str,
        success: bool,
    ) -> bool:
        """Record learned rule for future incident prevention.

        Updates aims_workspace/repairman_memory/rules_learned.md
        """
        try:
            from pathlib import Path

            rules_file = Path("/home/axi_omi_sphere/aims-workspace/aims_workspace/repairman_memory/rules_learned.md")
            rules_file.parent.mkdir(parents=True, exist_ok=True)

            # Read existing content
            if rules_file.exists():
                existing = rules_file.read_text()
            else:
                existing = "# Learned Rules from Repairs\n\n"

            # Add new rule
            rule_entry = f"""
## Rule — {repair_task_id} ({datetime.utcnow().isoformat()})
**Status**: {"✅ Success" if success else "❌ Failed"}
**Content**: {content}

---
"""

            updated = existing + rule_entry

            # Write back
            rules_file.write_text(updated)
            return True
        except Exception as e:
            print(f"⚠ Failed to record learned rule: {e}")
            return False


async def create_repairman_feedback_handler() -> RepairmanFeedbackHandler:
    """Create and initialize repairman feedback handler."""
    manager = await get_manager()
    bus = await get_bus()

    handler = RepairmanFeedbackHandler(manager, bus)
    return handler


# REST API handlers for integration with RepairmanAPI

async def handle_repair_completion_webhook(
    repair_task_id: str,
    status: str,  # "success" or "failure"
    fix_applied: Optional[str] = None,
    error_message: Optional[str] = None,
    output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Handle repair completion webhook from RepairmanAPI.

    Called by: POST /api/logi/repairs/{repair_task_id}/complete

    Args:
        repair_task_id: ID of the repair task
        status: "success" or "failure"
        fix_applied: Description of fix (if success)
        error_message: Error details (if failure)
        output: Additional output dict

    Returns:
        Response dict with status
    """
    handler = await create_repairman_feedback_handler()

    if status == "success":
        result = await handler.on_repair_succeeded(
            repair_task_id,
            fix_applied or "Fix applied",
            output=output,
        )
        return {
            "status": "updated",
            "task_id": repair_task_id,
            "repair_status": "succeeded",
            "success": result,
        }
    elif status == "failure":
        result = await handler.on_repair_failed(
            repair_task_id,
            error_message or "Unknown error",
            output=output,
        )
        return {
            "status": "updated",
            "task_id": repair_task_id,
            "repair_status": "failed",
            "success": result,
        }
    else:
        return {"error": f"Unknown status: {status}"}


if __name__ == "__main__":
    # Test
    async def test():
        handler = await create_repairman_feedback_handler()

        # Simulate repair task
        repair = await handler.manager.create_task(
            task_type=TaskType.REPAIR,
            title="Test repair",
            created_by="test",
        )

        # Simulate repair success
        print(f"Starting repair {repair.task_id}...")
        await handler.on_repair_started(repair.task_id, "Restart service")
        await asyncio.sleep(0.1)

        print("Repair succeeded, creating training task...")
        result = await handler.on_repair_succeeded(
            repair.task_id,
            fix_applied="Restarted docagent container",
            output={"restart_time": 5.2},
        )
        print(f"Success: {result}")

        # Check training task was queued
        stats = await handler.manager.get_stats()
        print(f"Manager stats: {stats}")

        await handler.manager.disconnect()
        await handler.bus.disconnect()

    asyncio.run(test())
