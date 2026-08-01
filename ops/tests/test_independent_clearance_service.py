from __future__ import annotations

from ops.ft.traini.autopilot.independent_clearance_service import clear_candidate


def _candidate(reviewer: str = "reviewer-b") -> dict:
    prompt = "Fix the code"
    response = "def fixed():\n    return True"
    return {
        "pair_id": "pair-1",
        "mode": "traini_model_tuning",
        "target_slot": "slot32",
        "material_type": "direct_coding",
        "prompt": prompt,
        "response": response,
        "provenance": {
            "record_id": "source-1",
            "source_path": "raw.json",
            "source_agent": "producer-a",
            "source_checksum": "source-hash",
            "source_excerpt": "validated source",
            "pair_transformation": {
                "review_status": "PASS",
                "response_contract": "direct_code",
                "negative_transfer_probe": "PASS",
                "holdout_separation": "PASS",
                "source_copy_ratio": 0.1,
                "raw_source_hash": "source-hash",
                "prepared_answer_hash": "answer-hash",
                "independent_reviewer": reviewer,
                "transformer_id": "transformer-a",
            },
        },
        "coverage_tags": ["test"],
        "eval_mapping_status": "MAPPED",
        "quality_score": "HIGH",
        "target_pool": "slot32_pair_pool",
        "output_mode": "traini_model_tuning_pairs",
        "routing_decision": "ACCEPT",
        "routing_reason": "test",
        "transformation_rule": "test",
        "gate_status": "PASS",
        "model_affinity": {"primary": "coder", "confidence": 1.0, "secondary": [], "evidence": ["test"]},
        "negative_transfer": {"status": "PASS", "sequence_overlap": 0.1, "token_overlap": 0.1, "reasons": []},
        "codex_cli_audit": {
            "status": "PASS",
            "auditor": "codex_cli",
            "audit_id": "audit-1",
            "pair_hash": "unused-by-service",
            "checks": {
                "provenance_traceable": True,
                "not_transcript_copy": True,
                "negative_transfer_passed": True,
                "response_contract_valid": True,
                "slot_routing_valid": True,
                "holdout_separated": True,
            },
        },
        "rejection_reason": None,
        "model_affinity": {"primary": "coder", "confidence": 1.0, "secondary": [], "evidence": ["test"]},
        "negative_transfer": {"status": "PASS", "sequence_overlap": 0.1, "token_overlap": 0.1, "reasons": []},
        "codex_cli_audit": {"status": "PASS", "auditor": "codex_cli", "audit_id": "audit-1", "checks": {"provenance_traceable": True, "not_transcript_copy": True, "negative_transfer_passed": True, "response_contract_valid": True, "slot_routing_valid": True, "holdout_separated": True}},
    }


def test_source_producer_cannot_self_clear() -> None:
    result = clear_candidate(_candidate(reviewer="producer-a"))
    assert result["decision"] == "REJECT"
    assert result["approved_for_training"] is False
    assert "REVIEWER_NOT_INDEPENDENT_OF_SOURCE_PRODUCER" in result["reasons"]


def test_distinct_reviewer_can_reach_clearance_gate() -> None:
    result = clear_candidate(_candidate(reviewer="reviewer-b"))
    # The service must still apply all existing gates; this fixture intentionally
    # proves only that reviewer identity is no longer the rejection reason.
    assert "REVIEWER_NOT_INDEPENDENT_OF_SOURCE_PRODUCER" not in result["reasons"]
    assert result["candidate_mutated"] is False
