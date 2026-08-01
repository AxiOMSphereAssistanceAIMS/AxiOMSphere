"""Independent, fail-closed clearance for prepared Traini candidates.

This service deliberately does not discover sources or synthesize pairs.  It
reviews an already bounded candidate and emits an auditable decision.  The
existing preparation gates remain the source of the detailed contamination
checks; this layer adds an explicit reviewer identity boundary and a separate
decision record before dataset admission.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _hash_candidate(candidate: dict[str, Any]) -> str:
    payload = {
        "pair_id": candidate.get("pair_id"),
        "prompt": candidate.get("prompt"),
        "response": candidate.get("response"),
        "target_slot": candidate.get("target_slot"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def clear_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a separate clearance decision without mutating the candidate.

    ``approved_for_training`` is true only in the returned decision after all
    checks pass.  A producer, transformer, or this function's input record can
    never self-approve by setting a field on the candidate itself.
    """
    from ops.ft.traini.autopilot.raw_material_pair_preparation import (
        PairCandidate,
        reject_contamination,
        validate_candidate_schema,
    )

    pair_id = str(candidate.get("pair_id") or "")
    provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
    transform = provenance.get("pair_transformation") if isinstance(provenance.get("pair_transformation"), dict) else {}
    source_agent = str(provenance.get("source_agent") or "").strip().lower()
    reviewer = str(transform.get("independent_reviewer") or "").strip().lower()
    transformer = str(
        transform.get("transformer_id") or transform.get("extractor_id") or transform.get("prepared_by") or ""
    ).strip().lower()
    reasons: list[str] = []
    if not reviewer:
        reasons.append("REVIEWER_IDENTITY_MISSING")
    if source_agent and reviewer and source_agent == reviewer:
        reasons.append("REVIEWER_NOT_INDEPENDENT_OF_SOURCE_PRODUCER")
    if transformer and reviewer == transformer:
        reasons.append("REVIEWER_NOT_INDEPENDENT_OF_TRANSFORMER")

    try:
        typed = PairCandidate(**candidate)
    except (TypeError, ValueError) as exc:
        reasons.append(f"CANDIDATE_SCHEMA_UNREADABLE:{type(exc).__name__}")
        typed = None
    if typed is not None:
        reasons.extend(f"SCHEMA:{item}" for item in validate_candidate_schema(typed))
        rejected, reason = reject_contamination(typed)
        if rejected and reason:
            reasons.append(f"CONTAMINATION:{reason}")

    decision = "ADMIT" if not reasons else "REJECT"
    return {
        "clearance_version": "independent-clearance-v1",
        "pair_id": pair_id,
        "candidate_hash": _hash_candidate(candidate),
        "reviewer_identity": reviewer or None,
        "source_producer_identity": source_agent or None,
        "transformer_identity": transformer or None,
        "decision": decision,
        "approved_for_training": decision == "ADMIT",
        "reasons": sorted(set(reasons)),
        "candidate_mutated": False,
    }


def clear_jsonl(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [clear_candidate(row) for row in rows]
    return {
        "clearance_version": "independent-clearance-v1",
        "candidate_count": len(decisions),
        "clearance_coverage_percent": 100 if decisions else 100,
        "admitted_count": sum(item["decision"] == "ADMIT" for item in decisions),
        "rejected_count": sum(item["decision"] == "REJECT" for item in decisions),
        "candidate_without_clearance": 0,
        "decisions": decisions,
    }
