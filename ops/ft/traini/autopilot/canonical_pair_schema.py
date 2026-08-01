"""Canonical PairCandidate compatibility and approval normalization."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


CANONICAL_SCHEMA_VERSION = "pair-candidate-v1"


def normalize_pair_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """Promote legacy nested fields while preserving old names.

    Untrusted input can never self-approve. Approval is populated only from an
    explicit stored independent-clearance decision with a matching candidate
    hash; otherwise it is normalized to false.
    """
    result = deepcopy(row)
    provenance = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
    transform = provenance.get("pair_transformation") if isinstance(provenance.get("pair_transformation"), dict) else {}
    result["schema_version"] = CANONICAL_SCHEMA_VERSION
    result["input"] = str(result.get("input") or result.get("prompt") or "")
    result["expected_output"] = str(result.get("expected_output") or result.get("response") or "")
    result["prompt"] = result.get("prompt") or result["input"]
    result["response"] = result.get("response") or result["expected_output"]
    result["source_id"] = str(result.get("source_id") or provenance.get("record_id") or "")
    result["source_version"] = str(result.get("source_version") or provenance.get("source_version") or "v1")
    result["raw_source_hash"] = str(result.get("raw_source_hash") or transform.get("raw_source_hash") or provenance.get("source_checksum") or "")
    result["prepared_answer_hash"] = str(result.get("prepared_answer_hash") or transform.get("prepared_answer_hash") or "")
    result["response_contract"] = str(result.get("response_contract") or transform.get("response_contract") or "")
    result["independent_reviewer"] = str(result.get("independent_reviewer") or transform.get("independent_reviewer") or "")
    result["holdout_separation"] = str(result.get("holdout_separation") or transform.get("holdout_separation") or "")
    result["evidence_hashes"] = list(result.get("evidence_hashes") or provenance.get("evidence_hashes") or [])
    result["duplicate_key"] = str(result.get("duplicate_key") or result.get("pair_id") or "")
    result["approved_for_training"] = False
    clearance = result.get("independent_clearance") if isinstance(result.get("independent_clearance"), dict) else {}
    candidate_hash_payload = {
        "pair_id": result.get("pair_id"),
        "prompt": result.get("prompt"),
        "response": result.get("response"),
        "target_slot": result.get("target_slot"),
    }
    expected_clearance_hash = hashlib.sha256(json.dumps(candidate_hash_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if clearance.get("decision") == "ADMIT" and clearance.get("candidate_hash") == expected_clearance_hash:
        result["approved_for_training"] = True
    result["approval_authority"] = "independent_clearance_service" if clearance else None
    return result


def schema_errors(row: dict[str, Any]) -> list[str]:
    normalized = normalize_pair_candidate(row)
    required = ("pair_id", "source_id", "raw_source_hash", "target_slot", "input", "expected_output", "response_contract", "duplicate_key")
    return [f"MISSING_{field}" for field in required if not str(normalized.get(field) or "").strip()]
