"""Conservative semantic route decisions for bounded learning units."""
from __future__ import annotations

from typing import Any

from ops.ft.traini.autopilot.learning_unit import LearningUnit


def classify_unit(unit: LearningUnit) -> dict[str, Any]:
    if unit.producer_mode == "agent_skill_learning" or unit.unit_type == "SKILL_LEARNING_UNIT":
        return {"learning_unit_id": unit.learning_unit_id, "decision": "NON_MODEL_ROUTE", "route": "AGENT_SKILL_LEARNING", "confidence": 1.0, "reason": "producer mode preserved"}
    if unit.unit_type == "MODEL_LEARNING_UNIT" and unit.verification_status == "PASS" and len(unit.route_candidates) == 1:
        return {"learning_unit_id": unit.learning_unit_id, "decision": "SINGLE_MODEL_ROUTE", "route": unit.route_candidates[0], "confidence": 0.95, "reason": "explicit verified model route"}
    if unit.unit_type == "EVALUATION_UNIT":
        return {"learning_unit_id": unit.learning_unit_id, "decision": "NON_MODEL_ROUTE", "route": "EVALUATION_CASE", "confidence": 0.9, "reason": "rejection/evaluation unit"}
    if unit.verification_status != "PASS":
        return {"learning_unit_id": unit.learning_unit_id, "decision": "HOLD_FOR_REVIEW", "route": "HOLD", "confidence": 0.2, "reason": "verification incomplete"}
    return {"learning_unit_id": unit.learning_unit_id, "decision": "NON_MODEL_ROUTE", "route": "AUDIT_EVIDENCE_ONLY", "confidence": 0.8, "reason": "no supported model objective"}
