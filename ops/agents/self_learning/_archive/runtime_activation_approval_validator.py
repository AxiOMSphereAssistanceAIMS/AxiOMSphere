"""
AIMS Self-Learning — Runtime Activation Approval Validator.

Validates RuntimeActivationApprovalEntry dicts before writing to disk.
No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

try:
    from .runtime_activation_approval_schema import (
        APPROVAL_STATUSES,
        APPROVAL_STATUS_DRY_RUN,
        REQUIRED_GATES_BASE,
        GATE_TRAINI,
    )
    from .runtime_activation_gate_evaluator import evaluate_gate_status
except ImportError:
    from agents.self_learning.runtime_activation_approval_schema import (  # type: ignore
        APPROVAL_STATUSES,
        APPROVAL_STATUS_DRY_RUN,
        REQUIRED_GATES_BASE,
        GATE_TRAINI,
    )
    from agents.self_learning.runtime_activation_gate_evaluator import evaluate_gate_status  # type: ignore


class RuntimeActivationApprovalValidator:

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

    def validate(self, entry: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # 1. approval_status must be one of the allowed values
        status = entry.get("approval_status")
        if status not in APPROVAL_STATUSES:
            self._errors.append(
                f"approval_status must be one of {APPROVAL_STATUSES}, got {status!r}"
            )

        # 2. APPROVED_FOR_DRY_RUN_ONLY is impossible unless all gates are True
        if status == APPROVAL_STATUS_DRY_RUN:
            computed, blocking = evaluate_gate_status(entry)
            if computed != APPROVAL_STATUS_DRY_RUN:
                self._errors.append(
                    f"APPROVED_FOR_DRY_RUN_ONLY requires all gates True; blocking: {blocking}"
                )

        # 3. all required gate keys must be present
        for gate in REQUIRED_GATES_BASE:
            if gate not in entry:
                self._errors.append(f"required gate key missing: {gate!r}")

        # 4. model-related DRY_RUN entries require Traini gate
        if entry.get("model_related") and status == APPROVAL_STATUS_DRY_RUN:
            if not entry.get(GATE_TRAINI):
                self._errors.append(
                    f"model_related APPROVED_FOR_DRY_RUN_ONLY entry missing gate: {GATE_TRAINI!r}"
                )

        # 5. self-approval forbidden
        if entry.get("self_approval_allowed") is True:
            self._errors.append("self_approval_allowed must be False")

        # 6. runtime activation remains disabled
        if entry.get("runtime_activation_allowed") is True:
            self._errors.append("runtime_activation_allowed must be False")

        # 7. active runtime registry not modified — structurally enforced by workflow write isolation

        # 8. deletion/quarantine control forbidden
        meta = str(entry.get("metadata", {})).lower()
        if "direct_deletion_control" in meta or "direct_quarantine_control" in meta:
            self._errors.append("metadata contains forbidden deletion/quarantine control")

        # 9. production restart control forbidden
        if "direct_production_restart" in meta:
            self._errors.append("metadata contains forbidden production_restart control")

        # 10. model training/promotion control forbidden
        if "direct_training_launch" in meta or "direct_model_promotion" in meta:
            self._errors.append("metadata contains forbidden training/model_promotion control")

        # 11–13. warn when key safety gates are False (expected for default BLOCKED entries)
        if entry.get("dgx_policy_verified") is False:
            self._warnings.append("dgx_policy_verified is False — DGX policy not yet verified")
        if entry.get("secrets_policy_verified") is False:
            self._warnings.append("secrets_policy_verified is False")
        if entry.get("rollback_plan_approved") is False:
            self._warnings.append("rollback_plan_approved is False")

        # 14. proposal_id must be present
        if not entry.get("proposal_id"):
            self._warnings.append("proposal_id is missing or empty")

        return self.is_valid()

    def validate_manifest(
        self,
        entries: list[dict[str, Any]],
        proposals: list[dict[str, Any]] | None = None,
    ) -> bool:
        """
        Validate all entries. Optionally cross-reference against proposal list.
        Returns True only if all entries pass.
        """
        all_valid = True

        if proposals is not None:
            proposal_ids = {p.get("proposal_id") for p in proposals}
            for entry in entries:
                pid = entry.get("proposal_id")
                if pid not in proposal_ids:
                    self._errors.append(
                        f"approval entry proposal_id not found in proposals: {pid!r}"
                    )
                    all_valid = False

        for entry in entries:
            if not self.validate(entry):
                all_valid = False

        return all_valid
