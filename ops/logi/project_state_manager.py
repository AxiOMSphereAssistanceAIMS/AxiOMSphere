"""Project State Manager — unified DAG-based task orchestration for AIMS.

Tracks all project work:
- Tasks (repair, training, analysis, deployment)
- Dependencies between tasks
- Scheduling and deadlines
- Task status and results
- Priority queue

Backend: Redis for persistence and pub/sub coordination
"""
from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Set, Optional, Any
from uuid import uuid4

import redis.asyncio as redis


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Task categories for orchestration."""
    REPAIR = "repair"
    TRAINING = "training"
    ANALYSIS = "analysis"
    DEPLOYMENT = "deployment"
    HEALTH_CHECK = "health_check"
    SYNC = "sync"


@dataclass
class Task:
    """Atomic unit of work in the project."""
    task_id: str = field(default_factory=lambda: str(uuid4()))
    task_type: TaskType = TaskType.REPAIR
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING

    # Dependencies
    depends_on: List[str] = field(default_factory=list)  # tasks that must finish first
    blocking: List[str] = field(default_factory=list)    # tasks waiting for this one

    # Metadata
    created_by: str = ""                                  # "argus", "logi", "bedrock", "user"
    created_at: datetime = field(default_factory=datetime.utcnow)
    scheduled_for: Optional[datetime] = None              # planned execution time
    deadline: Optional[datetime] = None                   # hard deadline

    # Execution
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_duration_seconds: int = 0

    # Priority
    priority: int = 50  # 0=lowest, 100=highest (default=medium)

    # Results
    result: Optional[Dict[str, Any]] = None               # output when done
    error: Optional[str] = None                           # if failed
    retries_left: int = 3

    def is_runnable(self) -> bool:
        """Can this task run now (all deps complete)?"""
        return self.status == TaskStatus.PENDING and not self.depends_on

    def mark_blocked(self, reason: str):
        """Mark task as blocked and store reason."""
        self.status = TaskStatus.BLOCKED
        if not self.error:
            self.error = reason

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        d = asdict(self)
        d['task_type'] = self.task_type.value
        d['status'] = self.status.value
        d['created_at'] = self.created_at.isoformat()
        d['scheduled_for'] = self.scheduled_for.isoformat() if self.scheduled_for else None
        d['deadline'] = self.deadline.isoformat() if self.deadline else None
        d['started_at'] = self.started_at.isoformat() if self.started_at else None
        d['completed_at'] = self.completed_at.isoformat() if self.completed_at else None
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> Task:
        """Deserialize from JSON dict."""
        # Parse enums
        d['task_type'] = TaskType(d.get('task_type', 'repair'))
        d['status'] = TaskStatus(d.get('status', 'pending'))

        # Parse timestamps
        for ts_field in ['created_at', 'scheduled_for', 'deadline', 'started_at', 'completed_at']:
            if d.get(ts_field):
                d[ts_field] = datetime.fromisoformat(d[ts_field])

        return Task(**d)


class ProjectStateManager:
    """Manage project state: tasks, dependencies, scheduling."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self._tasks_local: Dict[str, Task] = {}  # fallback in-memory cache

    async def connect(self):
        """Connect to Redis backend."""
        try:
            self.redis_client = await redis.from_url(self.redis_url)
            await self.redis_client.ping()
            print(f"✓ Connected to Redis at {self.redis_url}")
        except Exception as e:
            print(f"⚠ Redis connection failed: {e}, using in-memory fallback")
            self.redis_client = None

    async def disconnect(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()

    # ============ Task CRUD ============

    async def create_task(
        self,
        task_type: TaskType,
        title: str,
        created_by: str,
        depends_on: Optional[List[str]] = None,
        deadline: Optional[datetime] = None,
        priority: int = 50,
        estimated_duration_seconds: int = 0,
    ) -> Task:
        """Create a new task with optional dependencies."""
        task = Task(
            task_type=task_type,
            title=title,
            created_by=created_by,
            depends_on=depends_on or [],
            deadline=deadline,
            priority=priority,
            estimated_duration_seconds=estimated_duration_seconds,
        )

        # Validate dependencies exist
        for dep_id in task.depends_on:
            if not await self.get_task(dep_id):
                raise ValueError(f"Dependency {dep_id} not found")

        # Store
        await self._store_task(task)
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task by ID."""
        if self.redis_client:
            try:
                data = await self.redis_client.get(f"task:{task_id}")
                if data:
                    return Task.from_dict(json.loads(data))
            except Exception as e:
                print(f"⚠ Redis read failed: {e}")

        # Fallback to in-memory
        return self._tasks_local.get(task_id)

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Task:
        """Update task status and optionally result/error."""
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Update state
        old_status = task.status
        task.status = status
        if result:
            task.result = result
        if error:
            task.error = error

        # Timestamp transitions
        if status == TaskStatus.IN_PROGRESS and not task.started_at:
            task.started_at = datetime.utcnow()
        if status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = datetime.utcnow()

        # If succeeded, unblock dependent tasks
        if status == TaskStatus.SUCCEEDED:
            await self._unblock_dependents(task_id)

        # Store
        await self._store_task(task)

        return task

    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        task_type: Optional[TaskType] = None,
        created_by: Optional[str] = None,
    ) -> List[Task]:
        """List tasks matching optional filters."""
        if self.redis_client:
            try:
                # Scan Redis for all tasks
                pattern = "task:*"
                cursor = 0
                tasks = []
                while True:
                    cursor, keys = await self.redis_client.scan(cursor, match=pattern)
                    for key in keys:
                        data = await self.redis_client.get(key)
                        if data:
                            task = Task.from_dict(json.loads(data))
                            if self._matches_filter(task, status, task_type, created_by):
                                tasks.append(task)
                    if cursor == 0:
                        break
                return sorted(tasks, key=lambda t: t.priority, reverse=True)
            except Exception as e:
                print(f"⚠ Redis scan failed: {e}")

        # Fallback to in-memory
        tasks = [t for t in self._tasks_local.values()
                 if self._matches_filter(t, status, task_type, created_by)]
        return sorted(tasks, key=lambda t: t.priority, reverse=True)

    async def get_runnable_tasks(self) -> List[Task]:
        """Get tasks ready to execute (PENDING, no dependencies)."""
        all_tasks = await self.list_tasks(status=TaskStatus.PENDING)
        runnable = [t for t in all_tasks if t.is_runnable()]
        return sorted(runnable, key=lambda t: t.priority, reverse=True)

    async def get_blocked_tasks(self) -> List[Task]:
        """Get tasks currently blocked by dependencies."""
        all_tasks = await self.list_tasks()
        blocked = [t for t in all_tasks if t.status == TaskStatus.BLOCKED or t.depends_on]
        return sorted(blocked, key=lambda t: t.priority, reverse=True)

    # ============ Dependency Graph ============

    async def validate_dag(self) -> bool:
        """Check for cycles in dependency graph."""
        all_tasks = await self.list_tasks()
        task_map = {t.task_id: t for t in all_tasks}

        visited = set()
        rec_stack = set()

        def has_cycle(task_id: str) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)

            task = task_map.get(task_id)
            if not task:
                return False

            for dep_id in task.depends_on:
                if dep_id not in visited:
                    if has_cycle(dep_id):
                        return True
                elif dep_id in rec_stack:
                    return True

            rec_stack.remove(task_id)
            return False

        for task_id in task_map:
            if task_id not in visited:
                if has_cycle(task_id):
                    return False

        return True

    async def get_task_dependencies(self, task_id: str) -> Dict[str, Any]:
        """Get full dependency info for a task."""
        task = await self.get_task(task_id)
        if not task:
            return {}

        all_tasks = await self.list_tasks()
        task_map = {t.task_id: t for t in all_tasks}

        # Walk up the DAG
        upstream = set()
        queue = list(task.depends_on)
        while queue:
            dep_id = queue.pop(0)
            if dep_id not in upstream:
                upstream.add(dep_id)
                dep_task = task_map.get(dep_id)
                if dep_task:
                    queue.extend(dep_task.depends_on)

        # Walk down the DAG
        downstream = set()
        queue = list(task.blocking)
        while queue:
            blocked_id = queue.pop(0)
            if blocked_id not in downstream:
                downstream.add(blocked_id)
                blocked_task = task_map.get(blocked_id)
                if blocked_task:
                    queue.extend(blocked_task.blocking)

        return {
            "task_id": task_id,
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "upstream": sorted(upstream),
            "downstream": sorted(downstream),
            "immediate_deps": task.depends_on,
            "immediate_blocking": task.blocking,
        }

    # ============ Internal Helpers ============

    async def _store_task(self, task: Task):
        """Store task in Redis and in-memory cache."""
        self._tasks_local[task.task_id] = task

        if self.redis_client:
            try:
                key = f"task:{task.task_id}"
                data = json.dumps(task.to_dict())
                await self.redis_client.set(key, data)
            except Exception as e:
                print(f"⚠ Redis write failed: {e}")

    async def _unblock_dependents(self, completed_task_id: str):
        """When a task completes, remove it from depends_on lists."""
        all_tasks = await self.list_tasks()

        for task in all_tasks:
            if completed_task_id in task.depends_on:
                task.depends_on.remove(completed_task_id)

                # If no more deps, mark as runnable
                if not task.depends_on and task.status == TaskStatus.BLOCKED:
                    task.status = TaskStatus.PENDING

                await self._store_task(task)

    @staticmethod
    def _matches_filter(
        task: Task,
        status: Optional[TaskStatus],
        task_type: Optional[TaskType],
        created_by: Optional[str],
    ) -> bool:
        """Check if task matches filter criteria."""
        if status and task.status != status:
            return False
        if task_type and task.task_type != task_type:
            return False
        if created_by and task.created_by != created_by:
            return False
        return True

    # ============ Statistics ============

    async def get_stats(self) -> Dict[str, Any]:
        """Get project statistics."""
        all_tasks = await self.list_tasks()

        by_status = {}
        by_type = {}

        for task in all_tasks:
            by_status[task.status.value] = by_status.get(task.status.value, 0) + 1
            by_type[task.task_type.value] = by_type.get(task.task_type.value, 0) + 1

        # Calculate critical path
        runnable = await self.get_runnable_tasks()
        blocked = await self.get_blocked_tasks()

        return {
            "total_tasks": len(all_tasks),
            "by_status": by_status,
            "by_type": by_type,
            "runnable_count": len(runnable),
            "blocked_count": len(blocked),
            "success_rate": (by_status.get('succeeded', 0) / max(len(all_tasks), 1)) * 100,
        }


# ============ Singleton Instance ============

_manager_instance: Optional[ProjectStateManager] = None


async def get_manager(redis_url: str = "redis://localhost:6379") -> ProjectStateManager:
    """Get or create the global ProjectStateManager instance."""
    global _manager_instance

    if not _manager_instance:
        _manager_instance = ProjectStateManager(redis_url)
        await _manager_instance.connect()

    return _manager_instance


if __name__ == "__main__":
    # Quick test
    async def test():
        mgr = await get_manager()

        # Create a repair task
        repair = await mgr.create_task(
            task_type=TaskType.REPAIR,
            title="Fix timeout in service X",
            created_by="argus",
            priority=80,
            estimated_duration_seconds=600,
        )
        print(f"Created repair task: {repair.task_id}")

        # Create a training task that depends on repair
        training = await mgr.create_task(
            task_type=TaskType.TRAINING,
            title="Retrain model after repair",
            created_by="traini",
            depends_on=[repair.task_id],
            priority=70,
            estimated_duration_seconds=3600,
        )
        print(f"Created training task: {training.task_id} (depends on {repair.task_id})")

        # Get stats
        stats = await mgr.get_stats()
        print(f"Stats: {json.dumps(stats, indent=2)}")

        # Check DAG
        is_valid = await mgr.validate_dag()
        print(f"DAG valid: {is_valid}")

        await mgr.disconnect()

    asyncio.run(test())
