"""Canonical semantic per-unit routing facade.

The classifier remains deliberately conservative: producer metadata can
preserve a skill route, but model admission requires an explicit verified
objective and route in the bounded evidence.
"""
from __future__ import annotations

from typing import Any

from .learning_unit import LearningUnit
from .learning_unit_route_classifier import classify_unit


ROUTER_POLICY_VERSION = "route-policy-v1"


def route_learning_unit(unit: LearningUnit) -> dict[str, Any]:
    decision = classify_unit(unit)
    route = decision.get("route", "HOLD")
    return {
        "learning_unit_id": unit.learning_unit_id,
        "route": route,
        "target_slot": route.removeprefix("MODEL_TRAINING_SLOT") if route.startswith("MODEL_TRAINING_SLOT") else None,
        "task_family": unit.task_family,
        "affinity_score": decision.get("confidence", 0.0),
        "supporting_features": [decision.get("reason", "")],
        "disqualifying_features": [] if route != "HOLD" else ["insufficient_verified_evidence"],
        "confidence": decision.get("confidence", 0.0),
        "policy_version": ROUTER_POLICY_VERSION,
        "decision_reason": decision.get("reason", ""),
        "decision": decision.get("decision", "HOLD_FOR_REVIEW"),
    }
