"""
AIMS Self-Learning — Runtime Activation Proposal Schema.

A RuntimeActivationProposal describes what would be required before a
CERTIFIED_SKILL entry could ever be promoted to ACTIVE_RUNTIME_SKILL.

This is a proposal artifact only. No activation occurs at this phase.
runtime_activation_allowed, self_approval_allowed, and active_runtime_requested
are always False. No runtime registry is modified.

No model calls, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── lifecycle states used in proposals ────────────────────────────────────
PROPOSAL_CURRENT_STATE = "CERTIFIED_SKILL"
PROPOSAL_TARGET_STATE = "ACTIVE_RUNTIME_SKILL"   # proposal target only — not activated

# ── proposal status ────────────────────────────────────────────────────────
PROPOSAL_STATUS_BLOCKED = "PROPOSED_BLOCKED"
PROPOSAL_STATUS_MANUAL = "PROPOSED_REQUIRES_MANUAL_APPROVAL"
PROPOSAL_STATUS_REJECTED = "PROPOSAL_REJECTED"

PROPOSAL_STATUSES: tuple[str, ...] = (
    PROPOSAL_STATUS_BLOCKED,
    PROPOSAL_STATUS_MANUAL,
    PROPOSAL_STATUS_REJECTED,
)

# ── activation request status ──────────────────────────────────────────────
ACTIVATION_BLOCKED = "BLOCKED"
ACTIVATION_REQUIRES_MANUAL = "REQUIRES_MANUAL_APPROVAL"
ACTIVATION_NOT_REQUESTED = "NOT_REQUESTED"

ACTIVATION_REQUEST_STATUSES: tuple[str, ...] = (
    ACTIVATION_BLOCKED,
    ACTIVATION_REQUIRES_MANUAL,
    ACTIVATION_NOT_REQUESTED,
)

# ── required approvals ─────────────────────────────────────────────────────
REQUIRED_APPROVALS_BASE: tuple[str, ...] = (
    "human_owner_approval",
    "Argus_safety_approval",
    "Logi_task_ledger_approval",
    "QA_validation_approval",
    "registry_update_approval",
    "rollback_plan_approval",
)

APPROVAL_TRAINI = "Traini_approval"

# ── required runtime gates ─────────────────────────────────────────────────
REQUIRED_RUNTIME_GATES: tuple[str, ...] = (
    "explicit_AIMS_activation_decision",
    "final_safety_smoke",
    "registry_diff_review",
    "rollback_rehearsal",
    "monitoring_plan_review",
    "deactivation_plan_review",
)

# ── safety invariants ──────────────────────────────────────────────────────
REQUIRED_SAFETY_INVARIANTS: tuple[str, ...] = (
    "no_self_approval",
    "no_runtime_activation",
    "no_active_runtime_promotion",
    "no_secret_access",
    "no_model_endpoint_calls",
    "no_shell_command_execution",
    "no_deletion_or_quarantine",
    "no_production_restart",
    "no_model_training_or_promotion",
    "dgx_slot32_slot120_policy_preserved",
)

# ── forbidden governors / direct-control actions ───────────────────────────
FORBIDDEN_GOVERNORS: frozenset[str] = frozenset({"hermes_external_worker", "hermes"})
FORBIDDEN_DIRECT_CONTROLS: frozenset[str] = frozenset({
    "direct_deletion_control",
    "direct_quarantine_control",
    "direct_production_restart",
    "direct_training_launch",
    "direct_model_promotion",
})

PROPOSAL_VERSION = "1.0"


@dataclass
class RuntimeActivationProposal:
    """
    Proposal artifact describing what is required before a certified skill
    could be activated at runtime. This phase does NOT activate anything.

    Immutable safety properties:
      runtime_activation_allowed = False
      self_approval_allowed = False
      active_runtime_requested = False
      current_lifecycle_state = CERTIFIED_SKILL
    """

    proposal_id: str
    staged_skill_id: str
    certified_skill_id: str
    owner_agent_id: str
    skill_domain: str
    proposed_name: str
    current_lifecycle_state: str            # must == PROPOSAL_CURRENT_STATE
    proposed_lifecycle_state: str           # ACTIVE_RUNTIME_SKILL as target only
    proposal_status: str                    # one of PROPOSAL_STATUSES
    activation_request_status: str          # one of ACTIVATION_REQUEST_STATUSES
    required_approvals: list[str]
    required_runtime_gates: list[str]
    safety_invariants: dict[str, bool]
    rollback_plan: str
    deactivation_plan: str
    monitoring_plan: str
    rate_limit_plan: str
    blast_radius: str
    activation_blockers: list[str]
    validation_commands_required: list[str]
    post_activation_checks_required: list[str]
    runtime_activation_allowed: bool        # always False
    self_approval_allowed: bool             # always False
    active_runtime_requested: bool          # always False
    production_related: bool
    model_related: bool
    proposed_at: str
    proposed_by: str
    proposal_version: str = PROPOSAL_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.current_lifecycle_state != PROPOSAL_CURRENT_STATE:
            raise ValueError(
                f"current_lifecycle_state must be {PROPOSAL_CURRENT_STATE!r}, "
                f"got {self.current_lifecycle_state!r}"
            )
        if self.proposal_status not in PROPOSAL_STATUSES:
            raise ValueError(
                f"proposal_status must be one of {PROPOSAL_STATUSES}, "
                f"got {self.proposal_status!r}"
            )
        if self.activation_request_status not in ACTIVATION_REQUEST_STATUSES:
            raise ValueError(
                f"activation_request_status must be one of {ACTIVATION_REQUEST_STATUSES}, "
                f"got {self.activation_request_status!r}"
            )
        if self.runtime_activation_allowed:
            raise ValueError("runtime_activation_allowed must be False")
        if self.self_approval_allowed:
            raise ValueError("self_approval_allowed must be False")
        if self.active_runtime_requested:
            raise ValueError("active_runtime_requested must be False")
        if not self.rollback_plan:
            raise ValueError("rollback_plan must be non-empty")
        if not self.deactivation_plan:
            raise ValueError("deactivation_plan must be non-empty")
        if not self.monitoring_plan:
            raise ValueError("monitoring_plan must be non-empty")
        if not self.rate_limit_plan:
            raise ValueError("rate_limit_plan must be non-empty")
        if not self.blast_radius:
            raise ValueError("blast_radius must be non-empty")
        if not self.validation_commands_required:
            raise ValueError("validation_commands_required must be non-empty")
        if not self.post_activation_checks_required:
            raise ValueError("post_activation_checks_required must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "staged_skill_id": self.staged_skill_id,
            "certified_skill_id": self.certified_skill_id,
            "owner_agent_id": self.owner_agent_id,
            "skill_domain": self.skill_domain,
            "proposed_name": self.proposed_name,
            "current_lifecycle_state": self.current_lifecycle_state,
            "proposed_lifecycle_state": self.proposed_lifecycle_state,
            "proposal_status": self.proposal_status,
            "activation_request_status": self.activation_request_status,
            "required_approvals": self.required_approvals,
            "required_runtime_gates": self.required_runtime_gates,
            "safety_invariants": self.safety_invariants,
            "rollback_plan": self.rollback_plan,
            "deactivation_plan": self.deactivation_plan,
            "monitoring_plan": self.monitoring_plan,
            "rate_limit_plan": self.rate_limit_plan,
            "blast_radius": self.blast_radius,
            "activation_blockers": self.activation_blockers,
            "validation_commands_required": self.validation_commands_required,
            "post_activation_checks_required": self.post_activation_checks_required,
            "runtime_activation_allowed": self.runtime_activation_allowed,
            "self_approval_allowed": self.self_approval_allowed,
            "active_runtime_requested": self.active_runtime_requested,
            "production_related": self.production_related,
            "model_related": self.model_related,
            "proposed_at": self.proposed_at,
            "proposed_by": self.proposed_by,
            "proposal_version": self.proposal_version,
            "metadata": self.metadata,
        }
