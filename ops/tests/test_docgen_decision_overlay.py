from ops.docgen.universal_overlay.decision_overlay import (
    branch_candidates_from_history,
    canonical_skill_registry_exists,
    skill_candidates_from_history,
    training_candidates_from_history,
)


def test_canonical_skill_registry_exists():
    assert canonical_skill_registry_exists()


def test_skill_candidates_cross_document_type():
    history = [
        {"failure": "missing_acceptance_criteria", "document_type": "maintenance_procedure"},
        {"failure": "missing_acceptance_criteria", "document_type": "operating_instruction"},
    ]

    assert skill_candidates_from_history(history) == ["missing_acceptance_criteria"]


def test_branch_candidates_repeated_failure():
    history = [
        {"failure": "render_fail", "document_type": "maintenance_procedure"},
        {"failure": "render_fail", "document_type": "technical_report"},
    ]

    assert branch_candidates_from_history(history) == ["docx_render_branch"]


def test_training_candidates_require_approved_example():
    history = [
        {"failure": "generic_steps", "document_type": "maintenance_procedure"},
        {"failure": "generic_steps", "document_type": "maintenance_procedure"},
        {"failure": "generic_steps", "document_type": "maintenance_procedure", "approved_training_example": True},
    ]

    assert training_candidates_from_history(history) == ["generic_steps"]
