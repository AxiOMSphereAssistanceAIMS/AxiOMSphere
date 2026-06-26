from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ops.learning_capture.case_builder import build_agent_action_case


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def test_case_created_from_prompt_log_and_diff(tmp_path: Path) -> None:
    _init_git(tmp_path)
    prompt = tmp_path / "task.md"
    prompt.write_text("Implement MarkItDown adapter", encoding="utf-8")
    log = tmp_path / "session.log"
    log.write_text("pytest -q\n1 passed in 0.01s\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    deliverable = tmp_path / "ops/docsreg/extraction/markitdown_adapter.py"
    deliverable.parent.mkdir(parents=True)
    deliverable.write_text("# adapter\n", encoding="utf-8")

    case = build_agent_action_case(
        agent_name="slot32-local",
        target_slot="slot32",
        task_prompt_file=prompt,
        terminal_log=log,
        evidence_root=evidence,
        expected_deliverables=["ops/docsreg/extraction/markitdown_adapter.py"],
        output_root=tmp_path / "learning",
        repo_root=tmp_path,
        case_id="case-basic",
    )

    assert case.case_id == "case-basic"
    assert case.tests_passed == 1
    assert Path(case.git_diff_path or "").exists()
    assert Path(tmp_path / "learning/cases/case-basic/case.json").exists()
    assert Path(tmp_path / "learning/agent_action_cases.jsonl").exists()


def test_missing_expected_deliverables_detected(tmp_path: Path) -> None:
    _init_git(tmp_path)
    prompt = tmp_path / "task.md"
    prompt.write_text("Need production file", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "report.md").write_text("COMPLETE", encoding="utf-8")

    case = build_agent_action_case(
        agent_name="slot32-local",
        target_slot="slot32",
        task_prompt_file=prompt,
        terminal_log=None,
        evidence_root=evidence,
        expected_deliverables=["ops/missing.py"],
        output_root=tmp_path / "learning",
        repo_root=tmp_path,
        case_id="case-missing",
    )

    assert "ops/missing.py" not in case.actual_deliverables
    assert "missing_artifact_paths" in case.failure_modes


def test_evidence_only_completion_failure_mode(tmp_path: Path) -> None:
    _init_git(tmp_path)
    prompt = tmp_path / "task.md"
    prompt.write_text("Need real implementation", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "evidence_only.md").write_text("Done in evidence only", encoding="utf-8")

    case = build_agent_action_case(
        agent_name="slot32-local",
        target_slot="slot32",
        task_prompt_file=prompt,
        terminal_log=None,
        evidence_root=evidence,
        expected_deliverables=["ops/production.py"],
        output_root=tmp_path / "learning",
        repo_root=tmp_path,
        case_id="case-evidence-only",
    )

    assert "evidence_only_completion_without_feature_implementation" in case.failure_modes
    data = json.loads((tmp_path / "learning/cases/case-evidence-only/case.json").read_text(encoding="utf-8"))
    assert data["approved_for_training"] is False
