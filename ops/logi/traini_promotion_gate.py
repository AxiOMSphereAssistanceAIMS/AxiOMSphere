"""Promotion gate model for Traini lifecycle."""
from __future__ import annotations

from typing import Any


def decide_promotion(
    *,
    dataset_quality_status: str,
    eval_status: str,
    baseline_recommendation: str,
    qa_status: str = "PENDING",
    poli_approval: str = "REQUIRED",
    release_status: str = "NOT_REQUESTED",
    allow_runtime_promotion: bool = False,
) -> dict[str, Any]:
    """Deterministic non-destructive promotion decision."""
    decision = "EVAL_ONLY"
    reason = "Default certification mode blocks runtime promotion."
    if dataset_quality_status == "INSUFFICIENT_DATA":
        decision = "INSUFFICIENT_DATA"
        reason = "Dataset is insufficient for safe tuning."
    elif eval_status != "PASS":
        decision = "REJECT"
        reason = "Evaluation did not pass."
    elif baseline_recommendation in {"RETUNE", "REJECT"}:
        decision = baseline_recommendation
        reason = f"Baseline comparison recommendation={baseline_recommendation}."
    elif allow_runtime_promotion and qa_status == "PASS" and poli_approval == "APPROVED" and release_status == "READY":
        decision = "PROMOTE"
        reason = "All gates approved."
    return {
        "decision": decision,
        "reason": reason,
        "qa_validation": qa_status,
        "poli_approval_required": True,
        "poli_approval_status": poli_approval,
        "release_step_required": True,
        "release_status": release_status,
        "runtime_promotion_executed": False,
        "policy": "No automatic runtime promotion in certification mode.",
    }

