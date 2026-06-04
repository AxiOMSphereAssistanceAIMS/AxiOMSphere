"""
AIMS Self-Learning — Runtime Activation Approval Schema.

A RuntimeActivationApprovalEntry is the gate skeleton for one
RuntimeActivationProposal. All entries default to BLOCKED with all
gate booleans False. No activation occurs at this phase.

No model calls, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── approval status ────────────────────────────────────────────────────────
APPROVAL_STATUS_PENDING = "PENDING_APPROVAL"
APPROVAL_STATUS_DRY_RUN = "APPROVED_FOR_DRY_RUN_ONLY"
APPROVAL_STATUS_BLOCKED = "BLOCKED"
APPROVAL_STATUS_REJECTED = "REJECTED"

APPROVAL_STATUSES: tuple[str, ...] = (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_DRY_RUN,
    APPROVAL_STATUS_BLOCKED,
    APPROVAL_STATUS_REJECTED,
)

APPROVAL_DEFAULT_STATUS = APPROVAL_STATUS_BLOCKED

# ── gate keys ──────────────────────────────────────────────────────────────
GATE_HUMAN = "human_approved"
GATE_ARGUS = "argus_gate_passed"
GATE_LOGI = "logi_task_ledger_registered"
GATE_QA = "qa_validation_passed"
GATE_TRAINI = "traini_validation_passed"
GATE_REGISTRY = "registry_update_approved"
GATE_ROLLBACK = "rollback_plan_approved"
GATE_RUNTIME_SAFETY = "runtime_safety_gate_passed"
GATE_DGX = "dgx_policy_verified"
GATE_SECRETS = "secrets_policy_verified"
GATE_PRODUCTION = "production_policy_verified"
GATE_MODEL = "model_policy_verified"
GATE_ACTIVATION_WINDOW = "activation_window_approved"

# All gates required for any approval (Traini is additional when model_related)
REQUIRED_GATES_BASE: tuple[str, ...] = (
    GATE_HUMAN,
    GATE_ARGUS,
    GATE_LOGI,
    GATE_QA,
    GATE_REGISTRY,
    GATE_ROLLBACK,
    GATE_RUNTIME_SAFETY,
    GATE_DGX,
    GATE_SECRETS,
    GATE_PRODUCTION,
    GATE_MODEL,
    GATE_ACTIVATION_WINDOW,
)

APPROVAL_VERSION = "1.0"


@dataclass
class RuntimeActivationApprovalEntry:
    """
    Approval gate skeleton for one RuntimeActivationProposal.

    All gate booleans default False.
    approval_status defaults BLOCKED.
    No entry may default to approved.

    Even when status reaches APPROVED_FOR_DRY_RUN_ONLY:
    - runtime activation remains disabled
    - active registry must not be modified
    - no agent behavior changes
    - no production skill execution
    """

    proposal_id: str
    certified_skill_id: str
    owner_agent_id: str
    skill_domain: str
    current_lifecycle_state: str
    proposed_lifecycle_state: str
    model_related: bool
    production_related: bool

    # approval status — defaults BLOCKED
    approval_status: str = APPROVAL_STATUS_BLOCKED

    # gate booleans — all default False
    human_approved: bool = False
    argus_gate_passed: bool = False
    logi_task_ledger_registered: bool = False
    qa_validation_passed: bool = False
    traini_validation_passed: bool = False
    registry_update_approved: bool = False
    rollback_plan_approved: bool = False
    runtime_safety_gate_passed: bool = False
    dgx_policy_verified: bool = False
    secrets_policy_verified: bool = False
    production_policy_verified: bool = False
    model_policy_verified: bool = False
    activation_window_approved: bool = False

    # approval record — defaults null
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    approval_reason: str = ""

    # blocking / rejection reasons
    rejection_reasons: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)

    approval_version: str = APPROVAL_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.approval_status not in APPROVAL_STATUSES:
            raise ValueError(
                f"approval_status must be one of {APPROVAL_STATUSES}, "
                f"got {self.approval_status!r}"
            )
        if self.approval_status == APPROVAL_STATUS_DRY_RUN:
            self._enforce_dry_run_gates()

    def _enforce_dry_run_gates(self) -> None:
        required = list(REQUIRED_GATES_BASE)
        if self.model_related:
            required.append(GATE_TRAINI)
        missing = [g for g in required if not getattr(self, g, False)]
        if missing:
            raise ValueError(
                f"APPROVED_FOR_DRY_RUN_ONLY requires all gates True; missing: {missing}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "certified_skill_id": self.certified_skill_id,
            "owner_agent_id": self.owner_agent_id,
            "skill_domain": self.skill_domain,
            "current_lifecycle_state": self.current_lifecycle_state,
            "proposed_lifecycle_state": self.proposed_lifecycle_state,
            "model_related": self.model_related,
            "production_related": self.production_related,
            "approval_status": self.approval_status,
            "human_approved": self.human_approved,
            "argus_gate_passed": self.argus_gate_passed,
            "logi_task_ledger_registered": self.logi_task_ledger_registered,
            "qa_validation_passed": self.qa_validation_passed,
            "traini_validation_passed": self.traini_validation_passed,
            "registry_update_approved": self.registry_update_approved,
            "rollback_plan_approved": self.rollback_plan_approved,
            "runtime_safety_gate_passed": self.runtime_safety_gate_passed,
            "dgx_policy_verified": self.dgx_policy_verified,
            "secrets_policy_verified": self.secrets_policy_verified,
            "production_policy_verified": self.production_policy_verified,
            "model_policy_verified": self.model_policy_verified,
            "activation_window_approved": self.activation_window_approved,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "approval_reason": self.approval_reason,
            "rejection_reasons": self.rejection_reasons,
            "blocking_reasons": self.blocking_reasons,
            "approval_version": self.approval_version,
            "metadata": self.metadata,
        }
