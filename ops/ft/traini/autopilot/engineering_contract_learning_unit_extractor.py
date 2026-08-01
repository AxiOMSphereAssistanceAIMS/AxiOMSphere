"""Bounded extraction for real engineering-contract records."""
from __future__ import annotations

import json
from typing import Any

from ops.ft.traini.autopilot.learning_unit import LearningUnit


def _bounded(value: Any, limit: int = 2400) -> str:
    return str(value or "").strip()[:limit]


def extract_engineering_units(record: Any) -> list[LearningUnit]:
    """Extract evidence-bound units without copying the source JSON.

    Producer-declared ``agent_skill_learning`` is preserved. A model unit is
    emitted only when the source explicitly contains an accepted resolution,
    runtime verification and a concrete model route; otherwise the source is
    represented as a skill/audit unit or held by the caller.
    """
    try:
        payload = json.loads(str(getattr(record, "content", "")))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("event_type") not in {"contract_resolution", "contract_rejection"}:
        return []
    source_id = str(getattr(record, "record_id", ""))
    source_version = str((getattr(record, "metadata", {}) or {}).get("source_version") or "v1")
    raw_hash = str(getattr(record, "checksum", "") or "")
    producer_mode = (getattr(record, "metadata", {}) or {}).get("mode")
    event_type = payload.get("event_type")
    objective = _bounded(payload.get("objective"))
    problem = _bounded(payload.get("learning_problem") or objective)
    accepted = payload.get("accepted_resolution") if isinstance(payload.get("accepted_resolution"), dict) else {}
    source_truth = payload.get("source_truth") if isinstance(payload.get("source_truth"), dict) else {}
    verification = bool(source_truth.get("runtime_checks_pass") or source_truth.get("decision") == "runtime_verified")
    evidence = source_truth.get("evidence_hashes") if isinstance(source_truth.get("evidence_hashes"), dict) else {}
    evidence_hashes = [str(v) for v in evidence.values() if isinstance(v, str) and v]
    target = _bounded(accepted.get("payload") if accepted else "")
    model_route = source_truth.get("model_route") if isinstance(source_truth.get("model_route"), dict) else {}
    if event_type == "contract_rejection":
        unit_type = "SKILL_LEARNING_UNIT" if producer_mode == "agent_skill_learning" else "EVALUATION_UNIT"
        target = _bounded(payload.get("rejection_reason") or payload.get("auditor_feedback") or "No accepted resolution; preserve as a rejected/evaluation case.")
        verification_status = "FAILED" if payload.get("rejection_reason") else "UNKNOWN"
        task_family = "agent_skill" if unit_type.startswith("SKILL") else "evaluation"
    elif producer_mode == "agent_skill_learning":
        unit_type, task_family, verification_status = "SKILL_LEARNING_UNIT", "agent_skill", "PASS" if verification else "UNKNOWN"
    elif accepted and verification and str(model_route.get("slot")) in {"14", "32", "120"}:
        unit_type, task_family, verification_status = "MODEL_LEARNING_UNIT", "verified_runtime_contract", "PASS"
    else:
        unit_type, task_family, verification_status = "AUDIT_EVIDENCE_UNIT", "operational_audit", "PASS" if verification else "UNKNOWN"
    bounded_input = f"{payload.get('contract','unknown')}: {problem}"[:3600]
    bounded_target = target[:3600]
    unit_id = LearningUnit.deterministic_id(source_id, source_version, unit_type, bounded_input, bounded_target)
    routes = ["AGENT_SKILL_LEARNING"] if unit_type == "SKILL_LEARNING_UNIT" else ["AUDIT_EVIDENCE_ONLY"]
    if unit_type == "MODEL_LEARNING_UNIT":
        routes = [f"MODEL_TRAINING_SLOT{model_route.get('slot')}" ]
    return [LearningUnit(unit_id, source_id, source_version, raw_hash, evidence_hashes, unit_type, problem, _bounded(source_truth.get("decision") or payload.get("auditor_feedback") or ""), _bounded(source_truth.get("decision") or ""), _bounded(accepted.get("status") or ""), verification_status, _bounded(source_truth.get("runtime_validation_sha256") or ""), bounded_input, bounded_target, task_family, route_candidates=routes, excluded_content=["full_source_json", "transcript_body", "private_scratchpad"], producer_mode=producer_mode)]
