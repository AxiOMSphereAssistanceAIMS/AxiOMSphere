from __future__ import annotations

import pytest

from ops.self_learning.autonomous_change_governance import (
    ChangeRequest,
    claim_files,
    direct_main_commit_denial,
    register_change,
    review_transition,
)
from ops.ft.traini.autopilot.source_version_registry import observe_source, persist_closeout


def test_direct_main_commit_is_denied(tmp_path) -> None:
    with pytest.raises(PermissionError):
        register_change(tmp_path / "changes.jsonl", agent_id="a", session_id="s", target_branch="main", worktree_path="/tmp/w", base_commit="abc", owned_files=["x"], owned_components=["c"])
    assert direct_main_commit_denial("main")["allowed"] is False


def test_overlapping_file_lease_is_denied(tmp_path) -> None:
    path = tmp_path / "changes.jsonl"
    request = register_change(path, agent_id="a", session_id="s", target_branch="p1/a", worktree_path="/tmp/w1", base_commit="abc", owned_files=["ops/a.py"], owned_components=["traini"])
    assert claim_files(tmp_path / "leases.jsonl", request)["status"] == "LEASED"
    other = ChangeRequest(task_id="other", agent_id="b", session_id="s2", target_branch="p1/b", worktree_path="/tmp/w2", base_commit="abc", owned_files=["ops/a.py"], owned_components=["traini"])
    assert claim_files(tmp_path / "leases.jsonl", other)["status"] == "DENIED_OVERLAPPING_LEASE"


def test_review_requires_independent_reviewer() -> None:
    request = ChangeRequest(task_id="t", agent_id="agent", session_id="session", target_branch="p1/x", worktree_path="/tmp/w", base_commit="abc", owned_files=[], owned_components=[])
    assert review_transition(request, approved=True, reviewer_id="agent")["status"] == "REVIEW_REJECTED"
    assert review_transition(request, approved=True, reviewer_id="reviewer")["status"] == "APPROVED_FOR_CONTROLLED_MERGE"


def test_source_versioning_is_idempotent_and_changes_increment(tmp_path) -> None:
    registry = tmp_path / "source_versions.jsonl"
    first = observe_source(registry, logical_source_id="source-1", source_type="engineering_contract_resolution", producer="argus", source_hash="h1", cycle_id="A")
    same = observe_source(registry, logical_source_id="source-1", source_type="engineering_contract_resolution", producer="argus", source_hash="h1", cycle_id="B")
    changed = observe_source(registry, logical_source_id="source-1", source_type="engineering_contract_resolution", producer="argus", source_hash="h2", cycle_id="C")
    assert first["source_version"] == "v1" and first["version_created"] is True
    assert same["source_version"] == "v1" and same["version_created"] is False
    assert changed["source_version"] == "v2" and changed["changed"] is True
    closeout = persist_closeout(tmp_path / "closeouts.jsonl", first, status="CLOSED")
    assert closeout["source_version"] == "v1"
