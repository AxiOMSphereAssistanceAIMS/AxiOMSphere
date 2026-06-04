from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class ActiveSkillRegistryEntry:
    active_skill_id: str
    source_request_id: str
    source_skill_pack_id: str
    source_candidate_skill_id: str
    owner_agent_id: str
    skill_name: str
    skill_domain: str
    lifecycle_state: str
    activation_status: str
    approved_scope_id: str
    approved_risk_class: str
    approved_permission_level: str
    allowed_actions: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    required_gates: list[str] = field(default_factory=list)
    activation_conditions: list[str] = field(default_factory=list)
    rollback_manifest_id: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    version: str = "v1"
    activated_at: str = ""
    activated_by: str = "automatic_skill_activation_pipeline"
    runtime_use_mode: str = "CONTROLLED_SCOPE_ONLY"
    monitoring_required: bool = True
    deactivation_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
