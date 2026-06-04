"""
AIMS Self-Learning — Runtime Activation Proposal Validator.

Validates RuntimeActivationProposal dicts before they are written to disk.
No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

from .runtime_activation_proposal_schema import (
    PROPOSAL_CURRENT_STATE,
    PROPOSAL_TARGET_STATE,
    PROPOSAL_STATUSES,
    ACTIVATION_REQUEST_STATUSES,
    REQUIRED_APPROVALS_BASE,
    APPROVAL_TRAINI,
    REQUIRED_RUNTIME_GATES,
    REQUIRED_SAFETY_INVARIANTS,
    FORBIDDEN_GOVERNORS,
    FORBIDDEN_DIRECT_CONTROLS,
)


class RuntimeActivationProposalValidator:

    def __init__(self) -> None:
        self._errors: list[str] = []
        self._warnings: list[str] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def is_valid(self) -> bool:
        return len(self._errors) == 0

    def validate(self, proposal: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # 1. current_lifecycle_state must be CERTIFIED_SKILL
        cls = proposal.get("current_lifecycle_state")
        if cls != PROPOSAL_CURRENT_STATE:
            self._errors.append(
                f"current_lifecycle_state must be {PROPOSAL_CURRENT_STATE!r}, got {cls!r}"
            )

        # 2. proposed_lifecycle_state is ACTIVE_RUNTIME_SKILL only as proposal target
        pls = proposal.get("proposed_lifecycle_state")
        if pls != PROPOSAL_TARGET_STATE:
            self._errors.append(
                f"proposed_lifecycle_state must be {PROPOSAL_TARGET_STATE!r}, got {pls!r}"
            )

        # 3. proposal_status must be allowed
        ps = proposal.get("proposal_status")
        if ps not in PROPOSAL_STATUSES:
            self._errors.append(
                f"proposal_status must be one of {PROPOSAL_STATUSES}, got {ps!r}"
            )

        # 4. activation_request_status
        ars = proposal.get("activation_request_status")
        if ars not in ACTIVATION_REQUEST_STATUSES:
            self._errors.append(
                f"activation_request_status must be one of {ACTIVATION_REQUEST_STATUSES}, got {ars!r}"
            )

        # 5. runtime_activation_allowed must be False
        if proposal.get("runtime_activation_allowed") is not False:
            self._errors.append(
                f"runtime_activation_allowed must be False, got {proposal.get('runtime_activation_allowed')!r}"
            )

        # 6. active_runtime_requested must be False
        if proposal.get("active_runtime_requested") is not False:
            self._errors.append(
                f"active_runtime_requested must be False, got {proposal.get('active_runtime_requested')!r}"
            )

        # 7. self_approval_allowed must be False
        if proposal.get("self_approval_allowed") is not False:
            self._errors.append(
                f"self_approval_allowed must be False, got {proposal.get('self_approval_allowed')!r}"
            )

        # 8. required approvals include base set
        approvals = proposal.get("required_approvals", [])
        for approval in REQUIRED_APPROVALS_BASE:
            if approval not in approvals:
                self._errors.append(f"required_approvals missing: {approval!r}")

        # 9. Traini approval when model_related
        if proposal.get("model_related") and APPROVAL_TRAINI not in approvals:
            self._errors.append(
                f"model_related proposal missing approval: {APPROVAL_TRAINI!r}"
            )

        # 10. required runtime gates
        gates = proposal.get("required_runtime_gates", [])
        for gate in REQUIRED_RUNTIME_GATES:
            if gate not in gates:
                self._errors.append(f"required_runtime_gates missing: {gate!r}")

        # 11. rollback_plan
        if not proposal.get("rollback_plan"):
            self._errors.append("rollback_plan must be non-empty")

        # 12. deactivation_plan
        if not proposal.get("deactivation_plan"):
            self._errors.append("deactivation_plan must be non-empty")

        # 13. monitoring_plan
        if not proposal.get("monitoring_plan"):
            self._errors.append("monitoring_plan must be non-empty")

        # 14. rate_limit_plan
        if not proposal.get("rate_limit_plan"):
            self._errors.append("rate_limit_plan must be non-empty")

        # 15. blast_radius defined and not unlimited
        br = proposal.get("blast_radius", "")
        if not br:
            self._errors.append("blast_radius must be non-empty")
        if "unlimited" in br.lower():
            self._errors.append("blast_radius must not be unlimited")

        # 16. validation_commands_required
        vcr = proposal.get("validation_commands_required", [])
        if not isinstance(vcr, list) or len(vcr) == 0:
            self._errors.append("validation_commands_required must be a non-empty list")

        # 17. post_activation_checks_required
        pac = proposal.get("post_activation_checks_required", [])
        if not isinstance(pac, list) or len(pac) == 0:
            self._errors.append("post_activation_checks_required must be a non-empty list")

        # 18. Hermes external worker is not proposed as governor
        owner = str(proposal.get("owner_agent_id", "")).lower()
        if any(fg in owner for fg in FORBIDDEN_GOVERNORS):
            self._errors.append(
                f"owner_agent_id references forbidden governor: {owner!r}"
            )
        proposed_by = str(proposal.get("proposed_by", "")).lower()
        if any(fg in proposed_by for fg in FORBIDDEN_GOVERNORS):
            self._errors.append(
                f"proposed_by references forbidden governor: {proposed_by!r}"
            )

        # 19. deletion/quarantine direct control blocked
        metadata = str(proposal.get("metadata", {})).lower()
        if "direct_deletion_control" in metadata or "direct_quarantine_control" in metadata:
            self._errors.append(
                "proposal metadata contains forbidden direct_deletion/quarantine control"
            )

        # 20. production service restart direct control blocked
        if "direct_production_restart" in metadata:
            self._errors.append(
                "proposal metadata contains forbidden direct_production_restart control"
            )

        # 21. model training/promotion direct control blocked
        if "direct_training_launch" in metadata or "direct_model_promotion" in metadata:
            self._errors.append(
                "proposal metadata contains forbidden direct_training/model_promotion control"
            )

        # 22. DGX slot32/slot120 policy preserved
        inv = proposal.get("safety_invariants", {})
        if inv.get("dgx_slot32_slot120_policy_preserved") is not True:
            self._errors.append(
                "safety_invariants[dgx_slot32_slot120_policy_preserved] must be True"
            )

        # remaining safety invariants
        for key in REQUIRED_SAFETY_INVARIANTS:
            if inv.get(key) is not True:
                self._errors.append(
                    f"safety_invariants[{key!r}] must be True, got {inv.get(key)!r}"
                )

        # 23/24. Active runtime registry not modified — structural check only
        # (no file I/O in validator; workflow enforces write isolation)

        if not proposal.get("proposal_id"):
            self._warnings.append("proposal_id is missing or empty")

        return self.is_valid()
