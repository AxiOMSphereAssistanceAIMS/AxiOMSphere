from __future__ import annotations

import json
from pathlib import Path

from ops.learning_capture.session_capture import build_wrapper_metadata
from ops.learning_capture.training_candidate_writer import append_training_candidate


def test_training_candidate_never_auto_approved(tmp_path: Path) -> None:
    paths = append_training_candidate(
        {
            "case_id": "case-1",
            "target_slot": "slot32",
            "target_agent": "Repairman/Logi",
            "candidate_type": "dpo",
            "approved_for_training": True,
        },
        output_root=tmp_path / "learning",
        axi_ft_root=tmp_path / "axi_ft_log",
    )
    for path in paths.values():
        line = Path(path).read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["approved_for_training"] is False
        assert data["requires_human_approval"] is True


def test_wrapper_metadata_schema() -> None:
    data = build_wrapper_metadata(
        agent_name="claude-code-local",
        target_slot="slot32",
        task_prompt="/tmp/task.md",
        command=["claude", "--print"],
        started_at_utc="2026-06-26T00:00:00Z",
        finished_at_utc="2026-06-26T00:01:00Z",
        exit_code=0,
        session_log_path="/tmp/session.log",
        start_status_path="/tmp/start.txt",
        end_status_path="/tmp/end.txt",
        diff_path="/tmp/diff.patch",
    )
    assert data["schema_version"] == "learning_capture_wrapper_v1"
    assert data["agent_name"] == "claude-code-local"
    assert data["target_slot"] == "slot32"
    assert data["command"] == ["claude", "--print"]
