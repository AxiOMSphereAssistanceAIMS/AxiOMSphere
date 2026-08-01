"""Read-only census and dry-run planning for active session migration."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return ""


def capture_process_state(row: dict[str, Any], repo: Path) -> dict[str, Any]:
    state = dict(row)
    command = row.get("command", "")
    state["wrapper_type"] = "claude" if "claude" in command.lower() else "codex" if "codex" in command.lower() else "support_or_unknown"
    state["permissions_mode"] = "DANGEROUS_SKIP_PERMISSIONS" if "dangerously-skip-permissions" in command else "UNKNOWN"
    status = _git(repo, "status", "--porcelain=v1")
    state["branch"] = _git(repo, "branch", "--show-current").strip() or row.get("branch", "UNKNOWN")
    state["base_commit"] = _git(repo, "rev-parse", "HEAD").strip() or None
    state["head_commit"] = state["base_commit"]
    state["git_status"] = status
    state["uncommitted_diff_hash"] = hashlib.sha256(status.encode()).hexdigest()
    state["task_context_available"] = bool(row.get("session_path"))
    state["lease_status"] = "UNKNOWN_READ_ONLY"
    state["commit_capability"] = "POSSIBLE_MAIN_CONTEXT" if state["branch"] == "main" else "UNKNOWN"
    state["classification"] = "OPERATOR_HOLD" if row.get("classification") == "AUTONOMOUS_CANDIDATE" else row.get("classification")
    return state


def build_overlap_matrix(states: list[dict[str, Any]]) -> dict[str, Any]:
    return {"same_main_context_count": sum(1 for state in states if state.get("branch") == "main"), "overlap_analysis": "requires per-file snapshots before migration", "states": [(s.get("pid"), s.get("branch"), s.get("worktree")) for s in states]}
