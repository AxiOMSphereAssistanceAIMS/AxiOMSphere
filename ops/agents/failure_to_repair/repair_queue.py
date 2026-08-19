from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import fcntl

ROOT = Path(__file__).resolve().parents[3]
QUEUE_PATH = ROOT / "aims_workspace" / "repair" / "queue" / "repair_queue.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace the authoritative queue atomically.  A direct truncate/write can
    # expose a partial queue after a process crash and can lose concurrent
    # updates when two pollers read the same snapshot.
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _locked_queue(path: Path):
    """Serialize queue read/decision/write transactions across processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    handle = lock_path.open("a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _unlock_queue(handle: Any) -> None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def load_repair_queue(path: Path | None = None) -> list[dict[str, Any]]:
    return _read_lines(path or QUEUE_PATH)


@dataclass
class RepairQueueItem:
    repair_id: str
    event_id: str
    created_at: str
    status: str
    repair_class: str
    tool: str
    source_path: str
    run_id: str | None
    slot: str | None
    reason: str
    attempts: int
    max_attempts: int
    evidence_dir: str
    verification: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_duplicate(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    same_identity = (
        existing.get("run_id") == candidate.get("run_id")
        and existing.get("repair_class") == candidate.get("repair_class")
        and existing.get("reason") == candidate.get("reason")
    )
    if not same_identity:
        return False
    if existing.get("status") == "FAILED":
        return False
    try:
        created = datetime.fromisoformat(str(existing.get("created_at")).replace("Z", "+00:00"))
    except Exception:
        return True
    return datetime.now(timezone.utc) - created < timedelta(hours=24)


def enqueue_repair_item(item: RepairQueueItem, *, path: Path | None = None) -> tuple[RepairQueueItem, bool]:
    queue_path = path or QUEUE_PATH
    lock = _locked_queue(queue_path)
    try:
        queue = load_repair_queue(queue_path)
        candidate = item.to_dict()
        for existing in queue:
            if _is_duplicate(existing, candidate):
                return item, False
        queue.append(candidate)
        _write_lines(queue_path, queue)
        return item, True
    finally:
        _unlock_queue(lock)


def restart_existing_repair_item(
    *,
    repair_id: str,
    expected_status: str,
    idempotency_key: str,
    restart_record: dict[str, Any],
    path: Path | None = None,
) -> dict[str, Any]:
    """CAS/reconcile one existing lineage through the authoritative queue file.

    This is the existing queue's continuation operation, not a second queue.
    It is deliberately path-injectable so certification namespaces can exercise
    the real mutation without touching the production queue.
    """
    queue_path = path or QUEUE_PATH
    lock = _locked_queue(queue_path)
    try:
        queue = load_repair_queue(queue_path)
        for row in queue:
            if row.get("restart_idempotency_key") == idempotency_key:
                return {"status": "RECONCILED_IDEMPOTENT", "mutated": False, "repair_id": repair_id}
        matches = [row for row in queue if row.get("repair_id") == repair_id]
        if len(matches) != 1:
            return {"status": "CAS_FAILED_LINEAGE_NOT_FOUND", "mutated": False, "repair_id": repair_id}
        row = matches[0]
        if row.get("status") != expected_status:
            return {"status": "CAS_FAILED_QUEUE_STATE", "mutated": False, "repair_id": repair_id,
                    "actual_status": row.get("status"), "expected_status": expected_status}
        if int(row.get("attempts", 0)) >= int(row.get("max_attempts", 0)):
            return {"status": "CAS_FAILED_RETRY_EXHAUSTED", "mutated": False, "repair_id": repair_id}
        row["status"] = "QUEUED"
        row["attempts"] = int(row.get("attempts", 0)) + 1
        row["restart_idempotency_key"] = idempotency_key
        row["restart_record"] = dict(restart_record)
        row["restarted_at"] = _now()
        _write_lines(queue_path, queue)
        return {"status": "RESTARTED_EXISTING_LINEAGE", "mutated": True, "repair_id": repair_id,
                "attempt": row["attempts"], "idempotency_key": idempotency_key}
    finally:
        _unlock_queue(lock)


def complete_existing_repair_item(*, repair_id: str, expected_status: str = "QUEUED",
                                  verification: dict[str, Any] | None = None,
                                  path: Path | None = None) -> dict[str, Any]:
    """Close the same queue lineage after bounded verification."""
    queue_path = path or QUEUE_PATH
    lock = _locked_queue(queue_path)
    try:
        queue = load_repair_queue(queue_path)
        matches = [row for row in queue if row.get("repair_id") == repair_id]
        if len(matches) != 1:
            return {"status": "COMPLETION_FAILED_LINEAGE_NOT_FOUND", "mutated": False, "repair_id": repair_id}
        row = matches[0]
        if row.get("status") != expected_status:
            return {"status": "COMPLETION_FAILED_QUEUE_STATE", "mutated": False, "repair_id": repair_id,
                    "actual_status": row.get("status"), "expected_status": expected_status}
        row["status"] = "COMPLETED_VERIFIED"
        row["verification"] = list(row.get("verification") or []) + [dict(verification or {})]
        _write_lines(queue_path, queue)
        return {"status": "COMPLETED_VERIFIED", "mutated": True, "repair_id": repair_id}
    finally:
        _unlock_queue(lock)


def make_repair_queue_item(
    *,
    event: dict[str, Any],
    classification: dict[str, Any],
    tool: str,
    evidence_dir: str,
    max_attempts: int = 3,
) -> RepairQueueItem:
    return RepairQueueItem(
        repair_id=f"repair_{uuid.uuid4().hex[:12]}",
        event_id=str(event.get("event_id") or ""),
        created_at=_now(),
        status="QUEUED",
        repair_class=str(classification.get("repair_class") or "UNCLASSIFIED_FAILURE"),
        tool=tool,
        source_path=str(event.get("source_path") or ""),
        run_id=event.get("run_id"),
        slot=event.get("slot"),
        reason=str(event.get("reason") or ""),
        attempts=0,
        max_attempts=max_attempts,
        evidence_dir=evidence_dir,
        verification=list(classification.get("next_required_verification") or []),
    )
