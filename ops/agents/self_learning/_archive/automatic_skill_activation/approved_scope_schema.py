from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class ApprovedSkillScope:
    scope_id: str
    source_request_id: str
    approved_by: str
    approved_at: str
    owner_agent_id: str
    skill_name: str
    skill_domain: str
    approved_risk_class: str
    approved_permission_level: str
    approved_actions: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    allowed_inputs: list[str] = field(default_factory=list)
    allowed_outputs: list[str] = field(default_factory=list)
    allowed_runtime_contexts: list[str] = field(default_factory=list)
    required_tests: list[str] = field(default_factory=list)
    required_gates: list[str] = field(default_factory=list)
    activation_conditions: list[str] = field(default_factory=list)
    rollback_conditions: list[str] = field(default_factory=list)
    deactivation_conditions: list[str] = field(default_factory=list)
    scope_expansion_requires_new_approval: bool = True
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
