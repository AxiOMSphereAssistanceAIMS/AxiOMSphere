from __future__ import annotations

from types import SimpleNamespace

from ops.cyclic_doc_generation_pipeline import (
    _evaluate_cycle_hard_gate,
    _final_recommendation_lineage_status,
    _initial_recommendation_lineage_status,
)


def _gate(allowed: bool = True):
    return SimpleNamespace(allowed=allowed, reason="OK" if allowed else "BLOCKED")


def _structure(passed: bool = True):
    return SimpleNamespace(
        passed=passed,
        completeness_ratio=0.95 if passed else 0.29,
        threshold=0.90,
    )


def test_hard_gate_allows_only_complete_cycle() -> None:
    allowed, failures = _evaluate_cycle_hard_gate(
        gate=_gate(),
        struct_report=_structure(),
        audit_schema_passed=True,
        audit_quality_passed=True,
        audit_quality_failures=[],
        rec_lineage_passed=True,
        critical_regression=False,
    )
    assert allowed is True
    assert failures == []


def test_hard_gate_fails_closed_for_each_required_signal() -> None:
    allowed, failures = _evaluate_cycle_hard_gate(
        gate=_gate(False),
        struct_report=_structure(False),
        audit_schema_passed=False,
        audit_quality_passed=False,
        audit_quality_failures=[],
        rec_lineage_passed=False,
        critical_regression=True,
    )
    assert allowed is False
    assert failures == [
        "BLOCKED",
        "detailed_structure=29.0% < 90%",
        "claude_audit_schema=FAIL",
        "recommendation_lineage=FAIL",
        "critical_regression=true",
    ]


def test_hard_gate_rejects_valid_but_low_quality_audit() -> None:
    allowed, failures = _evaluate_cycle_hard_gate(
        gate=_gate(),
        struct_report=_structure(),
        audit_schema_passed=True,
        audit_quality_passed=False,
        audit_quality_failures=["claude_reference_gap=38.6% > 25%"],
        rec_lineage_passed=True,
        critical_regression=False,
    )
    assert allowed is False
    assert failures == ["claude_reference_gap=38.6% > 25%"]


def test_empty_repair_batch_is_not_a_lineage_failure() -> None:
    rec_lineage_passed = _initial_recommendation_lineage_status(
        cycle=2,
        applied_recommendations=[],
    )

    allowed, failures = _evaluate_cycle_hard_gate(
        gate=_gate(),
        struct_report=_structure(),
        audit_schema_passed=True,
        audit_quality_passed=True,
        audit_quality_failures=[],
        rec_lineage_passed=rec_lineage_passed,
        critical_regression=False,
    )

    assert allowed is True
    assert failures == []


def test_transactional_editor_verification_satisfies_lineage() -> None:
    recommendations = [
        "Add new Section 8.0 AIMS Elements",
        "Section 5.0: Expand stub content",
    ]

    assert _final_recommendation_lineage_status(
        applied_recommendations=recommendations,
        verified_recommendations=recommendations,
        text_verification_passed=False,
        pending_global=False,
        pending_unresolved=False,
        rolled_back=False,
    ) is True


def test_unresolved_editor_work_still_fails_lineage() -> None:
    recommendations = ["Add new Section 8.0 AIMS Elements"]

    assert _final_recommendation_lineage_status(
        applied_recommendations=recommendations,
        verified_recommendations=recommendations,
        text_verification_passed=False,
        pending_global=False,
        pending_unresolved=True,
        rolled_back=False,
    ) is False
