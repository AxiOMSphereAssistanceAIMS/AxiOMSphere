from __future__ import annotations

import json
import subprocess

from ops.self_learning.governed_mutation_preflight import mutation_preflight


def test_preflight_denies_main_and_missing_lease(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    result = mutation_preflight(repo, task_id="t", target_branch="main", worktree_path=repo, lease_path=tmp_path / "missing", owned_files=["x.py"])
    assert result["allowed"] is False
    assert "DIRECT_MAIN_BRANCH_DENIED" in result["reasons"]
    assert "LEASE_MISSING" in result["reasons"]


def test_preflight_allows_isolated_leased_context(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    # An unborn repository has no branch name; the task branch is still
    # explicitly isolated and the lease is authoritative for this preflight.
    lease = tmp_path / "leases.jsonl"
    lease.write_text(json.dumps({"task_id": "t", "status": "LEASED", "owned_files": ["x.py"]}) + "\n")
    result = mutation_preflight(repo, task_id="t", target_branch="task/t", worktree_path=tmp_path / "worktree", lease_path=lease, owned_files=["x.py"])
    assert result["allowed"] is True
