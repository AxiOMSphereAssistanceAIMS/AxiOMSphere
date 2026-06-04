"""
AIMS Self-Learning — Runtime Activation Gate Evaluator.

Evaluates whether an approval entry satisfies all required gates
for APPROVED_FOR_DRY_RUN_ONLY status.

All entries default to BLOCKED. No activation occurs.
No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

try:
    from .runtime_activation_approval_schema import (
        REQUIRED_GATES_BASE,
        GATE_TRAINI,
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_DRY_RUN,
    )
except ImportError:
    from agents.self_learning.runtime_activation_approval_schema import (  # type: ignore
        REQUIRED_GATES_BASE,
        GATE_TRAINI,
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_DRY_RUN,
    )

_FORBIDDEN_CONTROLS = (
    "direct_deletion_control",
    "direct_quarantine_control",
    "direct_production_restart",
    "direct_training_launch",
    "direct_model_promotion",
)


def evaluate_gate_status(entry: dict[str, Any]) -> tuple[str, list[str]]:
    """
    Evaluate gate status for an approval entry dict.

    Returns (status, blocking_reasons).
    APPROVED_FOR_DRY_RUN_ONLY is returned only when ALL required gates pass.
    All other cases return BLOCKED.
    """
    blocking: list[str] = []

    # All base gates must be True
    for gate in REQUIRED_GATES_BASE:
        if not entry.get(gate):
            blocking.append(f"gate not passed: {gate}")

    # Model-related proposals also require Traini gate
    if entry.get("model_related") and not entry.get(GATE_TRAINI):
        blocking.append(f"model_related proposal missing gate: {GATE_TRAINI}")

    # Hard safety invariants
    if entry.get("self_approval_allowed") is True:
        blocking.append("self_approval_allowed must be False")
    if entry.get("runtime_activation_allowed") is True:
        blocking.append("runtime_activation_allowed must be False")

    # Forbidden direct controls in metadata
    meta = str(entry.get("metadata", {})).lower()
    for forbidden in _FORBIDDEN_CONTROLS:
        if forbidden in meta:
            blocking.append(f"forbidden control in metadata: {forbidden}")

    if blocking:
        return APPROVAL_STATUS_BLOCKED, blocking
    return APPROVAL_STATUS_DRY_RUN, []


def build_gate_matrix(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build a gate matrix summarising the gate state for all entries.
    """
    all_gates = list(REQUIRED_GATES_BASE) + [GATE_TRAINI]
    rows = []
    for entry in entries:
        status, blocking = evaluate_gate_status(entry)
        rows.append({
            "proposal_id": entry.get("proposal_id"),
            "certified_skill_id": entry.get("certified_skill_id"),
            "skill_domain": entry.get("skill_domain"),
            "model_related": entry.get("model_related"),
            "computed_status": status,
            "blocking_count": len(blocking),
            "blocking_reasons": blocking,
            "gates": {g: bool(entry.get(g)) for g in all_gates},
        })
    return {
        "gate_matrix": rows,
        "total": len(rows),
        "blocked": sum(1 for r in rows if r["computed_status"] == APPROVAL_STATUS_BLOCKED),
        "approved_for_dry_run_only": sum(
            1 for r in rows if r["computed_status"] == APPROVAL_STATUS_DRY_RUN
        ),
    }
