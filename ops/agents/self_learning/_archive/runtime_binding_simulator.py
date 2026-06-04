"""
AIMS Self-Learning — Runtime Binding Simulator.

Simulates what would be required to bind approved skills to agents.
No model calls, no I/O beyond caller, no activation.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any

try:
    from .runtime_binding_schema import (
        RuntimeBindingSimulationEntry,
        BINDING_STATE_DRY_RUN_ONLY,
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
    )
    from .runtime_binding_policy import evaluate_binding_policy
    from .runtime_activation_approval_schema import (
        APPROVAL_STATUS_DRY_RUN,
        GATE_TRAINI,
        REQUIRED_GATES_BASE,
    )
except ImportError:
    from agents.self_learning.runtime_binding_schema import (  # type: ignore
        RuntimeBindingSimulationEntry,
        BINDING_STATE_DRY_RUN_ONLY,
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
    )
    from agents.self_learning.runtime_binding_policy import evaluate_binding_policy  # type: ignore
    from agents.self_learning.runtime_activation_approval_schema import (  # type: ignore
        APPROVAL_STATUS_DRY_RUN,
        GATE_TRAINI,
        REQUIRED_GATES_BASE,
    )


def simulate_binding(approval_entry: dict[str, Any]) -> RuntimeBindingSimulationEntry:
    """Simulate a binding evaluation for one Phase 13 approval entry dict."""
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    simulated_state, binding_allowed, blocking_reasons = evaluate_binding_policy(approval_entry)

    source_status = (
        approval_entry.get("source_approval_status")
        or approval_entry.get("approval_status", "")
    )
    model_related = bool(approval_entry.get("model_related"))
    traini_required = model_related
    traini_passed = bool(
        approval_entry.get("traini_validation_passed")
        or approval_entry.get("traini_gate_passed")
    )

    # Missing gates are only meaningful when blocked for non-approval-status reasons
    required_missing: list[str] = []
    if not binding_allowed and source_status == APPROVAL_STATUS_DRY_RUN:
        for gate in REQUIRED_GATES_BASE:
            if not approval_entry.get(gate):
                required_missing.append(gate)
        if traini_required and not traini_passed:
            required_missing.append(GATE_TRAINI)

    return RuntimeBindingSimulationEntry(
        binding_id=f"binding-{uuid.uuid4().hex[:12]}",
        proposal_id=approval_entry.get("proposal_id", ""),
        certified_skill_id=approval_entry.get("certified_skill_id", ""),
        owner_agent_id=approval_entry.get("owner_agent_id", ""),
        skill_domain=approval_entry.get("skill_domain", ""),
        source_approval_status=source_status,
        requested_binding_state=BINDING_STATE_DRY_RUN_ONLY,
        simulated_binding_state=simulated_state,
        binding_allowed=binding_allowed,
        binding_blocked=not binding_allowed,
        blocking_reasons=blocking_reasons,
        required_missing_gates=required_missing,
        runtime_activation_allowed=False,
        self_approval_allowed=False,
        active_runtime_registry_would_change=False,
        active_runtime_registry_changed=False,
        agent_behavior_would_change=False,
        agent_behavior_changed=False,
        rollback_plan_available=bool(approval_entry.get("rollback_plan_approved")),
        deactivation_plan_available=bool(approval_entry.get("rollback_plan_approved")),
        dgx_policy_verified=bool(approval_entry.get("dgx_policy_verified")),
        secrets_policy_verified=bool(approval_entry.get("secrets_policy_verified")),
        production_policy_verified=bool(approval_entry.get("production_policy_verified")),
        model_policy_verified=bool(approval_entry.get("model_policy_verified")),
        traini_gate_required=traini_required,
        traini_gate_passed=traini_passed,
        created_at=created_at,
    )


def simulate_all_bindings(
    approval_entries: list[dict[str, Any]],
) -> list[RuntimeBindingSimulationEntry]:
    return [simulate_binding(e) for e in approval_entries]


def build_binding_matrix(
    binding_entries: list[RuntimeBindingSimulationEntry],
) -> dict[str, Any]:
    entry_dicts = [e.to_dict() for e in binding_entries]
    blocked = sum(1 for e in entry_dicts if e["simulated_binding_state"] == SIMULATED_BLOCKED)
    ready = sum(1 for e in entry_dicts if e["simulated_binding_state"] == SIMULATED_READY)
    rejected = sum(1 for e in entry_dicts if e["simulated_binding_state"] == SIMULATED_REJECTED)
    return {
        "binding_matrix": entry_dicts,
        "total": len(entry_dicts),
        "blocked_not_approved": blocked,
        "ready_for_dry_run_binding": ready,
        "rejected_unsafe": rejected,
        "active_registry_changed": False,
    }
