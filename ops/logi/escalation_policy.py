"""Escalation Policy Engine — Auto-escalate tasks that exceed deadlines.

Rules:
- Task created with deadline
- If deadline exceeded → escalate priority
- After 1 hour overdue → send alert
- After 2 hours overdue → escalate to ops on-call
- After 4 hours overdue → exec escalation
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from logi.project_state_manager import (
    ProjectStateManager,
    TaskStatus,
    TaskType,
    get_manager,
)
from logi.telegram_alerts import get_alert_manager


class EscalationPolicy:
    """Manage task escalation based on deadline."""

    def __init__(self, manager: ProjectStateManager):
        self.manager = manager
        self.escalation_levels = {
            1 * 3600: {"name": "WARNING", "action": "send_alert"},
            2 * 3600: {"name": "ESCALATE", "action": "escalate_to_oncall"},
            4 * 3600: {"name": "EXEC", "action": "escalate_to_exec"},
        }

    async def check_overdue_tasks(self) -> Dict[str, List[str]]:
        """Check for overdue tasks and escalate.

        Returns:
            Dict with escalation level as key and task IDs as values
        """
        now = datetime.utcnow()
        escalations = {
            "warning": [],
            "oncall": [],
            "exec": [],
        }

        # Get all pending tasks
        tasks = await self.manager.list_tasks(status=TaskStatus.PENDING)

        for task in tasks:
            if not task.deadline:
                continue

            seconds_overdue = (now - task.deadline).total_seconds()
            if seconds_overdue <= 0:
                continue

            # Check escalation levels
            if seconds_overdue > 4 * 3600:
                escalations["exec"].append(task.task_id)
                await self._escalate_to_exec(task)
            elif seconds_overdue > 2 * 3600:
                escalations["oncall"].append(task.task_id)
                await self._escalate_to_oncall(task)
            elif seconds_overdue > 1 * 3600:
                escalations["warning"].append(task.task_id)
                await self._send_warning(task, int(seconds_overdue))

        return escalations

    async def _send_warning(self, task, seconds_overdue: int) -> None:
        """Send warning alert."""
        alert_manager = await get_alert_manager()
        await alert_manager.send_escalation_alert(
            task_id=task.task_id,
            task_type=task.task_type.value,
            priority=task.priority,
            deadline_exceeded_seconds=seconds_overdue,
        )

    async def _escalate_to_oncall(self, task) -> None:
        """Escalate to on-call team."""
        # Increase priority
        task.priority = min(100, task.priority + 10)
        await self.manager.update_task_status(
            task.task_id,
            task.status,
            priority=task.priority,
        )

        alert_manager = await get_alert_manager()
        await alert_manager.send_escalation_alert(
            task_id=task.task_id,
            task_type=task.task_type.value,
            priority=task.priority,
            deadline_exceeded_seconds=int(
                (datetime.utcnow() - task.deadline).total_seconds()
            ),
        )

    async def _escalate_to_exec(self, task) -> None:
        """Escalate to executive level."""
        # Set max priority
        task.priority = 100
        await self.manager.update_task_status(
            task.task_id,
            task.status,
            priority=task.priority,
        )

        alert_manager = await get_alert_manager()
        await alert_manager.send_escalation_alert(
            task_id=task.task_id,
            task_type=task.task_type.value,
            priority=task.priority,
            deadline_exceeded_seconds=int(
                (datetime.utcnow() - task.deadline).total_seconds()
            ),
        )


class EscalationMonitor:
    """Background monitor for escalation policy."""

    def __init__(self, policy: EscalationPolicy, check_interval_seconds: int = 60):
        self.policy = policy
        self.check_interval = check_interval_seconds
        self.running = False

    async def start(self) -> None:
        """Start background monitoring."""
        self.running = True
        while self.running:
            try:
                await self.policy.check_overdue_tasks()
                await asyncio.sleep(self.check_interval)
            except Exception:
                await asyncio.sleep(self.check_interval)

    async def stop(self) -> None:
        """Stop background monitoring."""
        self.running = False


async def create_escalation_monitor() -> EscalationMonitor:
    """Create and start escalation monitor."""
    manager = await get_manager()
    policy = EscalationPolicy(manager)
    monitor = EscalationMonitor(policy)
    return monitor
