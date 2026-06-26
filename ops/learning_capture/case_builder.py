from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from ops.learning_capture.git_capture import capture_git_snapshot
from ops.learning_capture.models import AgentActionCase, dataclass_to_dict
from ops.learning_capture.session_capture import copy_optional_file, read_text_file, utc_now


def make_case_id(agent_name: str, target_slot: str) -> str:
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]+", "_", agent_name).strip("_") or "agent"
    safe_slot = re.sub(r"[^A-Za-z0-9_.-]+", "_", target_slot).strip("_") or "slot"
    stamp = utc_now().replace("-", "").replace(":", "").replace(".", "_").replace("Z", "Z")
    return f"{safe_agent}_{safe_slot}_{stamp}_{uuid.uuid4().hex[:8]}"


def parse_pytest_summary(text: str) -> tuple[list[str], int, int]:
    tests_run: list[str] = []
    passed = 0
    failed = 0
    for line in (text or "").splitlines():
        if "pytest" in line or " passed" in line or " failed" in line:
            tests_run.append(line.strip())
        pass_match = re.search(r"(\d+)\s+passed", line)
        fail_match = re.search(r"(\d+)\s+failed", line)
        if pass_match:
            passed = max(passed, int(pass_match.group(1)))
        if fail_match:
            failed = max(failed, int(fail_match.group(1)))
    return tests_run[-20:], passed, failed


def collect_test_summary(*, terminal_log: str, evidence_root: str | Path | None) -> tuple[list[str], int, int]:
    texts = [terminal_log]
    if evidence_root and Path(evidence_root).exists():
        for path in sorted(Path(evidence_root).glob("*.log"))[:20]:
            texts.append(read_text_file(path))
    tests: list[str] = []
    passed = 0
    failed = 0
    for text in texts:
        current_tests, current_passed, current_failed = parse_pytest_summary(text)
        tests.extend(current_tests)
        passed = max(passed, current_passed)
        failed = max(failed, current_failed)
    return tests[-30:], passed, failed


def inspect_expected_deliverables(paths: list[str], *, repo_root: str | Path = ".") -> tuple[list[str], list[str]]:
    actual: list[str] = []
    missing: list[str] = []
    root = Path(repo_root)
    for item in paths:
        if (root / item).exists() or Path(item).exists():
            actual.append(item)
        else:
            missing.append(item)
    return actual, missing


def detect_failure_modes(
    *,
    expected_deliverables: list[str],
    actual_deliverables: list[str],
    evidence_root: str | Path | None,
    task_prompt: str,
    terminal_log: str,
    files_changed: list[str],
    tests_run: list[str],
    tests_failed: int,
    terminal_log_path: str | None,
    git_diff_path: str | None,
) -> list[str]:
    modes: set[str] = set()
    missing = sorted(set(expected_deliverables) - set(actual_deliverables))
    evidence_exists = bool(evidence_root and Path(evidence_root).exists())
    evidence_files = list(Path(evidence_root).glob("*")) if evidence_exists else []
    assessment_text = f"{task_prompt}\n{terminal_log}".lower()

    if missing and evidence_files:
        modes.add("evidence_only_completion_without_feature_implementation")
    if (
        "task_not_implemented_as_requested" in assessment_text
        or "smoke evidence is not implementation evidence" in assessment_text
        or "evidence-only" in assessment_text
        or "missing files:" in assessment_text
    ):
        modes.add("evidence_only_completion_without_feature_implementation")
    if missing:
        modes.add("missing_artifact_paths")
    if not terminal_log_path or not git_diff_path or not evidence_exists:
        modes.add("missing_artifact_paths")
    if "mock" in assessment_text and "production" in assessment_text:
        modes.add("mocked_path_claimed_as_production")
    if "quality" in assessment_text and "gate" not in assessment_text:
        modes.add("quality_score_without_gate_validation")
    if "raw output" in assessment_text and "certified" in assessment_text and "master package" not in assessment_text:
        modes.add("raw_output_certified_without_master_package")
    if evidence_exists and not any("learning" in p.name.lower() for p in evidence_files):
        modes.add("missing_learning_entry")
    if "wrong extractor" in assessment_text:
        modes.add("wrong_extractor_applied")
    if "unsupported" in assessment_text and "failed" in assessment_text:
        modes.add("unsupported_counted_as_failed")
    if "archive member" in assessment_text and "not processed" in assessment_text:
        modes.add("archive_member_not_processed")
    if actual_deliverables and files_changed and not any("commit" in line.lower() for line in tests_run):
        modes.add("no_commit_after_implementation")
    if tests_failed > 0 and actual_deliverables:
        modes.add("no_regression_after_patch")
    if actual_deliverables and "production" in assessment_text and "limited production" not in assessment_text:
        modes.add("no_limited_production_run")
    if tests_run and actual_deliverables and not files_changed:
        modes.add("tests_only_no_production_wiring")
    return sorted(modes)


def write_case_markdown(case: AgentActionCase, path: str | Path) -> str:
    target = Path(path)
    lines = [
        f"# Agent Action Case {case.case_id}",
        "",
        f"- Timestamp UTC: {case.timestamp_utc}",
        f"- Project: {case.project}",
        f"- Agent: {case.agent_name}",
        f"- Target slot: {case.target_slot}",
        f"- Outcome: {case.outcome}",
        f"- Approved for training: {case.approved_for_training}",
        "",
        "## Expected Deliverables",
        *[f"- {item}" for item in case.expected_deliverables],
        "",
        "## Actual Deliverables",
        *[f"- {item}" for item in case.actual_deliverables],
        "",
        "## Failure Modes",
        *[f"- {item}" for item in case.failure_modes],
        "",
        "## Evidence",
        f"- Terminal log: {case.terminal_log_path or 'none'}",
        f"- Git diff: {case.git_diff_path or 'none'}",
        f"- Evidence path: {case.evidence_path}",
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(target)


def append_jsonl(path: str | Path, data: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")
    return str(target)


def build_agent_action_case(
    *,
    agent_name: str,
    target_slot: str,
    task_prompt_file: str | Path,
    evidence_root: str | Path,
    expected_deliverables: list[str],
    output_root: str | Path,
    terminal_log: str | Path | None = None,
    repo_root: str | Path = ".",
    case_id: str | None = None,
) -> AgentActionCase:
    output = Path(output_root)
    cid = case_id or make_case_id(agent_name, target_slot)
    case_dir = output / "cases" / cid
    case_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = read_text_file(task_prompt_file)
    prompt_copy = copy_optional_file(task_prompt_file, case_dir / "task_prompt.md")
    terminal_copy = copy_optional_file(terminal_log, case_dir / "terminal.log")
    terminal_text = read_text_file(terminal_log)
    git_snapshot = capture_git_snapshot(output_dir=case_dir, repo_root=repo_root)
    actual, _missing = inspect_expected_deliverables(expected_deliverables, repo_root=repo_root)
    tests_run, tests_passed, tests_failed = collect_test_summary(
        terminal_log=terminal_text,
        evidence_root=evidence_root,
    )
    files_changed = list(git_snapshot.get("files_changed") or [])
    git_diff_path = str(git_snapshot["diff_path"]) if git_snapshot.get("diff_path") else None
    modes = detect_failure_modes(
        expected_deliverables=expected_deliverables,
        actual_deliverables=actual,
        evidence_root=evidence_root,
        task_prompt=prompt_text,
        terminal_log=terminal_text,
        files_changed=files_changed,
        tests_run=tests_run,
        tests_failed=tests_failed,
        terminal_log_path=terminal_copy,
        git_diff_path=git_diff_path,
    )
    outcome = "PASS" if not modes and tests_failed == 0 else "NEEDS_REVIEW"

    case = AgentActionCase(
        case_id=cid,
        timestamp_utc=utc_now(),
        project=str(Path(repo_root).resolve()),
        agent_name=agent_name,
        target_slot=target_slot,
        task_prompt=prompt_text,
        expected_deliverables=list(expected_deliverables),
        actual_deliverables=actual,
        files_changed=files_changed,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        terminal_log_path=terminal_copy,
        git_diff_path=git_diff_path,
        evidence_path=str(evidence_root),
        outcome=outcome,
        failure_modes=modes,
        approved_for_training=False,
    )

    case_json = case_dir / "case.json"
    case_json.write_text(json.dumps(dataclass_to_dict(case), indent=2, ensure_ascii=False), encoding="utf-8")
    write_case_markdown(case, case_dir / "case.md")
    append_jsonl(output / "agent_action_cases.jsonl", dataclass_to_dict(case))
    if prompt_copy is None:
        # Keep a clear placeholder when the caller supplied a missing prompt path.
        (case_dir / "task_prompt_missing.txt").write_text(str(task_prompt_file), encoding="utf-8")
    return case
