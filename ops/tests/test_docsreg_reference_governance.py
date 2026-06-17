"""
DOCSREG Reference Governance Gate — unit tests.

Validates deterministic fabricated-standards detection, classification,
gate decisions, repair plan generation, and strip utility.

Run:
  PYTHONPATH=/home/axi_omi_sphere/aims-workspace \
    python -m pytest ops/tests/test_docsreg_reference_governance.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ops.agents.skills.docsreg_reference_governance import (
    FABRICATED_STANDARDS_PATTERNS,
    REFERENCE_STANDARDS,
    ReferenceGateDecision,
    ReferenceGateResult,
    ReferenceOccurrence,
    ReferenceStatus,
    classify_references,
    extract_references,
    run_reference_governance_gate,
    select_reference_governance_recommendations,
    strip_fabricated_standards,
)


# ── Shared document builders ───────────────────────────────────────────────────

def _doc_with_iso_only() -> str:
    """Clean document referencing only ISO 55001."""
    return (
        "### 1.0 Scope\n\n"
        "This document is governed by ISO 55001:2014 requirements.\n"
        "Asset management per ISO 55001 is mandatory.\n"
    )


def _doc_with_api_ref(section: str = "6.2") -> str:
    return (
        f"### {section} Inspection\n\n"
        f"Inspections are conducted per API 580 risk-based inspection guidelines.\n"
    )


def _doc_with_nace_ref() -> str:
    return (
        "### 9.1 Corrosion Control\n\n"
        "Cathodic protection follows NACE SP0169 standard requirements.\n"
    )


def _doc_with_asme_ref() -> str:
    return (
        "### 5.3 Piping\n\n"
        "All piping systems are designed per ASME B31.3 process piping code.\n"
    )


def _clean_doc() -> str:
    """Document with no standards references at all."""
    return (
        "### 1.0 Introduction\n\n"
        "This section introduces the asset integrity management framework.\n"
        "The approach is consistent with best practices for industrial assets.\n"
    )


# ── Test 1: verified ISO reference passes ─────────────────────────────────────


class TestVerifiedIsoReferencePass:
    def test_verified_iso_reference_passes(self):
        result = run_reference_governance_gate(_doc_with_iso_only())
        assert result.decision == ReferenceGateDecision.PASS
        assert result.fabricated_count == 0
        assert result.verified_count >= 1


# ── Test 2: fabricated API ref blocks certification ───────────────────────────


class TestFabricatedApiRefBlocksCertification:
    def test_fabricated_api_ref_blocks_certification(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        assert result.decision == ReferenceGateDecision.CERTIFICATION_BLOCKER
        assert result.fabricated_count >= 1

    def test_api_580_appears_in_fabricated_references(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        ref_texts = [o.reference_text for o in result.fabricated_references]
        assert any("API" in t for t in ref_texts)

    def test_fabricated_ref_action_is_remove(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        for o in result.fabricated_references:
            assert o.action == "remove"

    def test_fabricated_ref_status_is_fabricated_suspected(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        for o in result.fabricated_references:
            assert o.status == ReferenceStatus.FABRICATED_SUSPECTED


# ── Test 3: fabricated NACE ref blocks certification ──────────────────────────


class TestFabricatedNaceRefBlocksCertification:
    def test_fabricated_nace_ref_blocks_certification(self):
        result = run_reference_governance_gate(_doc_with_nace_ref())
        assert result.decision == ReferenceGateDecision.CERTIFICATION_BLOCKER

    def test_nace_sp0169_detected(self):
        result = run_reference_governance_gate(_doc_with_nace_ref())
        ref_texts = [o.reference_text for o in result.fabricated_references]
        assert any("NACE" in t for t in ref_texts)


# ── Test 4: fabricated ASME ref blocks certification ──────────────────────────


class TestFabricatedAsmeRefBlocksCertification:
    def test_fabricated_asme_ref_blocks_certification(self):
        result = run_reference_governance_gate(_doc_with_asme_ref())
        assert result.decision == ReferenceGateDecision.CERTIFICATION_BLOCKER

    def test_asme_b313_detected(self):
        result = run_reference_governance_gate(_doc_with_asme_ref())
        ref_texts = [o.reference_text for o in result.fabricated_references]
        assert any("ASME" in t for t in ref_texts)


# ── Test 5: multiple fabricated refs in different sections ────────────────────


class TestMultipleFabricatedRefsInDifferentSections:
    def _doc(self) -> str:
        return (
            "### 6.2 Pressure Vessels\n\n"
            "Inspection intervals per API 510 requirements.\n\n"
            "### 9.1 Corrosion\n\n"
            "Cathodic protection per NACE SP0169 standard.\n"
        )

    def test_multiple_fabricated_refs_in_different_sections(self):
        result = run_reference_governance_gate(self._doc())
        assert result.fabricated_count >= 2

    def test_sections_with_fabricated_contains_both(self):
        result = run_reference_governance_gate(self._doc())
        assert "6.2" in result.sections_with_fabricated
        assert "9.1" in result.sections_with_fabricated

    def test_decision_is_certification_blocker(self):
        result = run_reference_governance_gate(self._doc())
        assert result.decision == ReferenceGateDecision.CERTIFICATION_BLOCKER


# ── Test 6: no references returns PASS ────────────────────────────────────────


class TestNoReferencesReturnsPass:
    def test_no_references_returns_pass(self):
        result = run_reference_governance_gate(_clean_doc())
        assert result.fabricated_count == 0
        assert result.decision in (
            ReferenceGateDecision.PASS,
            ReferenceGateDecision.BLOCKED_INSUFFICIENT_EVIDENCE,
        )

    def test_no_fabricated_means_no_blockers(self):
        result = run_reference_governance_gate(_clean_doc())
        assert result.certification_blockers == []

    def test_no_fabricated_means_empty_repair_plan(self):
        result = run_reference_governance_gate(_clean_doc())
        assert result.repair_plan == []


# ── Test 7: repair plan generated for fabricated refs ─────────────────────────


class TestRepairPlanGeneratedForFabricatedRefs:
    def test_repair_plan_generated_for_fabricated_refs(self):
        result = run_reference_governance_gate(_doc_with_api_ref(section="6.2"))
        assert len(result.repair_plan) >= 1

    def test_repair_plan_contains_section_id(self):
        result = run_reference_governance_gate(_doc_with_api_ref(section="6.2"))
        assert any("6.2" in item for item in result.repair_plan)

    def test_repair_plan_entries_are_strings(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        for item in result.repair_plan:
            assert isinstance(item, str)

    def test_repair_plan_mentions_reference_text(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        combined = " ".join(result.repair_plan)
        assert "API" in combined


# ── Test 8: certification blockers populated ──────────────────────────────────


class TestCertificationBlockersPopulated:
    def test_certification_blockers_populated(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        assert isinstance(result.certification_blockers, list)
        assert len(result.certification_blockers) >= 1

    def test_certification_blockers_are_strings(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        for blocker in result.certification_blockers:
            assert isinstance(blocker, str)

    def test_certification_blockers_mention_api(self):
        result = run_reference_governance_gate(_doc_with_api_ref())
        combined = " ".join(result.certification_blockers)
        assert "API" in combined


# ── Test 9: strip_fabricated_standards removes API lines ─────────────────────


class TestStripFabricatedStandardsRemovesApiLines:
    def test_strip_fabricated_standards_removes_api_lines(self):
        doc = (
            "### 6.2 Inspection\n\n"
            "Asset management principles apply.\n"
            "Inspections per API 580 risk-based guidelines.\n"
            "Further details follow.\n"
        )
        cleaned, removed = strip_fabricated_standards(doc)
        assert "API 580" not in cleaned
        assert len(removed) >= 1

    def test_removed_list_contains_api_line(self):
        doc = "Regular line.\nAPI 580 inspection frequency.\nAnother line.\n"
        _cleaned, removed = strip_fabricated_standards(doc)
        assert any("API" in r for r in removed)

    def test_cleaned_doc_preserves_non_fabricated_lines(self):
        doc = (
            "Asset management principles apply.\n"
            "Inspections per API 580.\n"
            "Further details follow.\n"
        )
        cleaned, _removed = strip_fabricated_standards(doc)
        assert "Asset management principles apply." in cleaned
        assert "Further details follow." in cleaned


# ── Test 10: strip preserves ISO lines ───────────────────────────────────────


class TestStripPreservesIsoLines:
    def test_strip_preserves_iso_lines(self):
        doc = (
            "Asset management per ISO 55001:2014.\n"
            "Requirements from ISO 55002:2018 apply.\n"
        )
        cleaned, removed = strip_fabricated_standards(doc)
        assert "ISO 55001:2014" in cleaned
        assert "ISO 55002:2018" in cleaned
        assert removed == []

    def test_strip_preserves_iso_9000_lines(self):
        doc = "Quality system based on ISO 9000 Series principles.\n"
        cleaned, removed = strip_fabricated_standards(doc)
        assert "ISO 9000" in cleaned
        assert removed == []


# ── Test 11: strip preserves headings with fabricated text ───────────────────


class TestStripPreservesHeadingsWithFabricatedText:
    def test_strip_preserves_headings_with_fabricated_text(self):
        doc = (
            "## 9.1 API Overview and Standards\n\n"
            "Body text mentioning API 510 directly.\n"
        )
        cleaned, removed = strip_fabricated_standards(doc)
        assert "## 9.1 API Overview and Standards" in cleaned

    def test_body_line_with_api_is_removed_but_heading_kept(self):
        doc = (
            "## 9.1 API Overview\n\n"
            "Per API 510 inspection code, intervals must be determined.\n"
        )
        cleaned, removed = strip_fabricated_standards(doc)
        assert "## 9.1 API Overview" in cleaned
        assert len(removed) >= 1
        assert any("API 510" in r for r in removed)


# ── Test 12: select_reference_governance_recommendations blocked ──────────────


class TestSelectReferenceGovernanceRecommendationsBlocked:
    def test_select_reference_governance_recommendations_blocked(self):
        result = select_reference_governance_recommendations(_doc_with_api_ref())
        assert result["status"] == "CERTIFICATION_BLOCKED"

    def test_blocked_result_has_expected_keys(self):
        result = select_reference_governance_recommendations(_doc_with_api_ref())
        expected_keys = {
            "decision", "fabricated_count", "verified_count",
            "sections_with_fabricated", "repair_plan",
            "certification_blockers", "status", "gate_version",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_blocked_decision_value_is_string(self):
        result = select_reference_governance_recommendations(_doc_with_api_ref())
        assert isinstance(result["decision"], str)
        assert result["decision"] == ReferenceGateDecision.CERTIFICATION_BLOCKER.value

    def test_gate_version_is_v1(self):
        result = select_reference_governance_recommendations(_doc_with_api_ref())
        assert result["gate_version"] == "v1"


# ── Test 13: select_reference_governance_recommendations pass ─────────────────


class TestSelectReferenceGovernanceRecommendationsPass:
    def test_select_reference_governance_recommendations_pass(self):
        result = select_reference_governance_recommendations(_clean_doc())
        assert result["status"] == "PASS"

    def test_pass_result_fabricated_count_is_zero(self):
        result = select_reference_governance_recommendations(_clean_doc())
        assert result["fabricated_count"] == 0

    def test_pass_result_empty_repair_plan(self):
        result = select_reference_governance_recommendations(_clean_doc())
        assert result["repair_plan"] == []

    def test_pass_result_empty_certification_blockers(self):
        result = select_reference_governance_recommendations(_clean_doc())
        assert result["certification_blockers"] == []

    def test_iso_only_doc_also_passes(self):
        result = select_reference_governance_recommendations(_doc_with_iso_only())
        assert result["status"] == "PASS"
        assert result["fabricated_count"] == 0
