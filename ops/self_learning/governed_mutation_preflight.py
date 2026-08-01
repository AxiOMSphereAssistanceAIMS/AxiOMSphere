"""Fail-closed mutation preflight for autonomous wrappers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()


def mutation_preflight(
    repo: Path,
    *,
    task_id: str,
    target_branch: str,
    worktree_path: Path,
    lease_path: Path,
    owned_files: list[str],
    autonomous: bool = True,
) -> dict[str, Any]:
    reasons: list[str] = []
    try:
        current_branch = _git(repo, "branch", "--show-current")
        root = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    except (OSError, subprocess.CalledProcessError):
        return {"allowed": False, "decision": "DENY", "reasons": ["REPOSITORY_CONTEXT_UNAVAILABLE"]}
    if autonomous and (target_branch == "main" or current_branch == "main"):
        reasons.append("DIRECT_MAIN_BRANCH_DENIED")
    if worktree_path.resolve() == root:
        reasons.append("SHARED_MAIN_WORKTREE_DENIED")
    if not lease_path.exists():
        reasons.append("LEASE_MISSING")
    else:
        requested = set(owned_files)
        valid_lease = False
        for line in lease_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("task_id") == task_id and row.get("status") in {"LEASED", "WORKING"} and requested.issubset(set(row.get("owned_files", []))):
                valid_lease = True
                break
        if not valid_lease:
            reasons.append("ACTIVE_FILE_LEASE_MISSING")
    return {"allowed": not reasons, "decision": "ALLOW_ISOLATED_MUTATION" if not reasons else "DENY", "reasons": reasons, "branch": current_branch, "worktree": str(worktree_path.resolve())}
