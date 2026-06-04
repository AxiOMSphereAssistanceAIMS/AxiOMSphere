from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, UTC
from typing import Any
import uuid


ALLOWED_CLAIM_TYPES = {
    "CONTAINER_HEALTH",
    "TASK_STATUS",
    "REPAIRMAN_COMPLETION",
    "HERMES_REVIEW",
    "HERMES_REJECTION",
    "SKILL_ADOPTION",
    "MODEL_USED",
    "SLOT_POLICY",
    "LIVE_RUNTIME",
    "ARTIFACT_STATUS",
}

ALLOWED_CONFIDENCE = {
    "LIVE_VERIFIED",
    "ARTIFACT_VERIFIED",
    "CACHED_ARTIFACT",
    "STALE_CACHE",
    "UNVERIFIED",
    "CONFLICTING",
}

ALLOWED_RESULT = {
    "SUPPORTED",
    "NOT_SUPPORTED",
    "PARTIAL",
    "CONFLICTING",
    "NOT_CHECKED",
}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    return f"claim_{uuid.uuid4().hex}"


@dataclass
class HermesClaim:
    claim_id: str = field(default_factory=_new_id)
    claim_text: str = ""
    claim_type: str = "ARTIFACT_STATUS"
    subject: str = ""
    expected_truth_value: bool | str = True
    required_evidence: list[str] = field(default_factory=list)
    evidence_checked: list[str] = field(default_factory=list)
    evidence_found: bool = False
    evidence_paths: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    verification_method: str = "artifact_check"
    confidence: str = "UNVERIFIED"
    result: str = "NOT_CHECKED"
    generated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["claim_type"] not in ALLOWED_CLAIM_TYPES:
            data["claim_type"] = "ARTIFACT_STATUS"
        if data["confidence"] not in ALLOWED_CONFIDENCE:
            data["confidence"] = "UNVERIFIED"
        if data["result"] not in ALLOWED_RESULT:
            data["result"] = "NOT_CHECKED"
        return data

