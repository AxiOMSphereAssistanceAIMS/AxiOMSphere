"""
logi_task_queue.py

Pending task artifact writer for Logi.

Phase 1: writes only to allowlisted local dirs (no direct Redis write).
Phase 2: integration with existing Redis scheduler via allowlisted API.

Allowed paths:
  aims_workspace/logi_tasks/pending/
  aims_workspace/logi_tasks/scheduled/

Persistent writes require confirmation (handled by caller via confirmation flow).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PENDING_DIR = _ROOT / "aims_workspace" / "logi_tasks" / "pending"
_SCHEDULED_DIR = _ROOT / "aims_workspace" / "logi_tasks" / "scheduled"


@dataclass
class LogiTaskRecord:
    task_id: str
    title: str
    description: str
    action_type: str        # queue_task_allowlisted | schedule_task_allowlisted
    created_at: str
    requested_by: str
    schedule_hint: str      # "asap" | "tonight" | ISO datetime | "recurring:daily"
    priority: str           # low | normal | high
    status: str             # pending | scheduled | completed | failed
    notes: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)


def _task_id(title: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = hashlib.sha256(f"{title}:{ts}".encode()).hexdigest()[:8]
    return f"logi_task_{ts}_{h}"


def write_pending_task(
    title: str,
    description: str,
    requested_by: str = "0",
    schedule_hint: str = "asap",
    priority: str = "normal",
    params: dict | None = None,
) -> LogiTaskRecord:
    """Write a pending task artifact. Caller must have obtained confirmation first."""
    now = datetime.now(timezone.utc).isoformat()
    task = LogiTaskRecord(
        task_id=_task_id(title),
        title=title,
        description=description,
        action_type="queue_task_allowlisted",
        created_at=now,
        requested_by=requested_by,
        schedule_hint=schedule_hint,
        priority=priority,
        status="pending",
        params=params or {},
    )
    _PENDING_DIR.mkdir(parents=True, exist_ok=True)
    path = _PENDING_DIR / f"{task.task_id}.json"
    path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False), encoding="utf-8")
    return task


def write_scheduled_task(
    title: str,
    description: str,
    schedule_hint: str,
    requested_by: str = "0",
    priority: str = "normal",
    params: dict | None = None,
) -> LogiTaskRecord:
    """Write a scheduled task artifact. Caller must have obtained confirmation first."""
    now = datetime.now(timezone.utc).isoformat()
    task = LogiTaskRecord(
        task_id=_task_id(title),
        title=title,
        description=description,
        action_type="schedule_task_allowlisted",
        created_at=now,
        requested_by=requested_by,
        schedule_hint=schedule_hint,
        priority=priority,
        status="scheduled",
        params=params or {},
    )
    _SCHEDULED_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCHEDULED_DIR / f"{task.task_id}.json"
    path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False), encoding="utf-8")
    return task


def list_pending_tasks(max_items: int = 20) -> list[dict]:
    """Return list of pending task dicts."""
    if not _PENDING_DIR.exists():
        return []
    tasks = []
    for p in sorted(_PENDING_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            tasks.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
        if len(tasks) >= max_items:
            break
    return tasks
