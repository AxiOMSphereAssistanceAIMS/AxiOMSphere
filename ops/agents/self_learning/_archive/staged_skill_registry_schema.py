"""
AIMS Self-Learning — Staged Skill Registry Schema.

A StagedCertifiedSkillEntry is a read-only staging record for a
CERTIFIED_SKILL package awaiting human/AIMS activation review.

lifecycle_state is always CERTIFIED_SKILL at this phase.
No entry may target ACTIVE_RUNTIME_SKILL.
runtime_activation_allowed, self_approval_allowed, and active_runtime_requested
are always False.
activation_request_status is always NOT_REQUESTED at staging time.

No model calls, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── lifecycle ──────────────────────────────────────────────────────────────
STAGED_LIFECYCLE_STATE = "CERTIFIED_SKILL"
_FORBIDDEN_LIFECYCLE_STATE = "ACTIVE_RUNTIME_SKILL"

# ── staging status ─────────────────────────────────────────────────────────
STAGING_STATUS_REVIEW = "STAGED_FOR_REVIEW"
STAGING_STATUS_WARN = "STAGED_WITH_WARNINGS"
STAGING_STATUS_REJECTED = "REJECTED_FROM_STAGING"

STAGING_STATUSES: tuple[str, ...] = (
    STAGING_STATUS_REVIEW,
    STAGING_STATUS_WARN,
    STAGING_STATUS_REJECTED,
)

# ── activation request status ──────────────────────────────────────────────
ACTIVATION_NOT_REQUESTED = "NOT_REQUESTED"
ACTIVATION_BLOCKED = "BLOCKED"
ACTIVATION_REQUIRES_MANUAL = "REQUIRES_MANUAL_APPROVAL"

ACTIVATION_REQUEST_STATUSES: tuple[str, ...] = (
    ACTIVATION_NOT_REQUESTED,
    ACTIVATION_BLOCKED,
    ACTIVATION_REQUIRES_MANUAL,
)

# ── gates always required before any runtime activation ────────────────────
STAGING_GATES_ALWAYS_REQUIRED: tuple[str, ...] = (
    "explicit_AIMS_activation_decision",
    "argus_gate",
    "logi_gate",
    "qa_gate",
    "rollback_plan_review",
    "registry_update_review",
)

STAGING_GATE_TRAINI = "traini_gate"

# ── required safety invariant keys ────────────────────────────────────────
STAGING_REQUIRED_INVARIANTS: tuple[str, ...] = (
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

STAGING_VERSION = "1.0"


@dataclass
class StagedCertifiedSkillEntry:
    """
    Staging record for a certified skill pending activation review.

    Immutable safety properties:
      runtime_activation_allowed = False
      self_approval_allowed = False
      active_runtime_requested = False
      lifecycle_state = CERTIFIED_SKILL
    """

    staged_skill_id: str
    certified_skill_id: str
    candidate_skill_id: str
    owner_agent_id: str
    skill_domain: str
    proposed_name: str
    lifecycle_state: str                    # must == STAGED_LIFECYCLE_STATE
    staging_status: str                     # one of STAGING_STATUSES
    certification_refs: list[str]
    evidence_pack_refs: list[str]
    required_runtime_gates: list[str]
    safety_invariants: dict[str, bool]
    rollback_plan: str
    deprecation_plan: str
    runtime_activation_allowed: bool        # always False
    self_approval_allowed: bool             # always False
    active_runtime_requested: bool          # always False
    activation_request_status: str          # one of ACTIVATION_REQUEST_STATUSES
    activation_blockers: list[str]
    staged_at: str
    staged_by: str
    model_related: bool = False
    production_related: bool = False
    staging_version: str = STAGING_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lifecycle_state != STAGED_LIFECYCLE_STATE:
            raise ValueError(
                f"lifecycle_state must be {STAGED_LIFECYCLE_STATE!r}, "
                f"got {self.lifecycle_state!r}"
            )
        if self.staging_status not in STAGING_STATUSES:
            raise ValueError(
                f"staging_status must be one of {STAGING_STATUSES}, "
                f"got {self.staging_status!r}"
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
        if not self.deprecation_plan:
            raise ValueError("deprecation_plan must be non-empty")
        if not self.evidence_pack_refs:
            raise ValueError("evidence_pack_refs must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "staged_skill_id": self.staged_skill_id,
            "certified_skill_id": self.certified_skill_id,
            "candidate_skill_id": self.candidate_skill_id,
            "owner_agent_id": self.owner_agent_id,
            "skill_domain": self.skill_domain,
            "proposed_name": self.proposed_name,
            "lifecycle_state": self.lifecycle_state,
            "staging_status": self.staging_status,
            "certification_refs": self.certification_refs,
            "evidence_pack_refs": self.evidence_pack_refs,
            "required_runtime_gates": self.required_runtime_gates,
            "safety_invariants": self.safety_invariants,
            "rollback_plan": self.rollback_plan,
            "deprecation_plan": self.deprecation_plan,
            "runtime_activation_allowed": self.runtime_activation_allowed,
            "self_approval_allowed": self.self_approval_allowed,
            "active_runtime_requested": self.active_runtime_requested,
            "activation_request_status": self.activation_request_status,
            "activation_blockers": self.activation_blockers,
            "staged_at": self.staged_at,
            "staged_by": self.staged_by,
            "model_related": self.model_related,
            "production_related": self.production_related,
            "staging_version": self.staging_version,
            "metadata": self.metadata,
        }
