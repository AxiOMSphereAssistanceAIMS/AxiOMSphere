"""
AIMS Self-Learning — Runtime Binding Validator.

Validates binding simulation report entries before writing to disk.
No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

try:
    from .runtime_binding_schema import (
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
    )
    from .runtime_activation_approval_schema import (
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_PENDING,
        APPROVAL_STATUS_REJECTED,
    )
except ImportError:
    from agents.self_learning.runtime_binding_schema import (  # type: ignore
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
    )
    from agents.self_learning.runtime_activation_approval_schema import (  # type: ignore
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_PENDING,
        APPROVAL_STATUS_REJECTED,
    )

_FORBIDDEN_CONTROLS = (
    "direct_deletion_control",
    "direct_quarantine_control",
    "direct_production_restart",
    "direct_training_launch",
    "direct_model_promotion",
    "direct_model_load",
    "direct_model_unload",
    "secrets_access",
    "external_send",
)

_FORBIDDEN_GOVERNORS = ("hermes",)


class RuntimeBindingValidator:

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

    def validate(
        self,
        binding: dict[str, Any],
        approval_entry: dict[str, Any] | None = None,
    ) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # 2. every binding maps to its Phase 13 approval entry
        if approval_entry is not None:
            if binding.get("proposal_id") != approval_entry.get("proposal_id"):
                self._errors.append(
                    f"binding proposal_id {binding.get('proposal_id')!r} "
                    f"does not match approval entry {approval_entry.get('proposal_id')!r}"
                )

        source_status = binding.get("source_approval_status", "")

        # 3. BLOCKED approval must not bind
        if source_status == APPROVAL_STATUS_BLOCKED:
            if binding.get("simulated_binding_state") != SIMULATED_BLOCKED:
                self._errors.append(
                    "BLOCKED approval entry must produce BLOCKED_NOT_APPROVED binding"
                )
            if binding.get("binding_allowed") is True:
                self._errors.append("BLOCKED approval entry must have binding_allowed=False")

        # 4. PENDING_APPROVAL must not bind
        if source_status == APPROVAL_STATUS_PENDING:
            if binding.get("binding_allowed") is True:
                self._errors.append("PENDING_APPROVAL entry must not bind")

        # 5. REJECTED must not bind
        if source_status == APPROVAL_STATUS_REJECTED:
            if binding.get("binding_allowed") is True:
                self._errors.append("REJECTED entry must not bind")

        # 7. active_runtime_registry_changed always False
        if binding.get("active_runtime_registry_changed") is True:
            self._errors.append("active_runtime_registry_changed must be False")

        # 8. agent_behavior_changed always False
        if binding.get("agent_behavior_changed") is True:
            self._errors.append("agent_behavior_changed must be False")

        # 9. runtime_activation_allowed always False
        if binding.get("runtime_activation_allowed") is True:
            self._errors.append("runtime_activation_allowed must be False")

        # 10. self_approval_allowed always False
        if binding.get("self_approval_allowed") is True:
            self._errors.append("self_approval_allowed must be False")

        # 11. Hermes must not be governor
        owner = str(binding.get("owner_agent_id", "")).lower()
        for gov in _FORBIDDEN_GOVERNORS:
            if gov in owner:
                self._errors.append(f"forbidden governor in owner_agent_id: {gov!r}")

        # 12–17. forbidden controls in metadata
        meta = str(binding.get("metadata", {})).lower()
        for ctrl in _FORBIDDEN_CONTROLS:
            if ctrl in meta:
                self._errors.append(f"forbidden control in metadata: {ctrl!r}")

        # 18. DGX policy: binding_allowed=True requires dgx_policy_verified=True
        if binding.get("binding_allowed") is True and not binding.get("dgx_policy_verified"):
            self._errors.append("binding_allowed=True requires dgx_policy_verified=True")

        # 19. Traini gate for model-related when binding allowed
        if binding.get("traini_gate_required") and binding.get("binding_allowed") is True:
            if not binding.get("traini_gate_passed"):
                self._errors.append(
                    "model_related binding_allowed=True requires traini_gate_passed=True"
                )

        return self.is_valid()

    def validate_report(
        self,
        bindings: list[dict[str, Any]],
        approval_entries: list[dict[str, Any]] | None = None,
        expected_all_blocked: bool = False,
    ) -> bool:
        all_valid = True

        approval_map: dict[str, dict[str, Any]] = {}
        if approval_entries is not None:
            approval_map = {e.get("proposal_id", ""): e for e in approval_entries}

        for binding in bindings:
            pid = binding.get("proposal_id", "")
            ae = approval_map.get(pid) if approval_map else None
            if not self.validate(binding, ae):
                all_valid = False

        # 6. all bindings blocked when Phase 13 has 0 approvals
        if expected_all_blocked:
            for binding in bindings:
                state = binding.get("simulated_binding_state")
                if state != SIMULATED_BLOCKED:
                    self._errors.append(
                        f"expected BLOCKED_NOT_APPROVED, "
                        f"got {state!r} for {binding.get('proposal_id')!r}"
                    )
                    all_valid = False

        return all_valid
