from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ops.learning_capture.case_builder import build_agent_action_case
from ops.learning_capture.codex_comparison import build_codex_repair_comparison


def test_codex_repair_creates_dpo_candidate(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    prompt = tmp_path / "task.md"
    prompt.write_text("Implement MarkItDown production adapter", encoding="utf-8")
    evidence = tmp_path / "docsreg_markitdown_slot32_training_assessment_20260626"
    evidence.mkdir()
    (evidence / "slot32_training_assessment.md").write_text("assessment", encoding="utf-8")
    learning = tmp_path / "learning"
    case = build_agent_action_case(
        agent_name="slot32-local",
        target_slot="slot32",
        task_prompt_file=prompt,
        terminal_log=None,
        evidence_root=evidence,
        expected_deliverables=["ops/docsreg/extraction/markitdown_adapter.py"],
        output_root=learning,
        repo_root=tmp_path,
        case_id="markitdown-case",
    )
    codex_evidence = tmp_path / "docsreg_markitdown_production_activation"
    codex_evidence.mkdir()
    (codex_evidence / "markitdown_production_activation_status.md").write_text("fixed", encoding="utf-8")

    comparison, candidate = build_codex_repair_comparison(
        case_id=case.case_id,
        codex_evidence_root=codex_evidence,
        codex_commit="e56398f",
        output_root=learning,
        repo_root=tmp_path,
    )

    assert comparison.same_task_identity is True
    assert comparison.eligible_for_dpo is True
    assert candidate["eligible_for_dpo"] is True
    assert candidate["approved_for_training"] is False
    assert candidate["requires_human_approval"] is True
    dpo_path = learning / "cases/markitdown-case/dpo_candidate.json"
    assert json.loads(dpo_path.read_text(encoding="utf-8"))["approved_for_training"] is False
