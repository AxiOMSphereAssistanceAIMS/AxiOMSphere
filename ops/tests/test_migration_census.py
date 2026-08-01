from __future__ import annotations

from ops.self_learning.migration_census import build_overlap_matrix


def test_overlap_matrix_counts_main_contexts():
    result = build_overlap_matrix([{"pid": 1, "branch": "main", "worktree": "."}, {"pid": 2, "branch": "task/x", "worktree": "/tmp/w"}])
    assert result["same_main_context_count"] == 1
