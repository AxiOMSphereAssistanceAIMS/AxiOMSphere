from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

ALLOWED_APPROVAL_STATUSES = {
    "PENDING_APPROVAL",
    "APPROVED",
    "REJECTED",
    "BLOCKED_UNSAFE",
}

DEFAULT_DOWNSTREAM_STATUS = "WAITING_FOR_APPROVAL"


@dataclass
class SkillRequest:
    request_id: str
    created_at: str
    source_agent_id: str
    requested_skill_name: str
    requested_skill_domain: str
    missing_capability_description: str
    repeated_task_evidence_refs: list[str] = field(default_factory=list)
    observed_count: int = 0
    example_tasks: list[str] = field(default_factory=list)
    expected_skill_behavior: str = ""
    proposed_trigger_conditions: list[str] = field(default_factory=list)
    proposed_owner_agent_id: str = ""
    safety_risk_tags: list[str] = field(default_factory=list)
    model_related: bool = False
    production_related: bool = False
    secrets_related: bool = False
    deletion_or_quarantine_related: bool = False
    service_restart_related: bool = False
    training_related: bool = False
    model_loading_related: bool = False
    registry_modification_related: bool = False
    requested_creator: str = "skill_creator"
    approval_status: str = "PENDING_APPROVAL"
    approval_required: bool = True
    approved_by: str | None = None
    approved_at: str | None = None
    rejection_reason: str | None = None
    downstream_status: str = DEFAULT_DOWNSTREAM_STATUS
    downstream_plan_id: str | None = None
    audit_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
