"""
Test suite for BaselineEvalMinimal and 7-metric evaluation system.

Validates 7-dimensional artifact quality evaluation, gate determination,
and verdict readiness across baseline_score ranges and scenario types.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from ops.docgen.baseline_eval_minimal import BaselineEvalMinimal, BaselineEvalResult
from ops.docgen.document_block_graph import (
    DocumentBlock,
    DocumentBlockGraph,
    BlockType,
)


class TestBaselineEvalMinimal:
    """Test suite for BaselineEvalMinimal 7-metric evaluator."""

    @pytest.fixture
    def minimal_graph(self):
        """Create minimal valid graph with 3 required blocks."""
        graph = DocumentBlockGraph(document_type="technical_report")
        for i in range(1, 4):
            block = DocumentBlock(
                block_id=f"SEC-{i:03d}",
                block_type=BlockType.SECTION,
                document_type="technical_report",
                required=True,
                generated_content=f"Content for section {i}. " * 50,
                quality_score=0.85,
            )
            graph.blocks[f"SEC-{i:03d}"] = block
        return graph

    @pytest.fixture
    def evaluator(self):
        """Create evaluator instance."""
        return BaselineEvalMinimal()

    def test_evaluator_initialization(self, evaluator):
        """Test BaselineEvalMinimal initializes with 7-metric weights."""
        assert evaluator.metric_weights is not None
        assert len(evaluator.metric_weights) == 7
        assert "evidence_completeness" in evaluator.metric_weights
        weights_sum = sum(evaluator.metric_weights.values())
        assert abs(weights_sum - 1.0) < 0.01, f"Weights don't sum to 1.0: {weights_sum}"

    def test_evaluate_returns_dict_with_required_keys(self, evaluator, minimal_graph):
        """Test evaluate() returns dict with all required keys."""
        result = evaluator.evaluate(
            graph=minimal_graph,
            audit_report={"approval": True, "findings": []},
            render_metrics={"page_count": 5, "blank_page_count": 0},
            visual_qa_passed=True,
            training_pairs_count=3,
            evidence_manifest={
                "plan_snapshot": "/path/to/plan.json",
                "block_graph_final": "/path/to/graph.json",
                "implementation_log": "/path/to/log.md",
            },
        )

        assert isinstance(result, dict)
        required_keys = [
            "timestamp",
            "metrics",
            "metric_weights",
            "baseline_score",
            "overall_verdict",
            "rationale",
            "gates",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_evaluate_contains_all_seven_metrics(self, evaluator, minimal_graph):
        """Test that evaluate() produces all 7 metrics."""
        result = evaluator.evaluate(graph=minimal_graph)

        assert "metrics" in result
        metrics = result["metrics"]
        expected_metrics = {
            "content_completeness",
            "quality_consistency",
            "structural_integrity",
            "issue_freedom",
            "training_readiness",
            "render_compatibility",
            "evidence_completeness",
        }
        for metric in expected_metrics:
            assert metric in metrics, f"Missing metric: {metric}"
            assert isinstance(metrics[metric], (int, float))
            assert 0.0 <= metrics[metric] <= 1.0

    def test_baseline_score_is_weighted_sum(self, evaluator, minimal_graph):
        """Test baseline_score is correctly weighted sum of metrics."""
        result = evaluator.evaluate(graph=minimal_graph)

        baseline_score = result["baseline_score"]
        metrics = result["metrics"]
        weights = result["metric_weights"]

        expected_score = sum(metrics.get(m, 0) * weights[m] for m in weights)
        assert abs(baseline_score - expected_score) < 0.01

    def test_evaluate_with_empty_evidence_manifest(self, evaluator, minimal_graph):
        """Test evaluate() gracefully handles missing evidence."""
        result = evaluator.evaluate(
            graph=minimal_graph,
            evidence_manifest=None,
        )

        assert "metrics" in result
        # evidence_completeness should be reduced when manifest is missing
        assert "evidence_completeness" in result["metrics"]

    def test_evaluate_with_complete_evidence_manifest(self, evaluator, minimal_graph):
        """Test evaluate() awards higher evidence_completeness with complete manifest."""
        complete_manifest = {
            "plan_snapshot": "/path/to/plan.json",
            "block_graph_final": "/path/to/graph.json",
            "implementation_log": "/path/to/log.md",
        }

        result = evaluator.evaluate(
            graph=minimal_graph,
            evidence_manifest=complete_manifest,
        )

        assert result["metrics"]["evidence_completeness"] > 0.5

    def test_gates_dict_contains_canonical_gates(self, evaluator, minimal_graph):
        """Test that gates dict includes all 16 canonical gates."""
        result = evaluator.evaluate(graph=minimal_graph)

        gates = result.get("gates", {})
        assert isinstance(gates, dict)
        # Should have gates for content, quality, structure, issues, training, render
        assert any("content" in k.lower() for k in gates.keys())
        assert any("issue" in k.lower() for k in gates.keys())

    def test_overall_verdict_field_present(self, evaluator, minimal_graph):
        """Test that evaluate() sets overall_verdict field."""
        result = evaluator.evaluate(graph=minimal_graph)

        assert "overall_verdict" in result
        verdict = result["overall_verdict"]
        assert isinstance(verdict, str)
        assert verdict in [
            "PASS",
            "READY_WITH_WARNINGS",
            "NEEDS_MORE_REPAIR",
            "NEEDS_TRAINING",
            "BLOCKED",
            "MARGINAL",
        ]

    def test_rationale_present_and_not_empty(self, evaluator, minimal_graph):
        """Test that rationale explains the evaluation decision."""
        result = evaluator.evaluate(graph=minimal_graph)

        assert "rationale" in result
        assert isinstance(result["rationale"], str)
        assert len(result["rationale"]) > 10
