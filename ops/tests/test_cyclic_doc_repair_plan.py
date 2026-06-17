from __future__ import annotations

from ops.cyclic_doc_generation_pipeline import (
    _build_repair_plan,
    _missing_section_recommendations,
)


def test_repair_plan_is_bounded_and_prioritizes_audit() -> None:
    audit = [
        f"Section {index}.0: Add audit control {index}"
        for index in range(1, 20)
    ]
    axi = [
        f"Section {index}.0: Add Axi control {index}"
        for index in range(1, 20)
    ]

    plan = _build_repair_plan(
        axi,
        audit,
        max_targets=4,
        max_recommendations=6,
        max_per_target=2,
        use_phase1_convergence=False,  # test legacy path directly
    )

    assert plan["selected"] == audit[:4] + axi[:2]
    assert plan["selected_count"] == 6
    assert len(plan["selected_targets"]) == 4
    assert plan["deferred_count"] == 32


def test_repair_plan_resolves_add_element_as_new_section() -> None:
    plan = _build_repair_plan(
        [],
        ["Section 8.0: Add Element 8.18 Supplier Management"],
    )

    assert plan["selected_count"] == 1
    assert plan["selected_targets"] == ["NEW:8.18"]


def test_missing_sections_become_prioritized_new_section_work() -> None:
    recommendations = _missing_section_recommendations(
        [
            "8.18 Element 18: Supplier Management — defines vendor controls",
            "9.1 Annexure 1: Compliance Matrix",
        ]
    )
    plan = _build_repair_plan([], recommendations)

    assert recommendations == [
        "Add new Section 8.18 Element 18: Supplier Management — defines vendor controls",
        "Add new Section 9.1 Annexure 1: Compliance Matrix",
    ]
    assert plan["selected_targets"] == ["NEW:8.18", "NEW:9.1"]


def test_missing_section_variants_are_routable() -> None:
    recommendations = _missing_section_recommendations(
        [
            "Sub-section 7.4: Document Hierarchy — define three tiers",
            "New Section 11.0: Emergency Response Integration — add interface",
            "Appendix F: SCE Register Template — add controlled table",
        ]
    )

    assert recommendations == [
        "Add new Section 7.4 Document Hierarchy — define three tiers",
        "Add new Section 11.0 Emergency Response Integration — add interface",
        "Appendix F: SCE Register Template — add controlled table",
    ]
