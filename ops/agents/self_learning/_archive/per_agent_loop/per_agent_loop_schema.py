from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class AgentSelfLearningProfile:
    agent_id: str
    agent_role: str
    self_learning_enabled: bool
    loop_mode: str
    loop_pace: str
    observation_sources: list[str]
    local_evidence_store: str
    local_skill_request_outbox: str
    assigned_active_skills: list[str]
    owned_skill_domains: list[str]
    allowed_skill_permission_levels: list[str]
    forbidden_actions: list[str]
    approval_required_for_new_skill: bool = True
    approval_required_for_scope_expansion: bool = True
    within_scope_improvement_allowed: bool = True
    central_approval_aggregator: str = "axi_skill_request_aggregator"
    central_skill_registry: str = "shared_skill_registry"
    safety_gates: list[str] = field(default_factory=lambda: ["argus", "logi", "qa"])
    kill_switch: bool = False
    last_loop_run: str = ""
    next_loop_due: str = ""
    status: str = "READY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
