from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SandboxExecutionAfterIntakeResult:
    execution_id: str
    sandbox_plan_id: str
    source_candidate_skill_id: str
    source_skill_pack_id: str
    owner_agent_id: str
    skill_name: str
    skill_domain: str
    lifecycle_state_before: str
    lifecycle_state_after: str
    execution_mode: str = "DETERMINISTIC_SYNTHETIC_ONLY"
    fixtures_used: list[str] = field(default_factory=list)
    actions_simulated: list[str] = field(default_factory=list)
    expected_outputs_checked: list[str] = field(default_factory=list)
    forbidden_actions_tested: list[str] = field(default_factory=list)
    safety_checks: dict[str, Any] = field(default_factory=dict)
    result_status: str = "SANDBOX_PASS"
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    rejected_actions: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    self_approval_allowed: bool = False
    runtime_activation_allowed: bool = False
    model_endpoint_calls: int = 0
    training_launch_count: int = 0
    model_load_unload_count: int = 0
    service_restart_count: int = 0
    secrets_access_count: int = 0
    raw_claude_mem_access_count: int = 0
    active_registry_modification_count: int = 0
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
