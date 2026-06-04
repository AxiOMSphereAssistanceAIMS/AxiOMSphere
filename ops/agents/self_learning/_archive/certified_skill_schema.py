"""
AIMS Self-Learning — Certified Skill Package Schema.

A CertifiedSkillPackage converts a SANDBOX_PASS execution result into
a read-only certification artifact. It records evidence, gates, rollback
and deprecation plans, and safety invariants.

lifecycle_transition is always "SANDBOX_SKILL -> CERTIFIED_SKILL".
No package may target ACTIVE_RUNTIME_SKILL.
runtime_activation_allowed, self_approval_allowed, and active_runtime_requested
are always False at this phase.

No model calls, no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Lifecycle transition encoded in every certification package
CERT_LIFECYCLE_TRANSITION = "SANDBOX_SKILL -> CERTIFIED_SKILL"

# Certification status values
CERT_STATUS_READY = "CERTIFIED_SKILL_READY"
CERT_STATUS_WARN = "CERTIFIED_SKILL_WARN"
CERT_STATUS_REJECTED = "CERTIFICATION_REJECTED"

CERT_STATUSES: tuple[str, ...] = (
    CERT_STATUS_READY,
    CERT_STATUS_WARN,
    CERT_STATUS_REJECTED,
)

# No package may ever target this state at certification time
_FORBIDDEN_TARGET_STATE = "ACTIVE_RUNTIME_SKILL"

# Required safety invariant keys — all must be present and True
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

# Gates always required before any runtime activation can be considered
GATES_ALWAYS_REQUIRED_BEFORE_RUNTIME: tuple[str, ...] = (
    "explicit_AIMS_activation_decision",
    "argus_gate",
    "logi_gate",
    "qa_gate",
    "rollback_plan_review",
    "registry_update_review",
)

# Additional gate required when model_related=True
GATE_TRAINI_RUNTIME = "traini_gate"

CERT_VERSION = "1.0"

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)


@dataclass
class CertifiedSkillPackage:
    """
    Certification artifact for a SANDBOX_PASS skill execution.

    Immutable safety properties:
      runtime_activation_allowed = False
      self_approval_allowed = False
      active_runtime_requested = False

    lifecycle_transition must == CERT_LIFECYCLE_TRANSITION.
    certification_status must be in CERT_STATUSES.
    """

    certified_skill_id: str
    candidate_skill_id: str
    sandbox_plan_id: str
    execution_id: str
    owner_agent_id: str
    skill_domain: str
    proposed_name: str
    lifecycle_transition: str               # must == CERT_LIFECYCLE_TRANSITION
    certification_status: str               # one of CERT_STATUSES
    evidence_pack_refs: list[str]           # must be non-empty
    sandbox_result_refs: list[str]
    gates_passed: list[str]
    gates_required_before_runtime: list[str]
    safety_invariants: dict[str, bool]      # all REQUIRED_SAFETY_INVARIANTS must be True
    residual_risks: list[str]
    rollback_plan: str                      # must be non-empty
    deprecation_plan: str                   # must be non-empty
    runtime_activation_allowed: bool        # always False
    self_approval_allowed: bool             # always False
    active_runtime_requested: bool          # always False
    model_related: bool
    production_related: bool
    certification_created_at: str
    certification_version: str
    validator_signature: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lifecycle_transition != CERT_LIFECYCLE_TRANSITION:
            raise ValueError(
                f"lifecycle_transition must be {CERT_LIFECYCLE_TRANSITION!r}, "
                f"got {self.lifecycle_transition!r}"
            )
        if self.certification_status not in CERT_STATUSES:
            raise ValueError(
                f"certification_status must be one of {CERT_STATUSES}, "
                f"got {self.certification_status!r}"
            )
        if self.runtime_activation_allowed:
            raise ValueError("runtime_activation_allowed must be False")
        if self.self_approval_allowed:
            raise ValueError("self_approval_allowed must be False")
        if self.active_runtime_requested:
            raise ValueError("active_runtime_requested must be False")
        if not self.evidence_pack_refs:
            raise ValueError("evidence_pack_refs must be non-empty")
        if not self.rollback_plan:
            raise ValueError("rollback_plan must be non-empty")
        if not self.deprecation_plan:
            raise ValueError("deprecation_plan must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "certified_skill_id": self.certified_skill_id,
            "candidate_skill_id": self.candidate_skill_id,
            "sandbox_plan_id": self.sandbox_plan_id,
            "execution_id": self.execution_id,
            "owner_agent_id": self.owner_agent_id,
            "skill_domain": self.skill_domain,
            "proposed_name": self.proposed_name,
            "lifecycle_transition": self.lifecycle_transition,
            "certification_status": self.certification_status,
            "evidence_pack_refs": self.evidence_pack_refs,
            "sandbox_result_refs": self.sandbox_result_refs,
            "gates_passed": self.gates_passed,
            "gates_required_before_runtime": self.gates_required_before_runtime,
            "safety_invariants": self.safety_invariants,
            "residual_risks": self.residual_risks,
            "rollback_plan": self.rollback_plan,
            "deprecation_plan": self.deprecation_plan,
            "runtime_activation_allowed": self.runtime_activation_allowed,
            "self_approval_allowed": self.self_approval_allowed,
            "active_runtime_requested": self.active_runtime_requested,
            "model_related": self.model_related,
            "production_related": self.production_related,
            "certification_created_at": self.certification_created_at,
            "certification_version": self.certification_version,
            "validator_signature": self.validator_signature,
            "metadata": self.metadata,
        }
