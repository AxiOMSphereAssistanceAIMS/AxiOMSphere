"""
Stage 3 — Phase 2 nesting unit tests for docsreg_phase2_nesting.py

Validates the pure-structural sub-element injection pass that transforms
flat parent sections (8.4, 8.6, 8.9, 8.11, 8.21, 8.23) into nested
hierarchies matching the AIM-PFM reference document topology.

Run:
  PYTHONPATH=/home/axi_omi_sphere/aims-workspace \
    python -m pytest ops/tests/test_phase2_nesting.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ops.agents.skills.docsreg_phase2_nesting import (
    NESTING_TARGETS,
    NestingTarget,
    Phase2NestingApplicator,
    Phase2NestingResult,
    SubElement,
    apply_phase2_nesting,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _flat_doc(sections: list[tuple[str, str, str]]) -> str:
    """Build a minimal flat markdown document.

    Args:
        sections: list of (level_hashes, section_id, title) e.g. ("###", "8.4", "Leadership")
    Returns:
        Markdown string with one line per heading + stub body.
    """
    parts = []
    for hashes, sid, title in sections:
        parts.append(f"{hashes} {sid} {title}\n\nStub content for {sid}.\n")
    return "\n".join(parts)


def _count_headings(doc: str, prefix: str) -> int:
    """Count headings that start with `prefix` (e.g. '8.4.')."""
    return len(re.findall(r"^#{1,6}\s+" + re.escape(prefix), doc, re.MULTILINE))


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def simple_target() -> NestingTarget:
    """A minimal single-target for focused tests."""
    return NestingTarget(
        parent_id="8.4",
        sub_elements=[
            SubElement("8.4.1", "Visibility", "A" * 80),
            SubElement("8.4.2", "Proactive in Target Setting", "B" * 80),
        ],
    )


@pytest.fixture()
def flat_84_doc() -> str:
    """Document with flat section 8.4 (no sub-elements yet)."""
    return _flat_doc([("###", "8.4", "Leadership and Commitment"),
                      ("###", "8.5", "Something Else")])


@pytest.fixture()
def already_nested_84_doc() -> str:
    """Document where 8.4 already has 8.4.1."""
    return (
        "### 8.4 Leadership and Commitment\n\nBody text.\n\n"
        "#### 8.4.1 Visibility\n\nAlready here.\n\n"
        "### 8.5 Something Else\n\nMore.\n"
    )


@pytest.fixture()
def full_flat_doc() -> str:
    """Document with all 6 parent sections in flat form."""
    return _flat_doc([
        ("###", "8.4",  "Leadership and Commitment"),
        ("###", "8.5",  "Other"),
        ("###", "8.6",  "Organisation and Competency"),
        ("###", "8.7",  "Other2"),
        ("###", "8.9",  "Risk Identification"),
        ("###", "8.10", "Other3"),
        ("###", "8.11", "Asset Integrity in Projects"),
        ("###", "8.12", "Other4"),
        ("###", "8.21", "Integrity Management Auditing"),
        ("###", "8.22", "Other5"),
        ("###", "8.23", "Performance Improvement"),
        ("###", "8.24", "Other6"),
    ])


# ── Module-level smoke tests ───────────────────────────────────────────────────


class TestModuleConstants:
    def test_nesting_targets_count(self):
        """Default NESTING_TARGETS covers the 6 reference sections."""
        parent_ids = [t.parent_id for t in NESTING_TARGETS]
        assert set(parent_ids) == {"8.4", "8.6", "8.9", "8.11", "8.21", "8.23"}

    def test_sub_element_stubs_are_long_enough(self):
        """Every stub_body must be ≥60 chars to pass structure validation."""
        for target in NESTING_TARGETS:
            for sub in target.sub_elements:
                assert len(sub.stub_body) >= 60, (
                    f"{sub.section_id} stub_body is {len(sub.stub_body)} chars "
                    "(need ≥60 for validate_structure)"
                )

    def test_section_ids_are_dotted(self):
        """Sub-element section IDs follow X.Y.Z notation."""
        for target in NESTING_TARGETS:
            for sub in target.sub_elements:
                parts = sub.section_id.split(".")
                assert len(parts) == 3, (
                    f"Expected 3-part ID (e.g. 8.4.1) but got {sub.section_id!r}"
                )
                assert all(p.isdigit() for p in parts)

    def test_section_ids_match_parent(self):
        """Each sub-element ID starts with parent_id."""
        for target in NESTING_TARGETS:
            for sub in target.sub_elements:
                assert sub.section_id.startswith(target.parent_id + "."), (
                    f"{sub.section_id} does not start with {target.parent_id}."
                )

    def test_titles_are_nonempty(self):
        """Every sub-element has a non-empty title."""
        for target in NESTING_TARGETS:
            for sub in target.sub_elements:
                assert sub.title.strip(), f"{sub.section_id} has empty title"

    def test_expected_sub_element_counts(self):
        """Verify sub-element counts match AIM-PFM reference."""
        counts = {t.parent_id: len(t.sub_elements) for t in NESTING_TARGETS}
        assert counts["8.4"]  == 4
        assert counts["8.6"]  == 4
        assert counts["8.9"]  == 3
        assert counts["8.11"] == 7
        assert counts["8.21"] == 3
        assert counts["8.23"] == 2


# ── Injection tests ────────────────────────────────────────────────────────────


class TestSubElementInjection:
    def test_injects_sub_elements_into_flat_section(
        self, flat_84_doc: str, simple_target: NestingTarget
    ):
        """Flat 8.4 section receives 8.4.1 and 8.4.2 headings."""
        result = Phase2NestingApplicator().apply(flat_84_doc, targets=[simple_target])
        assert "8.4.1" in result.improved_doc
        assert "8.4.2" in result.improved_doc
        assert result.sections_expanded == ["8.4"]
        assert result.total_stubs_added == 2

    def test_already_nested_is_skipped(
        self, already_nested_84_doc: str, simple_target: NestingTarget
    ):
        """Section 8.4 already containing 8.4.1 is not modified."""
        before = already_nested_84_doc
        result = Phase2NestingApplicator().apply(before, targets=[simple_target])
        assert result.already_nested == ["8.4"]
        assert result.sections_expanded == []
        assert result.improved_doc == before

    def test_missing_parent_is_skipped(self, simple_target: NestingTarget):
        """If parent 8.4 is absent from the document, report as skipped."""
        doc = "### 9.0 Other Section\n\nSome content.\n"
        result = Phase2NestingApplicator().apply(doc, targets=[simple_target])
        assert result.nesting_skipped == ["8.4"]
        assert result.sections_expanded == []

    def test_sub_element_heading_level_matches_parent_plus_one(self, flat_84_doc: str):
        """Sub-elements get heading level = parent level + 1."""
        # flat_84_doc has ### (level 3) for 8.4 → expect #### (level 4) for 8.4.x
        target = NestingTarget(
            parent_id="8.4",
            sub_elements=[SubElement("8.4.1", "Test", "T" * 80)],
        )
        result = Phase2NestingApplicator().apply(flat_84_doc, targets=[target])
        assert "#### 8.4.1 Test" in result.improved_doc

    def test_heading_level_2_parent_gets_level_3_children(self):
        """Level-2 parent (##) gets level-3 (###) sub-elements."""
        doc = "## 8.4 Leadership\n\nContent.\n\n## 8.5 Other\n\nMore.\n"
        target = NestingTarget(
            parent_id="8.4",
            sub_elements=[SubElement("8.4.1", "Sub", "S" * 80)],
        )
        result = Phase2NestingApplicator().apply(doc, targets=[target])
        assert "### 8.4.1 Sub" in result.improved_doc

    def test_sub_elements_inserted_before_next_sibling(self, flat_84_doc: str):
        """Sub-elements appear BEFORE the 8.5 heading, not after."""
        target = NestingTarget(
            parent_id="8.4",
            sub_elements=[SubElement("8.4.1", "V", "V" * 80)],
        )
        result = Phase2NestingApplicator().apply(flat_84_doc, targets=[target])
        pos_sub = result.improved_doc.index("8.4.1")
        pos_next = result.improved_doc.index("### 8.5")
        assert pos_sub < pos_next, "Sub-element must come before the next section"

    def test_stub_body_appears_in_output(self, flat_84_doc: str):
        """The stub_body text is written into the injected section."""
        body = "X" * 80
        target = NestingTarget(
            parent_id="8.4",
            sub_elements=[SubElement("8.4.1", "Title", body)],
        )
        result = Phase2NestingApplicator().apply(flat_84_doc, targets=[target])
        assert body in result.improved_doc

    def test_parent_heading_content_preserved(self, flat_84_doc: str, simple_target: NestingTarget):
        """Parent heading line is unchanged after injection."""
        result = Phase2NestingApplicator().apply(flat_84_doc, targets=[simple_target])
        assert "### 8.4 Leadership and Commitment" in result.improved_doc

    def test_document_end_injection(self):
        """Parent at end of document (no next sibling) still gets sub-elements."""
        doc = "### 8.4 Leadership\n\nBody here.\n"
        target = NestingTarget(
            parent_id="8.4",
            sub_elements=[SubElement("8.4.1", "X", "Y" * 80)],
        )
        result = Phase2NestingApplicator().apply(doc, targets=[target])
        assert "8.4.1" in result.improved_doc
        assert result.sections_expanded == ["8.4"]

    def test_no_false_match_on_prefix_superset(self):
        """Section 8.40 must NOT be matched when targeting 8.4."""
        doc = "### 8.40 Something\n\nBody.\n"
        target = NestingTarget(
            parent_id="8.4",
            sub_elements=[SubElement("8.4.1", "V", "V" * 80)],
        )
        result = Phase2NestingApplicator().apply(doc, targets=[target])
        assert result.nesting_skipped == ["8.4"]
        assert "8.4.1" not in result.improved_doc


# ── Full-document multi-target tests ──────────────────────────────────────────


class TestFullDocumentNesting:
    def test_all_six_sections_expanded(self, full_flat_doc: str):
        """All 6 AIM-PFM sections are expanded in a single pass."""
        result = apply_phase2_nesting(full_flat_doc)
        assert set(result["sections_expanded"]) == {"8.4", "8.6", "8.9", "8.11", "8.21", "8.23"}
        assert result["nesting_skipped"] == []
        assert result["already_nested"] == []
        assert result["status"] == "EXPANDED"

    def test_total_stub_count(self, full_flat_doc: str):
        """Total stubs added = 4+4+3+7+3+2 = 23."""
        result = apply_phase2_nesting(full_flat_doc)
        assert result["total_stubs_added"] == 23

    def test_result_keys_complete(self, full_flat_doc: str):
        """Return dict has all 6 required keys."""
        result = apply_phase2_nesting(full_flat_doc)
        for key in ("improved_doc", "sections_expanded", "total_stubs_added",
                    "nesting_skipped", "already_nested", "status"):
            assert key in result, f"Missing key: {key!r}"

    def test_document_grows(self, full_flat_doc: str):
        """Improved doc must be longer than input."""
        result = apply_phase2_nesting(full_flat_doc)
        assert len(result["improved_doc"]) > len(full_flat_doc)

    def test_no_change_status_on_empty_doc(self):
        """Empty document returns status=NO_CHANGE."""
        result = apply_phase2_nesting("")
        assert result["status"] == "NO_CHANGE"
        assert result["total_stubs_added"] == 0
        assert len(result["nesting_skipped"]) == 6  # all 6 targets not found

    def test_idempotent_second_pass(self, full_flat_doc: str):
        """Running nesting twice produces no additional stubs on second pass."""
        first = apply_phase2_nesting(full_flat_doc)
        second = apply_phase2_nesting(first["improved_doc"])
        assert second["status"] == "NO_CHANGE"
        assert second["total_stubs_added"] == 0
        assert set(second["already_nested"]) == {"8.4", "8.6", "8.9", "8.11", "8.21", "8.23"}

    def test_all_sub_element_headings_present(self, full_flat_doc: str):
        """Spot-check: specific sub-element IDs appear in improved doc."""
        result = apply_phase2_nesting(full_flat_doc)
        doc = result["improved_doc"]
        spot_checks = [
            "8.4.1", "8.4.4",
            "8.6.1", "8.6.4",
            "8.9.1", "8.9.3",
            "8.11.1", "8.11.7",
            "8.21.1", "8.21.3",
            "8.23.1", "8.23.2",
        ]
        for sid in spot_checks:
            assert re.search(r"^#{1,6}\s+" + re.escape(sid) + r"\b", doc, re.MULTILINE), (
                f"Sub-element heading {sid} not found in improved doc"
            )

    def test_partial_doc_partial_expansion(self):
        """Document with only 8.4 and 8.11 expands only those two."""
        doc = _flat_doc([
            ("###", "8.4",  "Leadership"),
            ("###", "8.11", "Projects"),
        ])
        result = apply_phase2_nesting(doc)
        assert set(result["sections_expanded"]) == {"8.4", "8.11"}
        assert set(result["nesting_skipped"]) == {"8.6", "8.9", "8.21", "8.23"}
        assert result["total_stubs_added"] == 4 + 7  # 8.4 + 8.11

    def test_parent_text_intact_after_all_expansions(self, full_flat_doc: str):
        """Original parent section headings survive the multi-target pass."""
        result = apply_phase2_nesting(full_flat_doc)
        doc = result["improved_doc"]
        for sid in ("8.4", "8.6", "8.9", "8.11", "8.21", "8.23"):
            assert re.search(
                r"^#{1,6}\s+" + re.escape(sid) + r"(?=[\s\.\:])",
                doc,
                re.MULTILINE,
            ), f"Parent heading {sid} disappeared after nesting"


# ── Phase2NestingResult dataclass ─────────────────────────────────────────────


class TestPhase2NestingResult:
    def test_result_fields(self, full_flat_doc: str):
        """Phase2NestingResult exposes all expected fields."""
        result = Phase2NestingApplicator().apply(full_flat_doc)
        assert isinstance(result, Phase2NestingResult)
        assert isinstance(result.improved_doc, str)
        assert isinstance(result.sections_expanded, list)
        assert isinstance(result.total_stubs_added, int)
        assert isinstance(result.nesting_skipped, list)
        assert isinstance(result.already_nested, list)
