from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class MaterializedSandboxTestPlan:
    sandbox_plan_id: str
    source_skill_pack_id: str
    source_candidate_skill_id: str
    source_stub_id: str
    owner_agent_id: str
    skill_name: str
    skill_domain: str
    lifecycle_transition: str = "CANDIDATE_SKILL -> SANDBOX_SKILL"
    sandbox_scope: str = "SYNTHETIC_FIXTURE_ONLY"
    synthetic_fixture_requirements: list[str] = field(default_factory=list)
    synthetic_fixtures_to_create: list[str] = field(default_factory=list)
    expected_behavior: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    safety_test_cases: list[str] = field(default_factory=list)
    forbidden_action_tests: list[str] = field(default_factory=list)
    required_gates: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    rollback_notes: str = ""
    filesystem_policy: dict[str, Any] = field(default_factory=dict)
    secrets_policy: dict[str, Any] = field(default_factory=dict)
    production_policy: dict[str, Any] = field(default_factory=dict)
    model_policy: dict[str, Any] = field(default_factory=dict)
    runtime_activation_allowed: bool = False
    self_approval_allowed: bool = False
    execution_allowed: bool = False
    status: str = "READY_FOR_SANDBOX_EXECUTION_PHASE"
    validation_errors: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
