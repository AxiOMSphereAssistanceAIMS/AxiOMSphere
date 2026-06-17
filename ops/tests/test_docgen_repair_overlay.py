from ops.docgen.universal_overlay.repair_overlay import (
    UniversalRepairRequest,
    decide_repair,
)


def test_decide_repair_for_coverage():
    decision = decide_repair(
        UniversalRepairRequest(
            document_type="maintenance_procedure",
            weakest_dimension="coverage",
        )
    )

    assert decision.repair_mode == "targeted_section_repair"
    assert any("gap closure" in action.lower() for action in decision.actions)


def test_decide_repair_degradation_rolls_back():
    decision = decide_repair(
        UniversalRepairRequest(
            document_type="maintenance_procedure",
            weakest_dimension="coverage",
            previous_score=0.90,
            current_score=0.85,
        )
    )

    assert decision.escalation == "rollback_to_best_version"


def test_decide_repair_repeated_failure_escalates():
    decision = decide_repair(
        UniversalRepairRequest(
            document_type="technical_report",
            weakest_dimension="standards",
            repeated_count=3,
        )
    )

    assert decision.escalation == "skill_or_training_candidate"
