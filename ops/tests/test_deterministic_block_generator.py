from __future__ import annotations


def test_deterministic_block_generator_never_returns_none():
    from ops.docgen.deterministic_block_generator import DeterministicBlockGenerator

    block = DeterministicBlockGenerator().generate(
        block_spec={
            "id": "SEC-001",
            "label": "Executive Summary",
            "validation_rules": {
                "required_elements": ["problem_statement", "recommendations"],
                "min_length_words": 120,
            },
        },
        document_type="technical_report",
        topic="Aircraft preservation strategy",
        audience="engineering_stakeholders",
    )

    payload = block.to_dict()

    assert payload["block_id"] == "SEC-001"
    assert payload["content"]
    assert payload["generation_mode"] == "deterministic_fallback"
    assert len(payload["content"].split()) >= 120


def test_deterministic_block_generator_includes_required_elements():
    from ops.docgen.deterministic_block_generator import DeterministicBlockGenerator

    block = DeterministicBlockGenerator().generate(
        block_spec={
            "id": "SEC-004",
            "label": "Recommendations",
            "validation_rules": {
                "required_elements": ["actions", "success_criteria"],
                "min_length_words": 80,
            },
        },
        document_type="technical_report",
        topic="AIMS DOCGEN",
        audience="engineering_stakeholders",
    )

    text = block.content.lower()

    assert "actions" in text
    assert "success_criteria" in text


def test_deterministic_block_generator_stable_id_when_no_id():
    from ops.docgen.deterministic_block_generator import DeterministicBlockGenerator

    gen = DeterministicBlockGenerator()
    spec = {"label": "Background", "validation_rules": {"min_length_words": 60}}
    a = gen.generate(
        block_spec=spec,
        document_type="technical_report",
        topic="same topic",
        audience="eng",
    )
    b = gen.generate(
        block_spec=spec,
        document_type="technical_report",
        topic="same topic",
        audience="eng",
    )
    # Deterministic: identical spec/topic/type => identical block_id.
    assert a.block_id == b.block_id
    assert a.model_slot is None
