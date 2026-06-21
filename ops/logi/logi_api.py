"""Logi Status API — REST endpoints for project orchestration dashboard.

Provides:
- /api/logi/status — current project state
- /api/logi/tasks — task list with filtering
- /api/logi/metrics — project statistics and health
- /api/logi/dependencies/{task_id} — dependency graph for a task
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

import asyncio
from fastapi.responses import Response

from ops.logi.project_state_manager import (
    ProjectStateManager,
    Task,
    TaskStatus,
    TaskType,
    get_manager,
)
from ops.logi.event_bus import EventBus, get_bus, EventType
from ops.logi.telegram_alerts import TelegramAlertManager, get_alert_manager
from ops.logi.escalation_policy import create_escalation_monitor
from ops.logi.metrics_collector import create_metrics_collector


# ============ Pydantic Models for API ============

class TaskResponse(BaseModel):
    """Task representation for API responses."""
    task_id: str
    task_type: str
    title: str
    description: str
    status: str
    created_by: str
    created_at: str
    deadline: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    priority: int
    depends_on: List[str]
    blocking: List[str]
    estimated_duration_seconds: int
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    retries_left: int


class ProjectStatusResponse(BaseModel):
    """Current project state snapshot."""
    timestamp: str
    total_tasks: int
    by_status: Dict[str, int]
    by_type: Dict[str, int]
    runnable_count: int
    blocked_count: int
    success_rate: float
    next_urgent_task: Optional[TaskResponse]


class ProjectMetricsResponse(BaseModel):
    """Project health and performance metrics."""
    timestamp: str
    tasks_completed_today: int
    tasks_failed_today: int
    avg_task_duration_seconds: float
    repair_success_rate: float
    model_eval_score: Optional[float]
    last_training_duration_seconds: Optional[int]
    events_published: Dict[str, int]


class DependencyGraphResponse(BaseModel):
    """Dependency information for a task."""
    task_id: str
    upstream_count: int
    downstream_count: int
    immediate_deps: List[str]
    immediate_blocking: List[str]
    upstream: List[str]
    downstream: List[str]


# ============ FastAPI App ============

app = FastAPI(
    title="Logi Project Orchestrator API",
    description="AIMS project state and task orchestration",
    version="1.0",
)

# Global managers (lazily initialized)
_manager: Optional[ProjectStateManager] = None
_bus: Optional[EventBus] = None
_alert_manager: Optional[TelegramAlertManager] = None
_escalation_monitor = None
_metrics_collector = None


@app.on_event("startup")
async def startup():
    """Initialize managers on startup."""
    global _manager, _bus, _alert_manager, _escalation_monitor, _metrics_collector
    _manager = await get_manager()
    _bus = await get_bus()
    _alert_manager = await get_alert_manager()
    _metrics_collector = await create_metrics_collector()
    _escalation_monitor = await create_escalation_monitor()

    # Start background monitoring
    asyncio.create_task(_escalation_monitor.start())


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    if _escalation_monitor:
        _escalation_monitor.running = False
    if _manager:
        await _manager.disconnect()
    if _bus:
        await _bus.disconnect()


async def get_or_init_manager() -> ProjectStateManager:
    """Get manager instance, initialize if needed."""
    global _manager
    if not _manager:
        _manager = await get_manager()
    return _manager


async def get_or_init_bus() -> EventBus:
    """Get bus instance, initialize if needed."""
    global _bus
    if not _bus:
        _bus = await get_bus()
    return _bus


def task_to_response(task: Task) -> TaskResponse:
    """Convert internal Task to API response."""
    return TaskResponse(
        task_id=task.task_id,
        task_type=task.task_type.value,
        title=task.title,
        description=task.description,
        status=task.status.value,
        created_by=task.created_by,
        created_at=task.created_at.isoformat(),
        deadline=task.deadline.isoformat() if task.deadline else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        priority=task.priority,
        depends_on=task.depends_on,
        blocking=task.blocking,
        estimated_duration_seconds=task.estimated_duration_seconds,
        result=task.result,
        error=task.error,
        retries_left=task.retries_left,
    )


# ============ Status Endpoints ============

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "logi-api"}


@app.get("/api/logi/status", response_model=ProjectStatusResponse)
async def get_project_status():
    """Get current project state snapshot."""
    manager = await get_or_init_manager()

    stats = await manager.get_stats()
    runnable = await manager.get_runnable_tasks()
    blocked = await manager.get_blocked_tasks()

    # Find most urgent task
    next_urgent = None
    if runnable:
        next_urgent = task_to_response(runnable[0])

    return ProjectStatusResponse(
        timestamp=datetime.utcnow().isoformat(),
        total_tasks=stats['total_tasks'],
        by_status=stats['by_status'],
        by_type=stats['by_type'],
        runnable_count=stats['runnable_count'],
        blocked_count=stats['blocked_count'],
        success_rate=stats['success_rate'],
        next_urgent_task=next_urgent,
    )


@app.get("/api/logi/tasks", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    created_by: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """List tasks with optional filtering."""
    manager = await get_or_init_manager()

    # Parse enums
    status_enum = TaskStatus(status) if status else None
    type_enum = TaskType(task_type) if task_type else None

    tasks = await manager.list_tasks(
        status=status_enum,
        task_type=type_enum,
        created_by=created_by,
    )

    return [task_to_response(t) for t in tasks[:limit]]


@app.get("/api/logi/tasks/runnable", response_model=List[TaskResponse])
async def get_runnable_tasks(limit: int = Query(50, ge=1, le=500)):
    """Get tasks ready to execute."""
    manager = await get_or_init_manager()
    tasks = await manager.get_runnable_tasks()
    return [task_to_response(t) for t in tasks[:limit]]


@app.get("/api/logi/tasks/blocked", response_model=List[TaskResponse])
async def get_blocked_tasks(limit: int = Query(50, ge=1, le=500)):
    """Get tasks blocked by dependencies."""
    manager = await get_or_init_manager()
    tasks = await manager.get_blocked_tasks()
    return [task_to_response(t) for t in tasks[:limit]]


@app.get("/api/logi/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """Get a single task by ID."""
    manager = await get_or_init_manager()
    task = await manager.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return task_to_response(task)


@app.get("/api/logi/metrics", response_model=ProjectMetricsResponse)
async def get_project_metrics():
    """Get project health metrics."""
    manager = await get_or_init_manager()
    bus = await get_or_init_bus()

    all_tasks = await manager.list_tasks()
    today_tasks = [t for t in all_tasks if t.created_at.date() == datetime.utcnow().date()]

    completed_today = len([t for t in today_tasks if t.status == TaskStatus.SUCCEEDED])
    failed_today = len([t for t in today_tasks if t.status == TaskStatus.FAILED])

    # Calculate average duration for completed tasks
    completed = [t for t in all_tasks if t.status == TaskStatus.SUCCEEDED]
    avg_duration = 0.0
    if completed:
        total_duration = sum(
            (t.completed_at - t.started_at).total_seconds()
            for t in completed
            if t.started_at and t.completed_at
        )
        avg_duration = total_duration / len(completed) if len(completed) > 0 else 0

    # Calculate repair success rate
    repairs = [t for t in all_tasks if t.task_type == TaskType.REPAIR]
    repair_success_rate = 0.0
    if repairs:
        successful = len([t for t in repairs if t.status == TaskStatus.SUCCEEDED])
        repair_success_rate = (successful / len(repairs)) * 100

    # Get event stats
    event_stats = await bus.get_event_stats()

    return ProjectMetricsResponse(
        timestamp=datetime.utcnow().isoformat(),
        tasks_completed_today=completed_today,
        tasks_failed_today=failed_today,
        avg_task_duration_seconds=avg_duration,
        repair_success_rate=repair_success_rate,
        model_eval_score=None,  # TODO: fetch from model registry
        last_training_duration_seconds=None,  # TODO: fetch from training logs
        events_published=event_stats,
    )


@app.get("/api/logi/metrics/prometheus")
async def get_metrics_prometheus():
    """Export metrics in Prometheus format."""
    global _metrics_collector
    if _metrics_collector:
        await _metrics_collector.collect()
        return Response(
            content=_metrics_collector.export_prometheus(),
            media_type="text/plain",
        )
    return Response(content="", media_type="text/plain")


@app.get("/api/logi/dependencies/{task_id}", response_model=DependencyGraphResponse)
async def get_task_dependencies(task_id: str):
    """Get full dependency graph for a task."""
    manager = await get_or_init_manager()
    deps = await manager.get_task_dependencies(task_id)

    if not deps:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return DependencyGraphResponse(**deps)


# ============ Task Management Endpoints (Protected) ============

class CreateTaskRequest(BaseModel):
    """Request to create a new task."""
    task_type: str
    title: str
    description: Optional[str] = ""
    created_by: str
    depends_on: Optional[List[str]] = None
    deadline: Optional[str] = None
    priority: Optional[int] = 50
    estimated_duration_seconds: Optional[int] = 0


@app.post("/api/logi/tasks", response_model=TaskResponse)
async def create_task(req: CreateTaskRequest):
    """Create a new task."""
    manager = await get_or_init_manager()
    bus = await get_or_init_bus()

    # Validate deadline format
    deadline = None
    if req.deadline:
        try:
            deadline = datetime.fromisoformat(req.deadline)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid deadline format")

    # Create task
    try:
        task = await manager.create_task(
            task_type=TaskType(req.task_type),
            title=req.title,
            created_by=req.created_by,
            depends_on=req.depends_on,
            deadline=deadline,
            priority=req.priority or 50,
            estimated_duration_seconds=req.estimated_duration_seconds or 0,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Publish event
    from ops.logi.event_bus import Event, EventSeverity
    event = Event(
        event_type=EventType.TASK_CREATED,
        source="logi-api",
        timestamp=datetime.utcnow(),
        severity=EventSeverity.INFO,
        data={"task_id": task.task_id, "title": task.title},
    )
    await bus.publish(event)

    return task_to_response(task)


class UpdateTaskRequest(BaseModel):
    """Request to update task status."""
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@app.patch("/api/logi/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, req: UpdateTaskRequest):
    """Update task status."""
    manager = await get_or_init_manager()
    bus = await get_or_init_bus()

    try:
        task = await manager.update_task_status(
            task_id=task_id,
            status=TaskStatus(req.status),
            result=req.result,
            error=req.error,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Publish event
    from ops.logi.event_bus import Event, EventSeverity
    event = Event(
        event_type=EventType.TASK_UPDATED,
        source="logi-api",
        timestamp=datetime.utcnow(),
        severity=EventSeverity.INFO,
        data={"task_id": task.task_id, "status": req.status},
    )
    await bus.publish(event)

    return task_to_response(task)


# ============ Event Endpoints ============

@app.get("/api/logi/events/{event_type}")
async def get_events(event_type: str, limit: int = Query(100, ge=1, le=1000)):
    """Get event history for a specific event type."""
    bus = await get_or_init_bus()

    try:
        evt_type = EventType(event_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {event_type}")

    events = await bus.get_events(evt_type, limit=limit)
    return [e.to_dict() for e in events]


@app.get("/api/logi/events/stats")
async def get_event_stats():
    """Get event statistics."""
    bus = await get_or_init_bus()
    stats = await bus.get_event_stats()
    return stats


# ============ Dashboard & Alert Testing ============

class TestAlertRequest(BaseModel):
    """Request to send test alert."""
    alert_type: str
    severity: Optional[str] = "CRITICAL"
    service: Optional[str] = "test-service"


@app.post("/api/logi/test/alert")
async def test_alert(req: TestAlertRequest):
    """Send test alert to Telegram (for dashboard testing)."""
    global _alert_manager
    if not _alert_manager:
        raise HTTPException(status_code=500, detail="Alert manager not initialized")

    if req.alert_type == "incident":
        result = await _alert_manager.send_incident_alert(
            incident_type="test_incident",
            severity=req.severity,
            service=req.service,
            error="This is a test alert",
            incident_id="test-001",
        )
    elif req.alert_type == "repair":
        result = await _alert_manager.send_repair_update(
            status="succeeded",
            repair_id="test-repair-001",
            fix="Test repair completed",
            duration_seconds=120,
        )
    elif req.alert_type == "escalation":
        result = await _alert_manager.send_escalation_alert(
            task_id="test-task-001",
            task_type="repair",
            priority=90,
            deadline_exceeded_seconds=3600,
        )
    elif req.alert_type == "status":
        status = await get_or_init_manager()
        stats = await status.get_stats()
        result = await _alert_manager.send_status_update(
            title="Test Status Update",
            total_tasks=stats.get("total_tasks", 0),
            runnable=0,
            blocked=0,
            success_rate=100.0,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown alert type: {req.alert_type}")

    return {
        "success": result,
        "alert_type": req.alert_type,
        "message": f"Alert {'sent' if result else 'not sent (check configuration)'}",
    }


@app.get("/api/logi/dashboard/status")
async def dashboard_status():
    """Get dashboard summary."""
    global _metrics_collector
    manager = await get_or_init_manager()
    stats = await manager.get_stats()

    metrics = {}
    if _metrics_collector:
        metrics = await _metrics_collector.collect()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "project": stats,
        "metrics": metrics,
        "alerts_enabled": bool(_alert_manager and _alert_manager.enabled),
        "escalation_active": _escalation_monitor is not None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8100,
        log_level="info",
    )
