"""Fail-closed governance primitives for autonomous repository changes.

The module is intentionally storage-agnostic: callers provide a JSONL registry
path, and every mutation is represented as an explicit state transition. It
does not perform a merge or edit source files.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChangeRequest:
    task_id: str
    agent_id: str
    session_id: str
    target_branch: str
    worktree_path: str
    base_commit: str
    owned_files: list[str]
    owned_components: list[str]
    allowed_actions: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=lambda: ["direct_main_commit", "training", "registry_mutation"])
    required_tests: list[str] = field(default_factory=list)
    review_gate: str = "REQUIRED"
    merge_gate: str = "CONTROLLED"
    status: str = "REGISTERED"
    created_at: str = field(default_factory=_now)
    rollback_commit: str | None = None


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def register_change(
    registry_path: Path,
    *,
    agent_id: str,
    session_id: str,
    target_branch: str,
    worktree_path: str,
    base_commit: str,
    owned_files: list[str],
    owned_components: list[str],
    required_tests: list[str] | None = None,
) -> ChangeRequest:
    if target_branch == "main":
        raise PermissionError("DIRECT_MAIN_COMMIT_DENIED: autonomous changes require an isolated branch")
    if not worktree_path or worktree_path == ".":
        raise PermissionError("ISOLATED_WORKTREE_REQUIRED")
    request = ChangeRequest(
        task_id=f"change_{uuid.uuid4().hex[:16]}",
        agent_id=agent_id,
        session_id=session_id,
        target_branch=target_branch,
        worktree_path=worktree_path,
        base_commit=base_commit,
        owned_files=sorted(set(owned_files)),
        owned_components=sorted(set(owned_components)),
        required_tests=required_tests or [],
    )
    _append(registry_path, asdict(request))
    return request


def claim_files(lease_path: Path, request: ChangeRequest) -> dict[str, Any]:
    existing: list[dict[str, Any]] = []
    if lease_path.exists():
        existing = [json.loads(line) for line in lease_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    requested = set(request.owned_files)
    collisions = [row for row in existing if row.get("status") in {"LEASED", "WORKING"} and requested.intersection(row.get("owned_files", [])) and row.get("task_id") != request.task_id]
    if collisions:
        return {"status": "DENIED_OVERLAPPING_LEASE", "task_id": request.task_id, "collisions": collisions}
    row = {"task_id": request.task_id, "owned_files": request.owned_files, "owned_components": request.owned_components, "status": "LEASED", "lease_created_at": _now()}
    _append(lease_path, row)
    return {"status": "LEASED", **row}


def review_transition(request: ChangeRequest, *, approved: bool, reviewer_id: str) -> dict[str, Any]:
    if not reviewer_id or reviewer_id in {request.agent_id, request.session_id}:
        return {"status": "REVIEW_REJECTED", "reason": "REVIEWER_NOT_INDEPENDENT", "task_id": request.task_id}
    if not approved:
        return {"status": "REVIEW_REJECTED", "reason": "REVIEWER_DECISION_REJECTED", "task_id": request.task_id}
    return {"status": "APPROVED_FOR_CONTROLLED_MERGE", "reviewer_id": reviewer_id, "task_id": request.task_id}


def direct_main_commit_denial(target_branch: str) -> dict[str, Any]:
    return {"target_branch": target_branch, "allowed": target_branch != "main", "decision": "DENY" if target_branch == "main" else "ALLOW_ISOLATED_BRANCH"}
