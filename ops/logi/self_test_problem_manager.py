"""Problem detection/classification/corrective/lessons for self-test manager."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_problem(source_status: str, context: dict[str, Any]) -> tuple[str, str]:
    src = (source_status or "").upper()
    if context.get("slot32_slot120_conflict"):
        return "CRITICAL", "slot32/slot120 conflict"
    if context.get("secrets_exposed"):
        return "CRITICAL", "secret exposure detected"
    if context.get("active_lifecycle_blocker"):
        return "BLOCKER", "active lifecycle blocker"
    if context.get("historical_redis_only"):
        return "INFO", "historical redis warning only"
    if src == "FAIL" and context.get("required_test", True):
        return "BLOCKER", "required test fail"
    if src in {"GAP", "WARN"} and not context.get("required_test", True):
        return "WARN", "optional test gap/warn"
    if src == "PARTIAL":
        return "PARTIAL", "partial result"
    if src in {"WARN", "GAP"}:
        return "PARTIAL", "warning/gap in required path"
    return "INFO", "noncritical issue"


@dataclass
class ProblemRecord:
    problem_id: str
    source_test_id: str
    source_action_id: str
    detected_at: str
    severity: str
    status: str
    owner_agent: str
    corrective_owner: str
    description: str
    evidence: dict[str, Any]
    suspected_root_cause: str
    corrective_actions: list[dict[str, Any]] = field(default_factory=list)
    validation_plan: str = ""
    retry_count: int = 0
    max_retries: int = 5
    closure_result: str = ""
    lessons_learned_ref: str = ""


def create_problem_record(
    source_test_id: str,
    source_action_id: str,
    owner_agent: str,
    corrective_owner: str,
    source_status: str,
    description: str,
    evidence: dict[str, Any],
    context: dict[str, Any],
) -> ProblemRecord:
    severity, root = classify_problem(source_status, context)
    return ProblemRecord(
        problem_id=f"prb_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')[:20]}",
        source_test_id=source_test_id,
        source_action_id=source_action_id,
        detected_at=_now(),
        severity=severity,
        status="OPEN",
        owner_agent=owner_agent,
        corrective_owner=corrective_owner,
        description=description,
        evidence=evidence,
        suspected_root_cause=root,
        validation_plan="Re-run targeted validation command and compare status/evidence.",
    )


def create_corrective_action(problem: ProblemRecord, validation_command: str, safe: bool = True) -> dict[str, Any]:
    action = {
        "corrective_action_id": f"ca_{problem.problem_id}",
        "problem_id": problem.problem_id,
        "responsible_agent": problem.corrective_owner,
        "execution_handler": "logi_process_integrity_orchestrator",
        "safety_policy": "No destructive actions; restricted fixes require Poli approval.",
        "validation_command": validation_command,
        "retry_policy": {"max_retries": problem.max_retries, "safe_mode_default": True},
        "evidence_path": "",
        "escalation_rule": "Escalate to Poli+Repairman if unsafe or retries exhausted.",
        "mode": "safe_execute" if safe else "requires_approval",
    }
    problem.corrective_actions.append(action)
    problem.status = "ASSIGNED"
    return action


def record_validation(problem: ProblemRecord, status: str, detail: str) -> dict[str, Any]:
    problem.retry_count += 1
    if status == "PASS":
        problem.status = "CLOSED"
        problem.closure_result = "PASS"
    elif problem.retry_count >= problem.max_retries:
        problem.status = "DEFERRED"
        problem.closure_result = "PARTIAL"
    else:
        problem.status = "VALIDATING"
        problem.closure_result = status
    return {
        "problem_id": problem.problem_id,
        "retry_count": problem.retry_count,
        "status": status,
        "detail": detail[:400],
        "problem_status": problem.status,
        "closure_result": problem.closure_result,
        "timestamp": _now(),
    }


def append_lesson(problem: ProblemRecord, test_id: str, action_id: str, output_path: Path) -> dict[str, Any]:
    lesson = {
        "timestamp": _now(),
        "problem_id": problem.problem_id,
        "test_id": test_id,
        "action_id": action_id,
        "root_cause": problem.suspected_root_cause,
        "fix_or_decision": problem.closure_result or problem.status,
        "validation_result": problem.closure_result or "UNKNOWN",
        "future_prevention": "Keep scheduled self-test + corrective validation loop active.",
        "owner_agent": problem.owner_agent,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(lesson, ensure_ascii=False) + "\n")
    problem.lessons_learned_ref = str(output_path)
    return lesson


def to_dict(problem: ProblemRecord) -> dict[str, Any]:
    return asdict(problem)

