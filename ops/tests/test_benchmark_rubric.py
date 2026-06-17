"""
Tests for DOCGEN benchmark rubric validation.

Validates the canonical 9-dimension quality rubric and its weight constraints.
"""

import pytest
from ops.docgen.benchmark_rubric import BenchmarkRubric


class TestBenchmarkRubric:
    """Test canonical benchmark rubric definitions and validation."""

    def test_benchmark_rubric_weights_sum_to_one(self):
        """Test that default rubric weights sum to 1.0."""
        rubric = BenchmarkRubric()
        total = (
            rubric.structure_weight
            + rubric.completeness_weight
            + rubric.reasoning_weight
            + rubric.specificity_weight
            + rubric.actionability_weight
            + rubric.clarity_weight
            + rubric.formatting_weight
            + rubric.evidence_weight
            + rubric.no_leakage_weight
        )
        assert abs(total - 1.0) < 0.0001, f"Weights sum to {total}, expected 1.0"

    def test_benchmark_rubric_all_weights_non_negative(self):
        """Test that all weights are non-negative."""
        rubric = BenchmarkRubric()
        assert rubric.structure_weight >= 0.0
        assert rubric.completeness_weight >= 0.0
        assert rubric.reasoning_weight >= 0.0
        assert rubric.specificity_weight >= 0.0
        assert rubric.actionability_weight >= 0.0
        assert rubric.clarity_weight >= 0.0
        assert rubric.formatting_weight >= 0.0
        assert rubric.evidence_weight >= 0.0
        assert rubric.no_leakage_weight >= 0.0

    def test_benchmark_rubric_all_weights_le_one(self):
        """Test that all weights are <= 1.0."""
        rubric = BenchmarkRubric()
        assert rubric.structure_weight <= 1.0
        assert rubric.completeness_weight <= 1.0
        assert rubric.reasoning_weight <= 1.0
        assert rubric.specificity_weight <= 1.0
        assert rubric.actionability_weight <= 1.0
        assert rubric.clarity_weight <= 1.0
        assert rubric.formatting_weight <= 1.0
        assert rubric.evidence_weight <= 1.0
        assert rubric.no_leakage_weight <= 1.0

    def test_benchmark_rubric_validate_passes_for_default(self):
        """Test that validate() passes for default rubric."""
        rubric = BenchmarkRubric()
        # Should not raise
        rubric.validate()

    def test_benchmark_rubric_validate_rejects_invalid_sum_too_high(self):
        """Test that validate() rejects weights summing > 1.0 + tolerance."""
        rubric = BenchmarkRubric(structure_weight=0.5)
        with pytest.raises(ValueError) as exc_info:
            rubric.validate()
        assert "sum" in str(exc_info.value).lower()

    def test_benchmark_rubric_validate_rejects_invalid_sum_too_low(self):
        """Test that validate() rejects weights summing < 1.0 - tolerance."""
        rubric = BenchmarkRubric(structure_weight=0.0)
        with pytest.raises(ValueError) as exc_info:
            rubric.validate()
        assert "sum" in str(exc_info.value).lower()

    def test_benchmark_rubric_validate_rejects_negative_weight(self):
        """Test that validate() rejects negative weights."""
        rubric = BenchmarkRubric(structure_weight=-0.1, completeness_weight=0.28)
        with pytest.raises(ValueError) as exc_info:
            rubric.validate()
        assert "outside" in str(exc_info.value).lower() or "range" in str(
            exc_info.value
        ).lower()

    def test_benchmark_rubric_validate_rejects_weight_gt_one(self):
        """Test that validate() rejects weights > 1.0."""
        rubric = BenchmarkRubric(structure_weight=1.5)
        with pytest.raises(ValueError) as exc_info:
            rubric.validate()
        assert "outside" in str(exc_info.value).lower() or "range" in str(
            exc_info.value
        ).lower()

    def test_benchmark_rubric_is_frozen(self):
        """Test that BenchmarkRubric is immutable."""
        rubric = BenchmarkRubric()
        with pytest.raises(
            (AttributeError, TypeError)
        ):  # Varies by Python version
            rubric.structure_weight = 0.2
