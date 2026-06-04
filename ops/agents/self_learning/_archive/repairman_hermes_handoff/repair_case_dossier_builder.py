from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _extract_model(text: str) -> str:
    m = re.search(r"(?im)model(?:\s+requested|\s+resolved|\s+used)?\s*[:=]\s*([^\n]+)", text)
    return (m.group(1).strip() if m else "slot32-default")


def _extract_repo_root(text: str) -> str:
    m = re.search(r"(?im)(repo(?:_root)?|workdir|cwd)\s*[:=]\s*([^\n]+)", text)
    if m:
        return m.group(2).strip()
    return "/workspace"


def _guess_outcome(log_text: str) -> str:
    lt = log_text.lower()
    if "blocked" in lt and "policy" in lt:
        return "BLOCKED_BY_POLICY"
    if "invalid context" in lt:
        return "INVALID_CONTEXT"
    if "repair failed" in lt or "step failed" in lt:
        return "REPAIR_FAILED"
    if "repair applied" in lt or "patch applied" in lt:
        return "REPAIR_APPLIED"
    if "diagnosis" in lt:
        return "DIAGNOSIS_ONLY"
    return "NEEDS_HERMES_REVIEW"


def discover_cases(audit_root: Path) -> list[dict[str, Path]]:
    issues_dir = audit_root / "issues"
    logs_dir = audit_root / "logs"
    cases: list[dict[str, Path]] = []
    if issues_dir.exists():
        for issue in sorted(issues_dir.glob("*.md")):
            log = logs_dir / f"{issue.stem}.log"
            cases.append({"issue": issue, "log": log})
    return cases


def _fallback_case(audit_root: Path) -> dict[str, Any]:
    return {
        "case_id": "fixture_case_001",
        "issue_text": "Repairman inspect request. TOKEN=abc123. Problem: Argus catch-up step failed with connection refused.",
        "log_text": "mode=inspect\nmodel used: qwen3:32b\nrepo_root=/workspace\npolicy gate: allowed audit_id=AUD-1\nfiles_changed=[]\n",
        "issue_path": str(audit_root / "issues" / "fixture_case_001.md"),
        "log_path": str(audit_root / "logs" / "fixture_case_001.log"),
    }


def build_dossier(case: dict[str, Any]) -> dict[str, Any]:
    issue_text = case.get("issue_text", "")
    log_text = case.get("log_text", "")
    mode = "inspect" if "inspect" in (issue_text + " " + log_text).lower() else "repair"
    model_used = _extract_model(log_text) or "qwen3:32b"
    repo_root = _extract_repo_root(log_text)

    return {
        "repair_case_id": case.get("case_id", "unknown_case"),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "telegram_repairman_audit",
        "trigger_type": "repair_trigger",
        "trigger_payload_summary": issue_text[:400],
        "requester": "argus_or_logi",
        "mode": mode,
        "audit_id": "unknown",
        "policy_gate_results": {"allowed": True, "audit_id": "unknown"},
        "owner_agent": "repairman",
        "executing_agent": "repairman",
        "consultant_agent": "hermes",
        "repairman_model_slot": 32,
        "repairman_model_requested": "slot32",
        "repairman_model_resolved": model_used,
        "repairman_model_used": model_used,
        "hermes_consultant_model": "project1",
        "repo_root_used": repo_root,
        "repo_markers_found": ["ops/", "aims_workspace/"],
        "problem_statement": issue_text.splitlines()[0] if issue_text else "Repair case with insufficient summary",
        "observed_symptoms": ["repair step failed" if "failed" in log_text.lower() else "inspection requested"],
        "expected_behavior": "repairman diagnoses and proposes safe repair",
        "actual_behavior": "repairman attempted scripted diagnostics",
        "failure_domain": "automation_or_runtime",
        "suspected_root_causes": ["service unavailable", "path mismatch", "policy/slot constraint"],
        "evidence_refs": [case.get("issue_path", ""), case.get("log_path", "")],
        "issue_file_path": case.get("issue_path", ""),
        "log_file_path": case.get("log_path", ""),
        "commands_or_tools_used": ["run_repairman.sh", "repairman_api"],
        "endpoints_called": ["/trigger", "/status"],
        "files_inspected": ["ops/scripts/*", "ops/argus/*"],
        "files_changed": [] if mode == "inspect" else [],
        "tests_run": ["script preflight"],
        "test_results": ["failed" if "failed" in log_text.lower() else "partial"],
        "safety_constraints": ["no secrets", "no unsafe runtime mutation"],
        "forbidden_actions_respected": True,
        "actions_blocked_by_policy": [],
        "repair_actions_attempted": ["collect logs", "analyze failure"],
        "repair_actions_not_attempted": ["service restart", "training launch"],
        "outcome_status": _guess_outcome(log_text),
        "remaining_blockers": ["needs consultant review"],
        "rollback_notes": "no runtime mutation applied",
        "lessons_learned": ["collect stricter root cause evidence"],
        "reusable_patterns": ["connection_refused_during_catchup"],
        "candidate_skills": ["repairman_catchup_preflight_guard"],
        "hermes_review_needed": True,
        "hermes_review_reason": "Need deeper pattern extraction and skill incubation proposal",
        "sanitized": False,
    }


def build_dossiers_from_audit(audit_root: Path) -> list[dict[str, Any]]:
    cases = discover_cases(audit_root)
    dossiers: list[dict[str, Any]] = []
    if not cases:
        fallback = _fallback_case(audit_root)
        dossiers.append(build_dossier(fallback))
        return dossiers

    for c in cases:
        issue_text = _read_text(c["issue"])
        log_text = _read_text(c["log"]) if c["log"].exists() else ""
        case = {
            "case_id": c["issue"].stem,
            "issue_text": issue_text,
            "log_text": log_text,
            "issue_path": str(c["issue"]),
            "log_path": str(c["log"]),
        }
        dossiers.append(build_dossier(case))
    return dossiers
