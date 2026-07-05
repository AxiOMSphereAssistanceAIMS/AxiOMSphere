"""
logi_skill_request.py

Skill request governance for Logi.

Every proposed new skill must go through this module.
auditor_review_required is always True.

Skill requests:
  aims_workspace/logi_skill_requests/pending/
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PENDING_DIR = _ROOT / "aims_workspace" / "logi_skill_requests" / "pending"
_COMPLETED_DIR = _ROOT / "aims_workspace" / "logi_skill_requests" / "completed"


@dataclass
class SkillRequestRecord:
    request_id: str
    created_at: str
    requested_by: str
    skill_name: str
    trigger_phrases_ru: list[str]
    trigger_phrases_en: list[str]
    purpose: str
    existing_analogs_checked: list[str]
    why_existing_insufficient: str
    allowed_actions: list[str]
    forbidden_actions: list[str]
    tests: list[str]
    safety_constraints: list[str]
    rollback: str
    original_message: str
    auditor_review_required: bool = True
    status: str = "pending"


def _request_id(skill_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = hashlib.sha256(f"{skill_name}:{ts}".encode()).hexdigest()[:8]
    return f"skill_req_{ts}_{h}"


def write_skill_request(
    skill_name: str,
    purpose: str,
    original_message: str,
    requested_by: str = "0",
    trigger_phrases_ru: list[str] | None = None,
    trigger_phrases_en: list[str] | None = None,
    existing_analogs_checked: list[str] | None = None,
    why_existing_insufficient: str = "",
    allowed_actions: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    tests: list[str] | None = None,
    safety_constraints: list[str] | None = None,
    rollback: str = "Remove skill from registry.",
) -> SkillRequestRecord:
    """Write a pending skill request. auditor_review_required is always True."""
    now = datetime.now(timezone.utc).isoformat()
    record = SkillRequestRecord(
        request_id=_request_id(skill_name),
        created_at=now,
        requested_by=requested_by,
        skill_name=skill_name,
        trigger_phrases_ru=trigger_phrases_ru or [],
        trigger_phrases_en=trigger_phrases_en or [],
        purpose=purpose,
        existing_analogs_checked=existing_analogs_checked or [],
        why_existing_insufficient=why_existing_insufficient,
        allowed_actions=allowed_actions or ["read_only_analysis"],
        forbidden_actions=forbidden_actions or [
            "shell=True", "arbitrary_paths", "docker_exec", "rm", "sudo"
        ],
        tests=tests or [],
        safety_constraints=safety_constraints or ["No shell=True", "auditor review required"],
        rollback=rollback,
        original_message=original_message,
        auditor_review_required=True,
    )
    _PENDING_DIR.mkdir(parents=True, exist_ok=True)
    path = _PENDING_DIR / f"{record.request_id}.json"
    path.write_text(json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def load_skill_request(request_id: str) -> dict | None:
    for d in (_PENDING_DIR, _COMPLETED_DIR):
        path = d / f"{request_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None
