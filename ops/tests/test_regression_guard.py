"""
Tests for regression detection and prevention in quality cycles.

Validates metric comparison logic, improvement delta checks, regression
tolerance bounds, and promotion gating.
"""

import pytest
from ops.docgen.regression_guard import RegressionGuard, RegressionDecision


class TestRegressionGuard:
    """Test regression detection and promotion gating."""

    def test_regression_guard_initializes_with_defaults(self):
        """Test that RegressionGuard initializes with sensible defaults."""
        guard = RegressionGuard()

        assert guard.min_improvement_delta == 0.02
        assert guard.regression_tolerance == 0.01

    def test_regression_guard_initializes_with_custom_values(self):
        """Test that RegressionGuard accepts custom thresholds."""
        guard = RegressionGuard(min_improvement_delta=0.03, regression_tolerance=0.02)

        assert guard.min_improvement_delta == 0.03
        assert guard.regression_tolerance == 0.02

    def test_compare_promotes_when_all_metrics_improve(self):
        """Test that comparison promotes when all metrics improve."""
        guard = RegressionGuard(min_improvement_delta=0.02, regression_tolerance=0.01)

        before_eval = {
            "metrics": {
                "completeness": 0.75,
                "coherence": 0.80,
                "accuracy": 0.82,
            }
        }

        after_eval = {
            "metrics": {
                "completeness": 0.80,  # +0.05
                "coherence": 0.85,     # +0.05
                "accuracy": 0.88,      # +0.06
            }
        }

        result = guard.compare(before_eval, after_eval)

        assert result.promoted is True
        assert "improved" in result.reason.lower()
        assert result.delta > 0

    def test_compare_rejects_when_metric_regresses_beyond_tolerance(self):
        """Test that comparison rejects if any metric regresses beyond tolerance."""
        guard = RegressionGuard(min_improvement_delta=0.02, regression_tolerance=0.01)

        before_eval = {
            "metrics": {
                "completeness": 0.80,
                "coherence": 0.85,
                "accuracy": 0.88,
            }
        }

        after_eval = {
            "metrics": {
                "completeness": 0.85,  # +0.05 (good)
                "coherence": 0.87,     # +0.02 (good)
                "accuracy": 0.86,      # -0.02 (regression beyond tolerance)
            }
        }

        result = guard.compare(before_eval, after_eval)

        assert result.promoted is False
        assert "regressed" in result.reason.lower()
        assert "accuracy" in result.reason
        assert len(result.regressions) >= 1

    def test_compare_rejects_when_all_improvements_below_min_delta(self):
        """Test that comparison rejects if all improvements are below min delta."""
        guard = RegressionGuard(min_improvement_delta=0.05, regression_tolerance=0.01)

        before_eval = {
            "metrics": {
                "completeness": 0.75,
                "coherence": 0.80,
                "accuracy": 0.82,
            }
        }

        after_eval = {
            "metrics": {
                "completeness": 0.78,  # +0.03 (below min 0.05)
                "coherence": 0.82,     # +0.02 (below min 0.05)
                "accuracy": 0.85,      # +0.03 (below min 0.05)
            }
        }

        result = guard.compare(before_eval, after_eval)

        assert result.promoted is False
        assert "below minimum delta" in result.reason.lower()

    def test_compare_handles_missing_metrics(self):
        """Test that comparison handles metrics missing from either evaluation."""
        guard = RegressionGuard(min_improvement_delta=0.02, regression_tolerance=0.01)

        before_eval = {
            "metrics": {
                "completeness": 0.75,
                "coherence": 0.80,
            }
        }

        after_eval = {
            "metrics": {
                "completeness": 0.80,  # +0.05
                "coherence": 0.85,     # +0.05
                "accuracy": 0.88,      # New metric (value of 0.88 vs default 0.0)
            }
        }

        result = guard.compare(before_eval, after_eval)

        # Should still promote if overall conditions met
        assert result.promoted is True

    def test_compare_handles_none_input(self):
        """Test that comparison handles None evaluation gracefully."""
        guard = RegressionGuard()

        result = guard.compare(None, {"metrics": {"test": 0.5}})

        assert result.promoted is False
        assert "invalid" in result.reason.lower()

    def test_compare_handles_non_dict_input(self):
        """Test that comparison handles non-dict input gracefully."""
        guard = RegressionGuard()

        result = guard.compare("not a dict", {"metrics": {"test": 0.5}})

        assert result.promoted is False
        assert "invalid" in result.reason.lower()

    def test_compare_handles_invalid_metrics_structure(self):
        """Test that comparison handles invalid metrics structure."""
        guard = RegressionGuard()

        before_eval = {"metrics": "not a dict"}
        after_eval = {"metrics": {"test": 0.5}}

        result = guard.compare(before_eval, after_eval)

        assert result.promoted is False
        assert "invalid metrics" in result.reason.lower()

    def test_compare_handles_missing_metrics_key(self):
        """Test that comparison handles missing metrics key."""
        guard = RegressionGuard()

        before_eval = {"data": {"test": 0.5}}
        after_eval = {"data": {"test": 0.6}}

        result = guard.compare(before_eval, after_eval)

        assert result.promoted is False
        assert "no metrics" in result.reason.lower()

    def test_compare_handles_empty_metrics(self):
        """Test that comparison handles empty metrics dict."""
        guard = RegressionGuard()

        before_eval = {"metrics": {}}
        after_eval = {"metrics": {}}

        result = guard.compare(before_eval, after_eval)

        assert result.promoted is False
        assert "no metrics" in result.reason.lower()

    def test_compare_tracks_all_regressions(self):
        """Test that comparison tracks all metrics that regressed."""
        guard = RegressionGuard(min_improvement_delta=0.02, regression_tolerance=0.005)

        before_eval = {
            "metrics": {
                "metric_a": 0.80,
                "metric_b": 0.80,
                "metric_c": 0.80,
            }
        }

        after_eval = {
            "metrics": {
                "metric_a": 0.85,     # +0.05 (good)
                "metric_b": 0.78,     # -0.02 (regression)
                "metric_c": 0.77,     # -0.03 (regression)
            }
        }

        result = guard.compare(before_eval, after_eval)

        assert result.promoted is False
        # Should have tracked regressions
        assert len(result.regressions) >= 1

    def test_regression_decision_frozen(self):
        """Test that RegressionDecision is immutable."""
        decision = RegressionDecision(
            promoted=True,
            reason="All metrics improved",
            delta=0.05,
            regressions={},
        )

        assert decision.promoted is True

        with pytest.raises(AttributeError):
            decision.promoted = False

    def test_compare_with_non_numeric_metric_values(self):
        """Test that comparison skips non-numeric metric values."""
        guard = RegressionGuard()

        before_eval = {
            "metrics": {
                "metric_a": 0.75,
                "metric_b": "invalid",  # Non-numeric
                "metric_c": 0.80,
            }
        }

        after_eval = {
            "metrics": {
                "metric_a": 0.85,       # +0.10
                "metric_b": "also_invalid",
                "metric_c": 0.90,       # +0.10
            }
        }

        result = guard.compare(before_eval, after_eval)

        # Should evaluate only numeric metrics and promote
        assert result.promoted is True

    def test_compare_calculates_largest_delta(self):
        """Test that compare tracks largest absolute delta."""
        guard = RegressionGuard(min_improvement_delta=0.01, regression_tolerance=0.01)

        before_eval = {
            "metrics": {
                "a": 0.50,
                "b": 0.80,
            }
        }

        after_eval = {
            "metrics": {
                "a": 0.52,  # +0.02
                "b": 0.78,  # -0.02
            }
        }

        result = guard.compare(before_eval, after_eval)

        assert result.delta >= 0.02
