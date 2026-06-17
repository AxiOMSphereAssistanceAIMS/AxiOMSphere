from ops.docgen.universal_overlay.self_improvement_gate import (
    build_self_improvement_manifest,
    decide_self_improvement_action,
)


def test_profile_failure_routes_to_profile_repair() -> None:
    decision = decide_self_improvement_action(
        document_type="maintenance_procedure",
        overall_quality=0.99,
        profile_conformance_passed=False,
        hard_gate_passed=True,
        render_passed=True,
        leakage_free=True,
    )

    assert decision.action == "PROFILE_REPAIR"
    assert decision.training_allowed is False


def test_quality_below_target_routes_to_skill_improvement() -> None:
    decision = decide_self_improvement_action(
        document_type="policy_framework",
        overall_quality=0.91,
        profile_conformance_passed=True,
        hard_gate_passed=True,
        render_passed=True,
        leakage_free=True,
    )

    assert decision.action == "SKILL_IMPROVEMENT"
    assert decision.promotion_allowed is False


def test_three_passes_still_require_review_before_training() -> None:
    decision = decide_self_improvement_action(
        document_type="technical_report",
        overall_quality=0.99,
        profile_conformance_passed=True,
        hard_gate_passed=True,
        render_passed=True,
        leakage_free=True,
        stable_success_count=3,
    )

    assert decision.action == "MODEL_LEARNING_CANDIDATE_REVIEW"
    assert decision.training_allowed is False


def test_manifest_covers_requested_document_types() -> None:
    manifest = build_self_improvement_manifest(
        document_types=["maintenance_procedure", "policy_framework"]
    )

    assert manifest["target_quality"] == 0.98
    assert manifest["backend"] == "ops.cyclic_doc_generation_pipeline.run_cyclic_generation"
    assert manifest["training_policy"]["automatic_training"] is False
    assert [item["document_type"] for item in manifest["profiles"]] == [
        "maintenance_procedure",
        "policy_framework",
    ]
