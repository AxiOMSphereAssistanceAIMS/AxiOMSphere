from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class AutomaticSkillPack:
    skill_pack_id: str
    source_request_id: str
    source_downstream_plan_id: str
    owner_agent_id: str
    skill_name: str
    skill_domain: str
    lifecycle_state: str = "CANDIDATE_SKILL"
    trigger_conditions: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    expected_inputs: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    refusal_conditions: list[str] = field(default_factory=list)
    safety_gates: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    sandbox_test_stub: dict[str, Any] = field(default_factory=dict)
    rollback_notes: str = ""
    deprecation_notes: str = ""
    version: str = "v1"
    generated_by: str = "automatic_skill_creator"
    generated_at: str = ""
    self_approval_allowed: bool = False
    runtime_activation_allowed: bool = False
    training_launch_allowed: bool = False
    model_load_unload_allowed: bool = False
    service_restart_allowed: bool = False
    secrets_access_allowed: bool = False
    deletion_quarantine_allowed: bool = False
    registry_direct_write_allowed: bool = False
    status: str = "GENERATED_PENDING_SANDBOX_PLAN"
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
