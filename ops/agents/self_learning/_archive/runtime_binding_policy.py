"""
AIMS Self-Learning — Runtime Binding Policy Enforcer.

Evaluates whether a Phase 13 approval entry may proceed to binding simulation.
No model calls, no I/O, no activation.
"""
from __future__ import annotations

from typing import Any

try:
    from .runtime_activation_approval_schema import (
        APPROVAL_STATUS_DRY_RUN,
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_PENDING,
        APPROVAL_STATUS_REJECTED,
    )
    from .runtime_binding_schema import (
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
    )
except ImportError:
    from agents.self_learning.runtime_activation_approval_schema import (  # type: ignore
        APPROVAL_STATUS_DRY_RUN,
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_PENDING,
        APPROVAL_STATUS_REJECTED,
    )
    from agents.self_learning.runtime_binding_schema import (  # type: ignore
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
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

_HARD_SAFETY_SIGNALS = (
    "runtime_activation_allowed",
    "agent_behavior_changed",
    "self_approval_allowed",
    "forbidden governor",
    "forbidden control",
)


def evaluate_binding_policy(
    approval_entry: dict[str, Any],
) -> tuple[str, bool, list[str]]:
    """
    Evaluate binding policy for one approval entry.

    Returns (simulated_binding_state, binding_allowed, blocking_reasons).
    READY_FOR_DRY_RUN_BINDING only when source approval is APPROVED_FOR_DRY_RUN_ONLY
    and all hard safety checks pass.
    """
    blocking: list[str] = []

    # Rule 1–4: binding allowed only when APPROVED_FOR_DRY_RUN_ONLY
    status = (
        approval_entry.get("source_approval_status")
        or approval_entry.get("approval_status", "")
    )
    if status != APPROVAL_STATUS_DRY_RUN:
        if status == APPROVAL_STATUS_BLOCKED:
            blocking.append("source approval status is BLOCKED — binding denied")
        elif status == APPROVAL_STATUS_PENDING:
            blocking.append("source approval status is PENDING_APPROVAL — binding denied")
        elif status == APPROVAL_STATUS_REJECTED:
            blocking.append("source approval status is REJECTED — binding denied")
        else:
            blocking.append(f"unrecognized source approval status: {status!r} — binding denied")

    # Rule 5: runtime activation always disabled
    if approval_entry.get("runtime_activation_allowed") is True:
        blocking.append("runtime_activation_allowed must be False")

    # Rule 6: active runtime registry must not be modified
    if approval_entry.get("active_runtime_registry_changed") is True:
        blocking.append("active_runtime_registry_changed must be False")

    # Rule 7: existing agent behavior must not be modified
    if approval_entry.get("agent_behavior_changed") is True:
        blocking.append("agent_behavior_changed must be False")

    # Rule 8: self-approval forbidden
    if approval_entry.get("self_approval_allowed") is True:
        blocking.append("self_approval_allowed must be False")

    # Rule 9: Hermes external worker must not be governor
    owner = str(approval_entry.get("owner_agent_id", "")).lower()
    for gov in _FORBIDDEN_GOVERNORS:
        if gov in owner:
            blocking.append(f"forbidden governor in owner_agent_id: {gov!r}")

    # Rules 11–17: forbidden controls in metadata
    meta = str(approval_entry.get("metadata", {})).lower()
    for ctrl in _FORBIDDEN_CONTROLS:
        if ctrl in meta:
            blocking.append(f"forbidden control in metadata: {ctrl!r}")

    # Rule 12: model-related entries require Traini gate
    traini_passed = (
        approval_entry.get("traini_validation_passed")
        or approval_entry.get("traini_gate_passed")
    )
    if approval_entry.get("model_related") and not traini_passed:
        blocking.append("model_related entry requires traini gate — not passed")

    if not blocking:
        return SIMULATED_READY, True, []

    # Distinguish hard safety violations (REJECTED_UNSAFE) from approval-gate blocks (BLOCKED_NOT_APPROVED)
    hard_violations = [
        r for r in blocking
        if any(sig in r for sig in _HARD_SAFETY_SIGNALS)
    ]
    state = SIMULATED_REJECTED if hard_violations else SIMULATED_BLOCKED
    return state, False, blocking
