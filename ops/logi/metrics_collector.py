"""Metrics Collector — Prometheus-compatible metrics export.

Exports:
- Task completion rates
- Repair success rates
- Model improvement tracking
- Latency metrics
"""
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from logi.project_state_manager import (
    ProjectStateManager,
    TaskStatus,
    TaskType,
    get_manager,
)


class MetricsCollector:
    """Collect operational metrics for monitoring."""

    def __init__(self, manager: ProjectStateManager):
        self.manager = manager
        self.start_time = time.time()
        self.metrics: Dict[str, Any] = {}

    async def collect(self) -> Dict[str, Any]:
        """Collect all metrics."""
        stats = await self.manager.get_stats()
        now = datetime.utcnow()

        # Task metrics
        total_tasks = stats.get("total_tasks", 0)
        by_status = stats.get("by_status", {})
        by_type = stats.get("by_type", {})

        # Calculate rates
        completed = by_status.get("succeeded", 0)
        failed = by_status.get("failed", 0)
        pending = by_status.get("pending", 0)
        in_progress = by_status.get("in_progress", 0)

        total_finished = completed + failed
        success_rate = (completed / total_finished * 100) if total_finished > 0 else 0

        # Repair metrics
        repairs = by_type.get("repair", 0)
        repair_success = (
            sum(
                1
                for task in await self.manager.list_tasks(task_type=TaskType.REPAIR)
                if task.status == TaskStatus.SUCCEEDED
            )
            if repairs > 0
            else 0
        )
        repair_success_rate = (
            repair_success / repairs * 100 if repairs > 0 else 0
        )

        self.metrics = {
            "timestamp": now.isoformat(),
            "uptime_seconds": time.time() - self.start_time,
            # Task counts
            "tasks_total": total_tasks,
            "tasks_pending": pending,
            "tasks_in_progress": in_progress,
            "tasks_succeeded": completed,
            "tasks_failed": failed,
            "tasks_blocked": sum(
                1
                for task in await self.manager.list_tasks()
                if task.depends_on
            ),
            # Rates
            "task_success_rate": success_rate,
            "task_completion_rate": (
                total_finished / total_tasks * 100 if total_tasks > 0 else 0
            ),
            # Repair metrics
            "repairs_total": repairs,
            "repairs_succeeded": repair_success,
            "repair_success_rate": repair_success_rate,
            # Task type breakdown
            "tasks_by_type": by_type,
            "tasks_by_status": by_status,
        }

        return self.metrics

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = [
            f"# HELP aims_tasks_total Total number of tasks",
            f"# TYPE aims_tasks_total gauge",
            f'aims_tasks_total {{}} {self.metrics.get("tasks_total", 0)}',
            f"# HELP aims_task_success_rate Task success rate percentage",
            f"# TYPE aims_task_success_rate gauge",
            f'aims_task_success_rate {{}} {self.metrics.get("task_success_rate", 0)}',
            f"# HELP aims_repair_success_rate Repair success rate percentage",
            f"# TYPE aims_repair_success_rate gauge",
            f'aims_repair_success_rate {{}} {self.metrics.get("repair_success_rate", 0)}',
            f"# HELP aims_uptime_seconds System uptime in seconds",
            f"# TYPE aims_uptime_seconds gauge",
            f'aims_uptime_seconds {{}} {self.metrics.get("uptime_seconds", 0)}',
        ]
        return "\n".join(lines) + "\n"


async def create_metrics_collector() -> MetricsCollector:
    """Create metrics collector."""
    manager = await get_manager()
    return MetricsCollector(manager)
