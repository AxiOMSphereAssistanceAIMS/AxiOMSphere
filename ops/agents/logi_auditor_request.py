"""
logi_auditor_request.py

Pending auditor request artifact writer for Logi.

Extends the existing Codex/Bedrock auditor chain (ops/agents/codex_auditor_adapter.py)
by writing structured pending requests before routing to the chain.

Pending requests:
  aims_workspace/logi_auditor_requests/pending/
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PENDING_DIR = _ROOT / "aims_workspace" / "logi_auditor_requests" / "pending"
_COMPLETED_DIR = _ROOT / "aims_workspace" / "logi_auditor_requests" / "completed"


@dataclass
class AuditorRequestRecord:
    request_id: str
    created_at: str
    requested_by: str
    problem_summary: str
    attempted_solution: str
    evidence: list[str]
    failure_class: str
    existing_analogs_checked: list[str]
    suspected_missing_capability: str
    target_files: list[str]
    safety_constraints: list[str]
    tests_to_add: list[str]
    acceptance_criteria: list[str]
    original_message: str
    status: str = "pending"
    notes: list[str] = field(default_factory=list)


def _request_id(summary: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = hashlib.sha256(f"{summary}:{ts}".encode()).hexdigest()[:8]
    return f"auditor_req_{ts}_{h}"


def write_auditor_request(
    problem_summary: str,
    original_message: str,
    requested_by: str = "0",
    attempted_solution: str = "",
    evidence: list[str] | None = None,
    failure_class: str = "CAPABILITY_GAP",
    existing_analogs_checked: list[str] | None = None,
    suspected_missing_capability: str = "",
    target_files: list[str] | None = None,
    safety_constraints: list[str] | None = None,
    tests_to_add: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> AuditorRequestRecord:
    """Write a pending auditor request. Caller must have obtained confirmation first."""
    now = datetime.now(timezone.utc).isoformat()
    record = AuditorRequestRecord(
        request_id=_request_id(problem_summary),
        created_at=now,
        requested_by=requested_by,
        problem_summary=problem_summary,
        attempted_solution=attempted_solution,
        evidence=evidence or [],
        failure_class=failure_class,
        existing_analogs_checked=existing_analogs_checked or [],
        suspected_missing_capability=suspected_missing_capability,
        target_files=target_files or [],
        safety_constraints=safety_constraints or ["No shell=True", "No arbitrary paths"],
        tests_to_add=tests_to_add or [],
        acceptance_criteria=acceptance_criteria or [],
        original_message=original_message,
    )
    _PENDING_DIR.mkdir(parents=True, exist_ok=True)
    path = _PENDING_DIR / f"{record.request_id}.json"
    path.write_text(json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def load_auditor_request(request_id: str) -> dict | None:
    path = _PENDING_DIR / f"{request_id}.json"
    if not path.exists():
        path = _COMPLETED_DIR / f"{request_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
