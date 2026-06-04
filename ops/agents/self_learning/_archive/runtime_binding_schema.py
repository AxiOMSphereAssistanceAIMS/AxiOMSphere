"""
AIMS Self-Learning — Runtime Binding Simulation Schema.

No model calls, no I/O, no activation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Requested binding states
BINDING_STATE_DRY_RUN_ONLY = "DRY_RUN_BINDING_ONLY"

REQUESTED_BINDING_STATES: tuple[str, ...] = (
    BINDING_STATE_DRY_RUN_ONLY,
)

# Simulated binding states
SIMULATED_BLOCKED = "BLOCKED_NOT_APPROVED"
SIMULATED_READY = "READY_FOR_DRY_RUN_BINDING"
SIMULATED_REJECTED = "REJECTED_UNSAFE"

SIMULATED_BINDING_STATES: tuple[str, ...] = (
    SIMULATED_BLOCKED,
    SIMULATED_READY,
    SIMULATED_REJECTED,
)

BINDING_SCHEMA_VERSION = "1.0"


@dataclass
class RuntimeBindingSimulationEntry:
    """
    Dry-run binding simulation result for one approval entry.

    Safety invariants enforced at construction:
    - runtime_activation_allowed always False
    - self_approval_allowed always False
    - active_runtime_registry_changed always False
    - agent_behavior_changed always False
    """

    binding_id: str
    proposal_id: str
    certified_skill_id: str
    owner_agent_id: str
    skill_domain: str
    source_approval_status: str
    requested_binding_state: str
    simulated_binding_state: str
    binding_allowed: bool
    binding_blocked: bool

    blocking_reasons: list[str] = field(default_factory=list)
    required_missing_gates: list[str] = field(default_factory=list)

    # Safety invariants — always False
    runtime_activation_allowed: bool = False
    self_approval_allowed: bool = False
    active_runtime_registry_would_change: bool = False
    active_runtime_registry_changed: bool = False
    agent_behavior_would_change: bool = False
    agent_behavior_changed: bool = False

    rollback_plan_available: bool = False
    deactivation_plan_available: bool = False
    dgx_policy_verified: bool = False
    secrets_policy_verified: bool = False
    production_policy_verified: bool = False
    model_policy_verified: bool = False
    traini_gate_required: bool = False
    traini_gate_passed: bool = False
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.requested_binding_state not in REQUESTED_BINDING_STATES:
            raise ValueError(
                f"requested_binding_state must be one of {REQUESTED_BINDING_STATES}, "
                f"got {self.requested_binding_state!r}"
            )
        if self.simulated_binding_state not in SIMULATED_BINDING_STATES:
            raise ValueError(
                f"simulated_binding_state must be one of {SIMULATED_BINDING_STATES}, "
                f"got {self.simulated_binding_state!r}"
            )
        if self.runtime_activation_allowed:
            raise ValueError("runtime_activation_allowed must be False")
        if self.self_approval_allowed:
            raise ValueError("self_approval_allowed must be False")
        if self.active_runtime_registry_changed:
            raise ValueError("active_runtime_registry_changed must be False")
        if self.agent_behavior_changed:
            raise ValueError("agent_behavior_changed must be False")

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "proposal_id": self.proposal_id,
            "certified_skill_id": self.certified_skill_id,
            "owner_agent_id": self.owner_agent_id,
            "skill_domain": self.skill_domain,
            "source_approval_status": self.source_approval_status,
            "requested_binding_state": self.requested_binding_state,
            "simulated_binding_state": self.simulated_binding_state,
            "binding_allowed": self.binding_allowed,
            "binding_blocked": self.binding_blocked,
            "blocking_reasons": self.blocking_reasons,
            "required_missing_gates": self.required_missing_gates,
            "runtime_activation_allowed": self.runtime_activation_allowed,
            "self_approval_allowed": self.self_approval_allowed,
            "active_runtime_registry_would_change": self.active_runtime_registry_would_change,
            "active_runtime_registry_changed": self.active_runtime_registry_changed,
            "agent_behavior_would_change": self.agent_behavior_would_change,
            "agent_behavior_changed": self.agent_behavior_changed,
            "rollback_plan_available": self.rollback_plan_available,
            "deactivation_plan_available": self.deactivation_plan_available,
            "dgx_policy_verified": self.dgx_policy_verified,
            "secrets_policy_verified": self.secrets_policy_verified,
            "production_policy_verified": self.production_policy_verified,
            "model_policy_verified": self.model_policy_verified,
            "traini_gate_required": self.traini_gate_required,
            "traini_gate_passed": self.traini_gate_passed,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
