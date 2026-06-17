"""
Tests for DOCGEN benchmark comparator.

Validates quality ratio computation, gap identification, and
recommendation generation.
"""

import pytest
from pathlib import Path
import json
import tempfile

from ops.docgen.benchmark_comparator import (
    clamp,
    compare_to_benchmark,
    save_benchmark_comparison,
    BenchmarkComparisonResult,
)
from ops.docgen.benchmark_rubric import BenchmarkRubric


class TestClamp:
    """Test clamp utility function."""

    def test_clamp_within_range(self):
        """Test clamp returns unchanged value within [0.0, 1.0]."""
        assert clamp(0.5) == 0.5
        assert clamp(0.0) == 0.0
        assert clamp(1.0) == 1.0

    def test_clamp_below_range(self):
        """Test clamp clamps values < 0.0 to 0.0."""
        assert clamp(-0.5) == 0.0
        assert clamp(-100.0) == 0.0

    def test_clamp_above_range(self):
        """Test clamp clamps values > 1.0 to 1.0."""
        assert clamp(1.5) == 1.0
        assert clamp(100.0) == 1.0


class TestCompareToBenchmark:
    """Test benchmark comparison logic."""

    def _make_dimension_scores(
        self,
        structure=1.0,
        completeness=1.0,
        reasoning=1.0,
        specificity=1.0,
        actionability=1.0,
        clarity=1.0,
        formatting=1.0,
        evidence=1.0,
        no_leakage=1.0,
    ) -> dict:
        """Helper to create dimension scores dict."""
        return {
            "structure": structure,
            "completeness": completeness,
            "reasoning": reasoning,
            "specificity": specificity,
            "actionability": actionability,
            "clarity": clarity,
            "formatting": formatting,
            "evidence": evidence,
            "no_leakage": no_leakage,
        }

    def test_compare_to_benchmark_perfect_score(self):
        """Test comparison with all dimension scores at 1.0."""
        scores = self._make_dimension_scores()
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
            benchmark_score=1.0,
            target_ratio=0.95,
        )

        assert result.candidate_score == 1.0
        assert result.quality_ratio == 1.0
        assert result.passed_target is True
        assert result.passed_stretch_target is True
        assert len(result.gaps) == 0

    def test_compare_to_benchmark_passes_target(self):
        """Test comparison that passes target but not stretch."""
        scores = self._make_dimension_scores(
            structure=0.96,
            completeness=0.96,
            reasoning=0.96,
            specificity=0.96,
            actionability=0.96,
            clarity=0.96,
            formatting=0.96,
            evidence=0.96,
            no_leakage=0.96,
        )
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
            target_ratio=0.95,
            stretch_target_ratio=0.98,
        )

        assert result.quality_ratio >= 0.95
        assert result.passed_target is True

    def test_compare_to_benchmark_records_gaps(self):
        """Test that gaps are identified for scores < 0.85."""
        scores = self._make_dimension_scores(
            structure=0.80,  # Below 0.85 → gap
            completeness=0.90,
            reasoning=0.90,
            specificity=0.90,
            actionability=0.90,
            clarity=0.90,
            formatting=0.90,
            evidence=0.90,
            no_leakage=0.90,
        )
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
        )

        assert "structure" in result.gaps
        assert len(result.gaps) == 1

    def test_compare_to_benchmark_multiple_gaps(self):
        """Test identification of multiple gaps."""
        scores = self._make_dimension_scores(
            structure=0.70,
            completeness=0.75,
            reasoning=0.90,
            specificity=0.90,
            actionability=0.90,
            clarity=0.90,
            formatting=0.90,
            evidence=0.90,
            no_leakage=0.90,
        )
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
        )

        assert "structure" in result.gaps
        assert "completeness" in result.gaps
        assert len(result.gaps) == 2
        assert len(result.recommendations) == 2

    def test_compare_to_benchmark_missing_keys_raises(self):
        """Test that missing dimension scores raise ValueError."""
        scores = {"structure": 1.0}  # Missing 8 keys
        with pytest.raises(ValueError) as exc_info:
            compare_to_benchmark(
                document_type="technical_report",
                dimension_scores=scores,
            )
        assert "Missing" in str(exc_info.value)

    def test_compare_to_benchmark_clamps_scores(self):
        """Test that dimension scores are clamped to [0.0, 1.0]."""
        scores = self._make_dimension_scores(
            structure=-0.5,  # Will be clamped to 0.0
            completeness=1.5,  # Will be clamped to 1.0
        )
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
        )

        assert result.dimension_scores["structure"] == 0.0
        assert result.dimension_scores["completeness"] == 1.0

    def test_compare_to_benchmark_custom_rubric(self):
        """Test comparison with custom rubric."""
        scores = self._make_dimension_scores(structure=0.5, completeness=0.5)
        custom_rubric = BenchmarkRubric(
            structure_weight=0.5,
            completeness_weight=0.5,
            reasoning_weight=0.0,
            specificity_weight=0.0,
            actionability_weight=0.0,
            clarity_weight=0.0,
            formatting_weight=0.0,
            evidence_weight=0.0,
            no_leakage_weight=0.0,
        )

        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
            rubric=custom_rubric,
        )

        # Expected: 0.5 * 0.5 + 0.5 * 0.5 = 0.5
        assert result.candidate_score == 0.5

    def test_compare_to_benchmark_result_has_recommendations(self):
        """Test that gaps generate corresponding recommendations."""
        scores = self._make_dimension_scores(
            structure=0.70,
            clarity=0.80,
        )
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
        )

        assert len(result.recommendations) >= len(result.gaps)
        # Each recommendation should be a non-empty string
        for rec in result.recommendations:
            assert isinstance(rec, str)
            assert len(rec) > 0


class TestSaveBenchmarkComparison:
    """Test benchmark comparison serialization."""

    def test_save_benchmark_comparison(self):
        """Test that save writes valid JSON to file."""
        scores = {
            "structure": 0.9,
            "completeness": 0.9,
            "reasoning": 0.9,
            "specificity": 0.9,
            "actionability": 0.9,
            "clarity": 0.9,
            "formatting": 0.9,
            "evidence": 0.9,
            "no_leakage": 0.9,
        }
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "comparison.json"
            save_benchmark_comparison(result, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                data = json.load(f)

            assert data["document_type"] == "technical_report"
            assert "candidate_score" in data
            assert "quality_ratio" in data
            assert "gaps" in data
            assert "recommendations" in data

    def test_save_benchmark_comparison_creates_parent_dirs(self):
        """Test that save creates parent directories if needed."""
        scores = {
            "structure": 0.9,
            "completeness": 0.9,
            "reasoning": 0.9,
            "specificity": 0.9,
            "actionability": 0.9,
            "clarity": 0.9,
            "formatting": 0.9,
            "evidence": 0.9,
            "no_leakage": 0.9,
        }
        result = compare_to_benchmark(
            document_type="technical_report",
            dimension_scores=scores,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = (
                Path(tmpdir) / "deep" / "nested" / "path" / "comparison.json"
            )
            save_benchmark_comparison(result, output_path)

            assert output_path.exists()
            assert output_path.parent.exists()
