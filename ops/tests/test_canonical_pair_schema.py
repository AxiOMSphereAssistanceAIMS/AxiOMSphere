from __future__ import annotations

from ops.ft.traini.autopilot.canonical_pair_schema import normalize_pair_candidate, schema_errors


def test_legacy_aliases_are_promoted_without_removing_old_fields() -> None:
    row = {"pair_id": "p1", "prompt": "problem", "response": "answer", "target_slot": "slot32", "provenance": {"record_id": "s1", "source_checksum": "h1", "pair_transformation": {"response_contract": "direct_code"}}}
    out = normalize_pair_candidate(row)
    assert out["input"] == "problem" and out["expected_output"] == "answer"
    assert out["source_id"] == "s1" and out["raw_source_hash"] == "h1"
    assert out["approved_for_training"] is False
    assert schema_errors(out) == []


def test_untrusted_approval_true_is_normalized_false() -> None:
    out = normalize_pair_candidate({"pair_id": "p1", "target_slot": "slot32", "input": "x", "expected_output": "y", "approved_for_training": True, "source_id": "s1", "raw_source_hash": "h", "response_contract": "direct_code"})
    assert out["approved_for_training"] is False


def test_only_matching_clearance_can_approve() -> None:
    base = {"pair_id": "p1", "target_slot": "slot32", "input": "x", "expected_output": "y", "source_id": "s1", "raw_source_hash": "h", "response_contract": "direct_code"}
    import hashlib, json
    expected = hashlib.sha256(json.dumps({"pair_id": "p1", "prompt": "x", "response": "y", "target_slot": "slot32"}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert normalize_pair_candidate(base | {"independent_clearance": {"decision": "ADMIT", "candidate_hash": expected}})["approved_for_training"] is True
    assert normalize_pair_candidate(base | {"independent_clearance": {"decision": "ADMIT", "candidate_hash": "hash"}})["approved_for_training"] is False
