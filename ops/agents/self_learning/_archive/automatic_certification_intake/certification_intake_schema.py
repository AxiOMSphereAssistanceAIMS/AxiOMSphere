from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class CertificationCandidatePackage:
    certification_candidate_id: str
    source_execution_id: str
    sandbox_plan_id: str
    source_candidate_skill_id: str
    source_skill_pack_id: str
    owner_agent_id: str
    skill_name: str
    skill_domain: str
    lifecycle_state_before: str
    proposed_lifecycle_state: str = "CERTIFIED_SKILL"
    certification_scope: str = "REVIEW_PACKAGE_ONLY"
    sandbox_result_status: str = "SANDBOX_PASS"
    sandbox_pass_count: int = 0
    sandbox_warn_count: int = 0
    sandbox_fail_count: int = 0
    evidence_refs: list[str] = field(default_factory=list)
    safety_checks: dict[str, Any] = field(default_factory=dict)
    gate_checklist_id: str = ""
    rollback_notes: str = ""
    deprecation_notes: str = ""
    runtime_activation_allowed: bool = False
    self_approval_allowed: bool = False
    certified_runtime_allowed: bool = False
    active_runtime_requested: bool = False
    status: str = "READY_FOR_CERTIFICATION_GATE_REVIEW"
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
