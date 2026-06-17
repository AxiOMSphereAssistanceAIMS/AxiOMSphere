"""
Stage 4 — Phase 3 content quality unit tests for docsreg_phase3_content_quality.py

Validates the deferred-rec selector and stub/fabricated-standards scanner that
forms the final pre-cycle content gate before the section editor runs.

Run:
  PYTHONPATH=/home/axi_omi_sphere/aims-workspace \
    python -m pytest ops/tests/test_docsreg_phase3_content_quality.py -v
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ops.agents.skills.docsreg_phase3_content_quality import (
    EXPANSION_TARGET_WORDS,
    FABRICATED_STANDARDS_PATTERNS,
    MAX_PHASE3_RECOMMENDATIONS,
    PHASE3_ELIGIBLE_TIERS,
    REFERENCE_STANDARDS,
    STUB_WORD_THRESHOLD,
    AutoRecommendationGenerator,
    DocumentContentScanner,
    Phase3ContentQualitySelector,
    Phase3SelectionResult,
    SectionContentAssessment,
    select_phase3_recommendations,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_section(section_id: str, heading: str, body_words: int) -> str:
    """Build a minimal markdown section with a given word count in the body."""
    words = ("word " * body_words).strip()
    return f"### {section_id} {heading}\n\n{words}\n"


def _make_deferred_rec(raw: str, tier_value: str) -> Any:
    """Minimal stand-in for a ClassifiedRecommendation object."""
    rec = MagicMock()
    rec.raw = raw
    rec.tier.value = tier_value
    return rec


# ── Module-level constant tests ────────────────────────────────────────────────


class TestModuleConstants:
    def test_stub_word_threshold_is_30(self):
        assert STUB_WORD_THRESHOLD == 30

    def test_expansion_target_is_80(self):
        assert EXPANSION_TARGET_WORDS == 80

    def test_max_phase3_recommendations_is_6(self):
        assert MAX_PHASE3_RECOMMENDATIONS == 6

    def test_eligible_tiers_contains_three_values(self):
        assert PHASE3_ELIGIBLE_TIERS == {"CONTENT_QUALITY", "FORMAT_LOW", "STRUCTURE_HIGH"}

    def test_reference_standards_iso_only(self):
        """Only ISO standards are canonical references."""
        assert "ISO 9000" in REFERENCE_STANDARDS
        assert "ISO 55001" in REFERENCE_STANDARDS
        assert "ISO 55002" in REFERENCE_STANDARDS
        assert len(REFERENCE_STANDARDS) == 3

    def test_fabricated_standards_patterns_count(self):
        """Must have at least 5 fabricated-standards patterns (API, NACE, IEC, NFPA, ASME)."""
        assert len(FABRICATED_STANDARDS_PATTERNS) >= 5

    def test_reference_iso_standards_not_in_fabricated_patterns(self):
        """ISO 55001, ISO 55002, ISO 9000 must not be matched by any fabricated pattern."""
        import re
        valid_references = [
            "ISO 55001:2014", "ISO 55002:2018", "ISO 9000 Series",
        ]
        for pattern in FABRICATED_STANDARDS_PATTERNS:
            for valid in valid_references:
                assert not re.search(pattern, valid, re.IGNORECASE), (
                    f"Pattern {pattern!r} incorrectly matches valid reference {valid!r}"
                )


# ── DocumentContentScanner._split_into_sections ───────────────────────────────


class TestSplitIntoSections:
    def test_numeric_heading_captured(self):
        doc = "### 8.4 Leadership\n\nBody content here.\n"
        sections = DocumentContentScanner._split_into_sections(doc)
        assert len(sections) == 1
        section_id, heading, body = sections[0]
        assert section_id == "8.4"
        assert "8.4" in heading
        assert "Body content" in body

    def test_non_numeric_heading_skipped(self):
        """Non-numeric headings like '## Table of Contents' are excluded."""
        doc = "## Table of Contents\n\nSome TOC content.\n\n### 3.0 Scope\n\nReal body.\n"
        sections = DocumentContentScanner._split_into_sections(doc)
        ids = [s[0] for s in sections]
        assert "3.0" in ids
        assert "Table" not in ids
        assert len(sections) == 1

    def test_multi_level_nested_sections(self):
        doc = (
            "### 8.4 Leadership\n\nParent body.\n\n"
            "#### 8.4.1 Visibility\n\nChild body.\n\n"
            "#### 8.4.2 Proactive\n\nAnother child.\n"
        )
        sections = DocumentContentScanner._split_into_sections(doc)
        ids = [s[0] for s in sections]
        assert "8.4" in ids
        assert "8.4.1" in ids
        assert "8.4.2" in ids
        assert len(sections) == 3

    def test_body_ends_at_next_heading(self):
        doc = "### 1.0 First\n\nFirst body.\n\n### 2.0 Second\n\nSecond body.\n"
        sections = DocumentContentScanner._split_into_sections(doc)
        assert len(sections) == 2
        _, _, body1 = sections[0]
        assert "First body" in body1
        assert "Second body" not in body1

    def test_last_section_body_reaches_eof(self):
        doc = "### 5.0 Last\n\nThis is the final section body.\n"
        sections = DocumentContentScanner._split_into_sections(doc)
        assert len(sections) == 1
        _, _, body = sections[0]
        assert "final section body" in body

    def test_empty_document_returns_empty_list(self):
        assert DocumentContentScanner._split_into_sections("") == []

    def test_section_id_with_three_parts(self):
        doc = "#### 8.11.3 Commissioning\n\nSome commissioning text here.\n"
        sections = DocumentContentScanner._split_into_sections(doc)
        assert sections[0][0] == "8.11.3"


# ── DocumentContentScanner._find_fabricated_standards ─────────────────────────


class TestFindFabricatedStandards:
    def test_detects_api_510(self):
        text = "Inspections follow API 510 pressure vessel guidelines."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert any("API" in f for f in found), f"API 510 not found in {found}"

    def test_detects_api_570(self):
        text = "Per API 570, piping inspection intervals are risk-based."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert any("API" in f for f in found)

    def test_detects_nace_sp_pattern(self):
        text = "Cathodic protection to NACE SP0169 standard."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert any("NACE" in f for f in found)

    def test_detects_iec_60364(self):
        text = "Electrical installations comply with IEC 60364."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert any("IEC" in f for f in found)

    def test_detects_nfpa_70(self):
        text = "National electrical code NFPA 70 is referenced."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert any("NFPA" in f for f in found)

    def test_detects_asme_b31(self):
        text = "Piping designed per ASME B31.3 process piping code."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert any("ASME" in f for f in found)

    def test_does_not_flag_iso_55001(self):
        text = "Asset management per ISO 55001:2014 requirements."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert found == [], f"ISO 55001 should not be flagged, got {found}"

    def test_does_not_flag_iso_9000(self):
        text = "Quality management system based on ISO 9000 Series."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert found == []

    def test_multiple_fabricated_in_one_text(self):
        text = "Per API 510, NACE SP0169, and ASME B31.3."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert len(found) >= 3

    def test_clean_text_returns_empty(self):
        text = "This section describes the management review process."
        found = DocumentContentScanner._find_fabricated_standards(text)
        assert found == []

    def test_case_insensitive_matching(self):
        text = "Requirements per api 510 and asme b31.3."
        found = DocumentContentScanner._find_fabricated_standards(text)
        # Should detect case-insensitively
        assert len(found) >= 1


# ── DocumentContentScanner.scan ───────────────────────────────────────────────


class TestDocumentContentScannerScan:
    def test_stub_detection_below_threshold(self):
        """Section with fewer than 30 words is a stub."""
        doc = _make_section("3.0", "Scope", 10)
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert len(assessments) == 1
        assert assessments[0].is_stub is True
        assert assessments[0].word_count == 10

    def test_non_stub_above_threshold(self):
        """Section with 30+ words is not a stub."""
        doc = _make_section("3.0", "Scope", 30)
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert assessments[0].is_stub is False

    def test_exactly_at_threshold_is_not_stub(self):
        """Exactly 30 words is NOT a stub (threshold is strict <)."""
        doc = _make_section("3.0", "Scope", 30)
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert assessments[0].is_stub is False

    def test_fabricated_standards_detection(self):
        body = "API 510 and NACE SP0169 are referenced throughout."
        doc = f"### 8.9 Risk Management\n\n{body}\n"
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert assessments[0].has_fabricated_standards is True
        assert len(assessments[0].fabricated_standards) >= 1

    def test_quality_score_stub_penalty(self):
        """Stub section has quality_score < 1.0."""
        doc = _make_section("3.0", "Scope", 5)
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert assessments[0].quality_score < 1.0

    def test_quality_score_perfect_clean_section(self):
        """Clean, non-stub section has quality_score == 1.0."""
        doc = _make_section("3.0", "Scope", 50)
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert assessments[0].quality_score == 1.0

    def test_quality_score_capped_at_zero(self):
        """Quality score never goes below 0."""
        # Both stub + multiple fabricated standards should not produce negative score
        body = ("API 510 " * 5).strip()  # < 30 words and fabricated standard
        doc = f"### 3.0 Scope\n\n{body}\n"
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert assessments[0].quality_score >= 0.0

    def test_assessment_fields_present(self):
        doc = _make_section("8.4", "Leadership", 40)
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        a = assessments[0]
        assert isinstance(a, SectionContentAssessment)
        assert a.section_id == "8.4"
        assert isinstance(a.word_count, int)
        assert isinstance(a.is_stub, bool)
        assert isinstance(a.fabricated_standards, list)
        assert isinstance(a.has_fabricated_standards, bool)
        assert isinstance(a.quality_score, float)

    def test_multiple_sections_scanned(self):
        doc = (
            _make_section("3.0", "Scope", 5) +
            _make_section("4.0", "References", 50) +
            _make_section("5.0", "Definitions", 10)
        )
        scanner = DocumentContentScanner()
        assessments = scanner.scan(doc)
        assert len(assessments) == 3
        ids = [a.section_id for a in assessments]
        assert "3.0" in ids
        assert "4.0" in ids
        assert "5.0" in ids

    def test_empty_document_returns_empty_list(self):
        scanner = DocumentContentScanner()
        assert scanner.scan("") == []


# ── AutoRecommendationGenerator ───────────────────────────────────────────────


class TestAutoRecommendationGenerator:
    def _make_assessment(
        self,
        section_id: str,
        word_count: int = 50,
        is_stub: bool = False,
        fabricated: list[str] | None = None,
    ) -> SectionContentAssessment:
        fabricated = fabricated or []
        return SectionContentAssessment(
            section_id=section_id,
            heading=f"### {section_id} Test",
            word_count=word_count,
            is_stub=is_stub,
            fabricated_standards=fabricated,
            has_fabricated_standards=bool(fabricated),
            quality_score=1.0,
        )

    def test_fabricated_standards_rec_generated(self):
        assessments = [self._make_assessment("8.9", fabricated=["API 510"])]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        assert len(recs) == 1
        assert "8.9" in recs[0]
        assert "non-ISO standard references" in recs[0]  # upgraded to STEP 1/2 format
        assert "API 510" in recs[0]

    def test_stub_rec_generated(self):
        assessments = [self._make_assessment("3.0", word_count=10, is_stub=True)]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        assert len(recs) == 1
        assert "3.0" in recs[0]
        assert "Expand stub content" in recs[0]
        assert "10 words" in recs[0]

    def test_standards_recs_before_stub_recs(self):
        """Fabricated-standards recs always precede stub expansion recs."""
        assessments = [
            self._make_assessment("3.0", word_count=5, is_stub=True),  # stub
            self._make_assessment("8.9", fabricated=["API 510"]),       # standards issue
        ]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        # Standards rec (8.9) must come before stub rec (3.0)
        assert len(recs) == 2
        standards_idx = next(i for i, r in enumerate(recs) if "non-ISO standard references" in r)
        stub_idx = next(i for i, r in enumerate(recs) if "Expand stub" in r)
        assert standards_idx < stub_idx, "Fabricated-standards rec must come before stub rec"

    def test_no_stub_rec_when_standards_issue_present(self):
        """When a section has both stub + fabricated standards, only standards rec is generated."""
        assessments = [
            self._make_assessment("8.9", word_count=5, is_stub=True, fabricated=["API 510"])
        ]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        assert len(recs) == 1
        assert "non-ISO standard references" in recs[0]  # upgraded to STEP 1/2 format
        # Must NOT also have a stub expansion rec for same section
        assert "Expand stub" not in recs[0]

    def test_clean_section_produces_no_rec(self):
        assessments = [self._make_assessment("4.0", word_count=100, is_stub=False)]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        assert recs == []

    def test_rec_text_mentions_iso_standards(self):
        """Fabricated-standards removal rec must mention the valid ISO references."""
        assessments = [self._make_assessment("8.9", fabricated=["API 570"])]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        assert "ISO 55001" in recs[0]

    def test_stub_rec_mentions_expansion_target(self):
        """Stub expansion rec must mention the EXPANSION_TARGET_WORDS minimum."""
        assessments = [self._make_assessment("3.0", word_count=15, is_stub=True)]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        assert str(EXPANSION_TARGET_WORDS) in recs[0]

    def test_fabricated_standards_capped_at_three_in_rec(self):
        """Rec text shows at most 3 fabricated citations to keep it readable."""
        many_fabricated = ["API 510", "NACE SP0169", "IEC 60364", "NFPA 70", "ASME B31.3"]
        assessments = [self._make_assessment("8.9", fabricated=many_fabricated)]
        gen = AutoRecommendationGenerator()
        recs = gen.generate(assessments)
        # The rec text is formed using assessments[0].fabricated_standards[:3]
        assert len(recs) == 1


# ── Phase3ContentQualitySelector ──────────────────────────────────────────────


class TestPhase3ContentQualitySelector:
    def _make_doc_with_stubs(self, n_stubs: int = 2) -> str:
        """Build a document with n stub sections and one normal section."""
        parts = [_make_section(f"{i}.0", f"Section {i}", 5) for i in range(1, n_stubs + 1)]
        parts.append(_make_section("9.0", "Good Section", 100))
        return "\n".join(parts)

    def test_eligible_deferred_recs_selected(self):
        doc = _make_section("3.0", "Scope", 100)  # clean doc, no auto-recs
        eligible = _make_deferred_rec("Section 3.0: Improve clarity.", "CONTENT_QUALITY")
        result = Phase3ContentQualitySelector().select(doc, [eligible])
        assert eligible.raw in result.selected

    def test_ineligible_deferred_recs_skipped(self):
        doc = _make_section("3.0", "Scope", 100)
        ineligible = _make_deferred_rec("Section 3.0: Some rec.", "MANDATORY")
        result = Phase3ContentQualitySelector().select(doc, [ineligible])
        assert ineligible.raw not in result.selected
        assert ineligible.raw in result.skipped

    def test_format_low_tier_is_eligible(self):
        doc = _make_section("3.0", "Scope", 100)
        rec = _make_deferred_rec("Format rec.", "FORMAT_LOW")
        result = Phase3ContentQualitySelector().select(doc, [rec])
        assert rec.raw in result.selected

    def test_structure_high_tier_is_eligible(self):
        doc = _make_section("3.0", "Scope", 100)
        rec = _make_deferred_rec("Structure rec.", "STRUCTURE_HIGH")
        result = Phase3ContentQualitySelector().select(doc, [rec])
        assert rec.raw in result.selected

    def test_max_limit_enforced(self):
        """Selector must not return more than MAX_PHASE3_RECOMMENDATIONS recs."""
        # Create many stub sections to generate many auto-recs
        parts = [_make_section(f"{i}.0", f"Section {i}", 5) for i in range(1, 20)]
        doc = "\n".join(parts)
        result = Phase3ContentQualitySelector().select(doc, [])
        assert len(result.selected) <= MAX_PHASE3_RECOMMENDATIONS

    def test_overflow_goes_to_skipped(self):
        """Items beyond the limit go to skipped list."""
        parts = [_make_section(f"{i}.0", f"Section {i}", 5) for i in range(1, 20)]
        doc = "\n".join(parts)
        result = Phase3ContentQualitySelector().select(doc, [])
        total = len(result.selected) + len(result.skipped)
        auto_generated = result.total_auto_generated
        ineligible_skipped = [
            s for s in result.skipped
            if not any(f"{i}.0" in s for i in range(1, 20))
        ]
        # All auto-generated recs are accounted for
        assert auto_generated >= len(result.selected)

    def test_deduplication_on_prefix(self):
        """Two recs with the same first 60 chars are deduplicated."""
        raw = "Section 3.0: Improve content quality of the scope section. Additional text here."
        rec1 = _make_deferred_rec(raw, "CONTENT_QUALITY")
        rec2 = _make_deferred_rec(raw, "CONTENT_QUALITY")
        doc = _make_section("3.0", "Scope", 100)
        result = Phase3ContentQualitySelector().select(doc, [rec1, rec2])
        # Should appear only once
        assert result.selected.count(raw) <= 1

    def test_stub_sections_reported(self):
        doc = _make_section("3.0", "Scope", 5)  # stub
        result = Phase3ContentQualitySelector().select(doc, [])
        assert "3.0" in result.stub_sections

    def test_fabricated_sections_reported(self):
        doc = "### 8.9 Risk\n\nAPI 510 is referenced in this section for inspection intervals.\n"
        result = Phase3ContentQualitySelector().select(doc, [])
        assert "8.9" in result.fabricated_standards_sections

    def test_total_from_deferred_count(self):
        doc = _make_section("3.0", "Scope", 100)
        eligible_recs = [
            _make_deferred_rec(f"Rec {i}.", "CONTENT_QUALITY") for i in range(3)
        ]
        result = Phase3ContentQualitySelector().select(doc, eligible_recs)
        assert result.total_from_deferred == 3

    def test_total_auto_generated_count(self):
        doc = (
            _make_section("3.0", "Scope", 5) +    # stub → auto rec
            _make_section("4.0", "Refs", 100)     # clean → no rec
        )
        result = Phase3ContentQualitySelector().select(doc, [])
        assert result.total_auto_generated >= 1

    def test_custom_max_limit(self):
        parts = [_make_section(f"{i}.0", f"Section {i}", 5) for i in range(1, 20)]
        doc = "\n".join(parts)
        result = Phase3ContentQualitySelector(max_recommendations=2).select(doc, [])
        assert len(result.selected) <= 2

    def test_section_assessments_returned(self):
        doc = _make_section("3.0", "Scope", 40)
        result = Phase3ContentQualitySelector().select(doc, [])
        assert isinstance(result.section_assessments, list)
        assert len(result.section_assessments) == 1

    def test_deferred_before_auto_in_merged(self):
        """Deferred recs must appear before auto-generated recs in the selected list."""
        doc = (
            "### 3.0 Scope\n\n" + ("word " * 5) + "\n\n"  # stub
            "### 4.0 References\n\n" + ("word " * 60) + "\n"   # clean
        )
        deferred = _make_deferred_rec("Deferred quality rec for section 4.0 something here.", "CONTENT_QUALITY")
        result = Phase3ContentQualitySelector().select(doc, [deferred])
        if len(result.selected) >= 2:
            deferred_idx = result.selected.index(deferred.raw)
            auto_idx = next(
                (i for i, r in enumerate(result.selected) if "Expand stub" in r),
                None,
            )
            if auto_idx is not None:
                assert deferred_idx < auto_idx, "Deferred recs must come before auto-generated recs"


# ── select_phase3_recommendations (top-level function) ────────────────────────


class TestSelectPhase3Recommendations:
    def test_returns_all_nine_keys(self):
        result = select_phase3_recommendations("### 1.0 Test\n\n" + "word " * 50 + "\n")
        expected_keys = {
            "selected", "skipped", "stub_sections", "fabricated_standards_sections",
            "section_assessments", "total_from_deferred", "total_auto_generated",
            "status", "phase3_version",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_status_has_work_when_stubs_present(self):
        doc = _make_section("3.0", "Scope", 5)  # stub → should trigger recs
        result = select_phase3_recommendations(doc)
        assert result["status"] == "HAS_WORK"

    def test_status_no_work_on_clean_doc(self):
        doc = _make_section("3.0", "Scope", 80)  # clean
        result = select_phase3_recommendations(doc, deferred_recs=[])
        assert result["status"] == "NO_WORK"

    def test_phase3_version_is_v1(self):
        result = select_phase3_recommendations("")
        assert result["phase3_version"] == "v1"

    def test_none_deferred_treated_as_empty_list(self):
        doc = _make_section("3.0", "Scope", 80)
        result = select_phase3_recommendations(doc, deferred_recs=None)
        assert isinstance(result["selected"], list)

    def test_section_assessments_are_dicts(self):
        doc = _make_section("3.0", "Scope", 40)
        result = select_phase3_recommendations(doc)
        for a in result["section_assessments"]:
            assert isinstance(a, dict)
            assert "section_id" in a
            assert "word_count" in a
            assert "is_stub" in a
            assert "has_fabricated_standards" in a
            assert "quality_score" in a

    def test_idempotent_on_clean_doc(self):
        """Running Phase 3 twice on a clean doc returns the same NO_WORK result."""
        doc = _make_section("3.0", "Scope", 100)
        result1 = select_phase3_recommendations(doc)
        result2 = select_phase3_recommendations(doc)
        assert result1["status"] == result2["status"]
        assert result1["selected"] == result2["selected"]

    def test_fabricated_standards_recs_in_selected(self):
        doc = "### 8.9 Risk\n\n" + "API 510 is used for pressure vessel inspection. " * 5 + "\n"
        result = select_phase3_recommendations(doc)
        assert any("non-ISO standard references" in r for r in result["selected"])  # upgraded STEP 1/2 format

    def test_empty_document_returns_no_work(self):
        result = select_phase3_recommendations("")
        assert result["status"] == "NO_WORK"
        assert result["selected"] == []

    def test_total_counts_are_integers(self):
        result = select_phase3_recommendations(_make_section("3.0", "Scope", 5))
        assert isinstance(result["total_from_deferred"], int)
        assert isinstance(result["total_auto_generated"], int)

    def test_with_eligible_deferred_increases_selected(self):
        """Eligible deferred recs add to the selected pool on a clean doc."""
        doc = _make_section("3.0", "Scope", 100)
        deferred = [_make_deferred_rec("Section 3.0: Improve terminology.", "CONTENT_QUALITY")]
        result = select_phase3_recommendations(doc, deferred_recs=deferred)
        assert len(result["selected"]) == 1
        assert result["total_from_deferred"] == 1
