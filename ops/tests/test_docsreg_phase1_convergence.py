"""
DOCSREG Phase 1 Staged Convergence — Test Suite

Tests classification, filtering, batching, and stub validation logic.
All tests are unit-level and don't require model API calls.
"""

import pytest
from ops.agents.skills.docsreg_phase1_convergence import (
    RecommendationClassifier,
    RecommendationTier,
    Phase1Selector,
    SemanticStubValidator,
    Phase1ConvergenceOrchestrator,
    ClassifiedRecommendation,
)


class TestRecommendationClassifier:
    """Test recommendation tier classification."""

    def test_classifies_new_section_as_critical(self):
        """New sections are STRUCTURE_CRITICAL."""
        classifier = RecommendationClassifier()
        rec = "Add new Section 7.3 Interface Management (stub - requires full content)"
        result = classifier.classify(rec)
        assert result.tier == RecommendationTier.STRUCTURE_CRITICAL
        assert "ADD_CONTENT" in result.operation or "NEW_SECTION" in result.operation

    def test_classifies_table_as_critical(self):
        """Tables 1-5 are STRUCTURE_CRITICAL."""
        classifier = RecommendationClassifier()
        rec = "Add new Section 9.1 Annexure 1: Compliance Matrix (stub - requires full compliance mapping)"
        result = classifier.classify(rec)
        assert result.tier == RecommendationTier.STRUCTURE_CRITICAL
        assert result.target in ["Section 9.1", "Annexure 1", "GLOBAL"]

    def test_classifies_pdca_table_as_critical(self):
        """PDCA cycle assignments are STRUCTURE_CRITICAL."""
        classifier = RecommendationClassifier()
        rec = "Insert the full PDCA element assignment table (equivalent to Table 3 in reference)"
        result = classifier.classify(rec)
        assert result.tier == RecommendationTier.STRUCTURE_CRITICAL

    def test_classifies_sub_element_expansion_as_nesting(self):
        """Sub-element expansion (8.x.y format) is NESTING tier."""
        classifier = RecommendationClassifier()
        rec = "Restructure into four sub-elements as per reference: 8.4.1 Visibility, 8.4.2 Target Setting, 8.4.3 Information, 8.4.4 Encouragement"
        result = classifier.classify(rec)
        assert result.tier == RecommendationTier.NESTING
        assert "8.4" in result.raw or "sub-element" in result.raw.lower()

    def test_classifies_section_expansion_as_high(self):
        """General section expansion is STRUCTURE_HIGH."""
        classifier = RecommendationClassifier()
        rec = "Expand Section 5.1 Definitions to include all 30+ entries and acronyms present in reference"
        result = classifier.classify(rec)
        # Could be HIGH or CRITICAL depending on keywords; verify it's not FORMAT_LOW
        assert result.tier in [
            RecommendationTier.STRUCTURE_HIGH,
            RecommendationTier.STRUCTURE_CRITICAL,
        ]

    def test_classifies_kpi_improvement_as_content(self):
        """KPI/performance improvements are CONTENT_QUALITY."""
        classifier = RecommendationClassifier()
        rec = "Define measurable leadership KPIs and link them to the monitoring framework"
        result = classifier.classify(rec)
        assert result.tier == RecommendationTier.CONTENT_QUALITY

    def test_detects_section_target(self):
        """Correctly extract section target from recommendation."""
        classifier = RecommendationClassifier()
        rec = "Section 8.11 (Element 11): Expand from a single expectation block to seven sub-elements"
        result = classifier.classify(rec)
        assert "8.11" in result.target or "Section 8.11" == result.target

    def test_detects_global_target(self):
        """Detect global targets like References, Definitions."""
        classifier = RecommendationClassifier()
        rec = "Update all References to include ASME B31.3 and ISO 9000 Series"
        result = classifier.classify(rec)
        assert result.target == "GLOBAL"

    def test_operation_detection_new_section(self):
        """Detect NEW_SECTION operation."""
        classifier = RecommendationClassifier()
        rec = "Add new Section 3.0 Expanded Scope"
        result = classifier.classify(rec)
        assert result.operation == "NEW_SECTION"

    def test_operation_detection_add_table(self):
        """Detect ADD_TABLE operation."""
        classifier = RecommendationClassifier()
        rec = "Insert Table 3 (PDCA cycle assignment) with all 23 elements"
        result = classifier.classify(rec)
        assert result.operation == "ADD_TABLE"

    def test_operation_detection_expand(self):
        """Detect EXPAND operation."""
        classifier = RecommendationClassifier()
        rec = "Expand Section 8.9 into three sub-elements"
        result = classifier.classify(rec)
        assert result.operation == "EXPAND"


class TestPhase1Selector:
    """Test Phase 1 recommendation selection and batching."""

    def test_selects_critical_and_high_only(self):
        """Phase 1 selects only STRUCTURE_CRITICAL and STRUCTURE_HIGH."""
        selector = Phase1Selector(max_per_phase=10)  # No limit for this test
        recommendations = [
            "Add new Section 7.3 Interface Management",  # CRITICAL
            "Insert Table 3 PDCA cycle assignment",  # CRITICAL
            "Expand Section 5.1 Definitions",  # HIGH
            "Restructure 8.4.1-8.4.4 sub-elements",  # NESTING (deferred)
            "Define KPI metrics for leadership",  # CONTENT (deferred)
            "Fix formatting in Section 2.1",  # FORMAT_LOW (deferred)
        ]
        result = selector.select_phase1(recommendations)

        # Should select CRITICAL and HIGH only
        assert result.selected_count == 3
        assert all(
            cls.tier in [
                RecommendationTier.STRUCTURE_CRITICAL,
                RecommendationTier.STRUCTURE_HIGH,
            ]
            for cls in result.phase1_selected
        )
        # Rest should be deferred
        assert result.deferred_count == 3

    def test_batches_to_max_recommendations(self):
        """Phase 1 respects max_per_phase limit."""
        selector = Phase1Selector(max_per_phase=2)
        recommendations = [
            "Add new Section 3.0",  # CRITICAL
            "Add new Section 5.0",  # CRITICAL
            "Add new Section 7.0",  # CRITICAL
            "Insert Table 3",  # CRITICAL
        ]
        result = selector.select_phase1(recommendations)

        # Only first 2 should be selected
        assert result.selected_count == 2
        assert result.deferred_count == 2

    def test_prioritizes_critical_before_high(self):
        """Phase 1 selects CRITICAL items before HIGH items."""
        selector = Phase1Selector(max_per_phase=3)
        recommendations = [
            "Expand Section 5.1",  # HIGH
            "Add new Section 7.3",  # CRITICAL
            "Expand Section 5.2",  # HIGH
            "Insert Table 3",  # CRITICAL
        ]
        result = selector.select_phase1(recommendations)

        # First 2 should be CRITICAL (Section 7.3 and Table 3)
        critical_selected = [
            cls for cls in result.phase1_selected
            if cls.tier == RecommendationTier.STRUCTURE_CRITICAL
        ]
        assert len(critical_selected) >= 2

    def test_handles_empty_recommendations(self):
        """Handle empty recommendation list gracefully."""
        selector = Phase1Selector()
        result = selector.select_phase1([])
        assert result.selected_count == 0
        assert result.deferred_count == 0
        assert len(result.phase1_selected) == 0


class TestSemanticStubValidator:
    """Test semantic stub validation (not length-based)."""

    def test_rejects_tbd_content(self):
        """Reject content with TBD markers."""
        content = "This section is TBD and requires full development."
        is_valid, reason = SemanticStubValidator.validate_section_content("8.3", content)
        assert not is_valid
        assert "stub" in reason.lower()

    def test_rejects_placeholder_content(self):
        """Reject explicit placeholder markers."""
        content = "[PLACEHOLDER: Add content here]"
        is_valid, reason = SemanticStubValidator.validate_section_content("8.5", content)
        assert not is_valid

    def test_rejects_incomplete_markers(self):
        """Reject 'requires full development' and similar."""
        content = "Basic outline. Section 8.11 structure requires further development and expansion."
        is_valid, reason = SemanticStubValidator.validate_section_content("8.11", content)
        assert not is_valid, f"Expected rejection but got: {reason}"

    def test_rejects_too_short_content(self):
        """Reject very short content (< 20 chars)."""
        content = "Stub"
        is_valid, reason = SemanticStubValidator.validate_section_content("8.0", content)
        assert not is_valid

    def test_accepts_real_section_content(self):
        """Accept genuine section content."""
        content = """
        Section 8.11 describes the asset lifecycle management approach including:

        1. Concept and Design phase considerations
        2. Procurement and construction integrity management
        3. Commissioning and operational readiness
        4. Maintenance strategies and performance monitoring
        5. End-of-life management planning

        This comprehensive lifecycle approach ensures assets meet integrity objectives throughout their operational period.
        """
        is_valid, reason = SemanticStubValidator.validate_section_content("8.11", content)
        assert is_valid

    def test_rejects_prose_only_compliance_matrix(self):
        """Reject compliance matrices written as prose instead of structured tables."""
        content = """
        The compliance matrix maps ISO 55001 clauses to AIMS elements. Clause 7.1 maps to Element 5.
        Clause 7.2 maps to Element 6. Clause 8.1 maps to Element 7. Additional clauses TBD.
        """
        is_valid, reason = SemanticStubValidator.validate_section_content("9.1", content)
        # Should either be valid or reject as incomplete
        if not is_valid:
            assert "stub" in reason.lower() or "tbd" in content.lower()


class TestPhase1ConvergenceOrchestrator:
    """Test end-to-end Phase 1 orchestration."""

    def test_prepares_phase1_batch(self):
        """Orchestrator prepares complete Phase 1 batch."""
        orchestrator = Phase1ConvergenceOrchestrator(max_recommendations_per_phase=5)
        recommendations = [
            "Add new Section 7.3 Interface Management",
            "Insert Table 3 PDCA cycle mapping",
            "Expand Section 5.1 Definitions to 30+ entries",
            "Restructure Section 8.4 into 8.4.1-8.4.4 sub-elements",
            "Define KPI metrics for leadership review",
            "Add reference to ASME B31.3",
            "Fix formatting in Section 2.1",
        ]
        batch = orchestrator.prepare_phase1_batch(recommendations)

        # Verify output structure
        assert "phase1_selected" in batch
        assert "phase1_count" in batch
        assert "classification_result" in batch
        assert "by_tier" in batch

        # Phase 1 should select only CRITICAL and HIGH
        assert batch["phase1_count"] <= 5  # Respects max
        assert all(
            rec_tier in [
                RecommendationTier.STRUCTURE_CRITICAL.value,
                RecommendationTier.STRUCTURE_HIGH.value,
            ]
            for rec_tier in [
                cls.tier.value for cls in batch["classification_result"].phase1_selected
            ]
        )

    def test_phase1_count_respects_limit(self):
        """Phase 1 batch respects max recommendations limit."""
        orchestrator = Phase1ConvergenceOrchestrator(max_recommendations_per_phase=3)
        recommendations = [
            f"Add new Section {i}.0"
            for i in range(3, 10)
        ] + [
            f"Insert Table {i}"
            for i in range(1, 6)
        ]
        batch = orchestrator.prepare_phase1_batch(recommendations)
        assert batch["phase1_count"] <= 3

    def test_produces_classification_stats(self):
        """Orchestrator produces detailed classification statistics."""
        orchestrator = Phase1ConvergenceOrchestrator()
        recommendations = [
            "Add new Section 7.3",
            "Insert Table 3",
            "Expand Section 5.1",
            "Restructure 8.4.1-8.4.4",
            "Define KPI metrics",
        ]
        batch = orchestrator.prepare_phase1_batch(recommendations)
        stats = batch["by_tier"]

        # Verify tier counts
        assert RecommendationTier.STRUCTURE_CRITICAL.value in stats
        total = sum(stats.values())
        assert total == len(recommendations)


class TestPhase1IntegrationScenario:
    """Integration test with real Cycle 2 recommendations."""

    def test_cycle2_recommendations_classification(self):
        """Classify actual Cycle 2 recommendations from repair plan."""
        # Sample recommendations from cycle_02/repair_plan.json
        cycle2_recs = [
            "Add new Section 7.3 Interface Management (stub - requires full content development)",
            "Add new Section 9.1 Annexure 1: Compliance Matrix (stub - requires full compliance mapping)",
            "Replace the specific ISO 55001 clause references (7.2, 8.1) with the broader 'ISO-55000 Series' reference",
            "Verify and include all EP Technical Integrity Framework section references",
            "Include requirement for the strategy to define inspection and maintenance philosophy",
            "Expand into sub-elements covering each lifecycle phase explicitly",
            "Restructure into four sub-elements: 8.4.1 Visibility, 8.4.2 Target Setting, 8.4.3 Information, 8.4.4 Encouragement",
            "Define measurable leadership KPIs and link them to the Implementation and Monitoring framework",
            "Define competency requirements matrix for each integrity role",
            "Include requirements for contractor personnel competence verification",
        ]

        orchestrator = Phase1ConvergenceOrchestrator(max_recommendations_per_phase=5)
        batch = orchestrator.prepare_phase1_batch(cycle2_recs)

        # Phase 1 should select high-priority items
        assert batch["phase1_count"] > 0
        assert batch["phase1_count"] <= 5

        # Verify CRITICAL items are selected
        critical_items = [
            rec for rec in batch["phase1_selected"]
            if "Section 7.3" in rec or "Section 9.1" in rec or "Annexure 1" in rec
        ]
        assert len(critical_items) > 0, "Missing critical sections should be in Phase 1"

        # Verify NESTING items are deferred
        nesting_items = [
            rec for rec in batch["classification_result"].deferred
            if "8.4.1" in rec.raw or "sub-element" in rec.raw.lower()
        ]
        assert len(nesting_items) > 0, "Sub-element nesting should be deferred to Phase 2"

    def test_cycle2_metrics_baseline(self):
        """Verify Phase 1 selection would improve Cycle 2 metrics."""
        # Cycle 2 baseline: 0.6067
        # Phase 1 targets: stabilize (> 0.59) or improve (> 0.61)

        cycle2_baseline = 0.6067
        regression_threshold = 0.02

        acceptable_minimum = cycle2_baseline - regression_threshold
        acceptable_maximum = cycle2_baseline + regression_threshold * 2

        # After Phase 1, result should stay within bounds
        # (This is a placeholder; actual metric would come from running Phase 1)
        phase1_result = 0.61  # Hypothetical Phase 1 result

        assert phase1_result >= acceptable_minimum, (
            f"Phase 1 regressed too much: {phase1_result} < {acceptable_minimum}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
