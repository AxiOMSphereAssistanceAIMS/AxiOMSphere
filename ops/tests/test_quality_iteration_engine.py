"""
Tests for DOCGEN quality iteration engine.

Validates the autonomous quality improvement loop: state persistence,
plateau detection, terminal conditions, and integration with vertical slice.
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from ops.docgen.quality_iteration_engine import (
    utc_now,
    QualityIterationRecord,
    QualityLoopState,
    extract_dimension_scores,
    QualityIterationEngine,
)
from ops.docgen.benchmark_comparator import BenchmarkComparisonResult


class TestUtcNow:
    """Test UTC timestamp generation."""

    def test_utc_now_format(self):
        """Test that utc_now returns ISO format string."""
        ts = utc_now()
        assert isinstance(ts, str)
        assert ts.endswith("Z")
        assert "T" in ts
        # Should have format: 2026-06-11T08:30:45Z (no microseconds)
        parts = ts.split("T")
        assert len(parts) == 2
        date_part, time_part = parts
        assert time_part.endswith("Z")
        time_no_z = time_part[:-1]
        assert len(time_no_z.split(":")) == 3  # HH:MM:SS
        assert "." not in time_no_z  # No microseconds


class TestQualityIterationRecord:
    """Test immutable iteration record."""

    def test_iteration_record_creation(self):
        """Test creating a QualityIterationRecord."""
        record = QualityIterationRecord(
            iteration_index=0,
            output_dir="/tmp/iter_0",
            verdict="PASS",
            baseline_score=0.85,
            auditor_score=0.90,
            quality_ratio=0.875,
            passed_target=False,
            passed_stretch_target=False,
            gaps=["structure"],
            recommendations=["Review document organization"],
        )
        assert record.iteration_index == 0
        assert record.baseline_score == 0.85
        assert record.auditor_score == 0.90
        assert record.quality_ratio == 0.875

    def test_iteration_record_to_dict(self):
        """Test conversion to dict for JSON serialization."""
        record = QualityIterationRecord(
            iteration_index=0,
            output_dir="/tmp/iter_0",
            verdict="PASS",
            baseline_score=0.85,
            auditor_score=0.90,
            quality_ratio=0.875,
            passed_target=False,
            passed_stretch_target=False,
            gaps=["structure"],
            recommendations=["Review document organization"],
        )
        d = record.to_dict()
        assert d["iteration_index"] == 0
        assert d["baseline_score"] == 0.85
        assert d["auditor_score"] == 0.90
        assert d["quality_ratio"] == 0.875
        assert d["gaps"] == ["structure"]

    def test_iteration_record_is_frozen(self):
        """Test that QualityIterationRecord is immutable."""
        record = QualityIterationRecord(
            iteration_index=0,
            output_dir="/tmp/iter_0",
            verdict="PASS",
            baseline_score=0.85,
            auditor_score=None,
            quality_ratio=0.85,
            passed_target=False,
            passed_stretch_target=False,
        )
        with pytest.raises((AttributeError, TypeError)):
            record.iteration_index = 1


class TestQualityLoopState:
    """Test mutable loop state."""

    def test_loop_state_creation(self):
        """Test creating QualityLoopState."""
        state = QualityLoopState(
            loop_id="quality_loop_20260611T083045Z",
            document_type="technical_report",
            topic="Aircraft Preservation Protocols",
            target_ratio=0.95,
            stretch_target_ratio=0.98,
            max_iterations=7,
            plateau_patience=2,
        )
        assert state.loop_id == "quality_loop_20260611T083045Z"
        assert state.best_quality_ratio == 0.0
        assert state.best_iteration == -1
        assert state.no_progress_count == 0
        assert state.status == "RUNNING"

    def test_loop_state_save_and_load(self):
        """Test saving and loading loop state."""
        state = QualityLoopState(
            loop_id="quality_loop_test",
            document_type="technical_report",
            topic="Test Topic",
            target_ratio=0.95,
            stretch_target_ratio=0.98,
            max_iterations=7,
            plateau_patience=2,
            best_quality_ratio=0.88,
            best_iteration=2,
            status="RUNNING",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state.save(state_path)

            assert state_path.exists()
            with open(state_path) as f:
                data = json.load(f)

            assert data["loop_id"] == "quality_loop_test"
            assert data["document_type"] == "technical_report"
            assert data["best_quality_ratio"] == 0.88
            assert data["best_iteration"] == 2


class TestExtractDimensionScores:
    """Test dimension score extraction from evaluator results."""

    def test_extract_scores_with_baseline_only(self):
        """Test extracting dimension scores from baseline evaluation."""
        baseline_eval = {
            "baseline_score": 0.75,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "evidence_complete": True,
                "no_internal_metadata_leaks": True,
            },
        }

        scores = extract_dimension_scores(baseline_eval, None, None)

        assert len(scores) == 9
        assert all(k in scores for k in [
            "structure", "completeness", "reasoning", "specificity",
            "actionability", "clarity", "formatting", "evidence", "no_leakage"
        ])
        # Effective quality should be baseline_score when no auditor
        assert scores["reasoning"] == 0.75

    def test_extract_scores_with_auditor(self):
        """Test extracting dimension scores with auditor result."""
        baseline_eval = {
            "baseline_score": 0.80,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "evidence_complete": True,
                "no_internal_metadata_leaks": True,
            },
        }
        auditor_result = {"overall_score": 0.90}

        scores = extract_dimension_scores(baseline_eval, auditor_result, None)

        # effective_quality = 0.80 * 0.65 + 0.90 * 0.35 = 0.52 + 0.315 = 0.835
        expected_quality = 0.80 * 0.65 + 0.90 * 0.35
        assert abs(scores["reasoning"] - expected_quality) < 0.001

    def test_extract_scores_skips_mock_auditor_blend(self):
        """Test mock auditors do not down-weight the baseline score."""
        baseline_eval = {
            "baseline_score": 0.92,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "evidence_complete": True,
                "no_internal_metadata_leaks": True,
            },
        }
        auditor_result = {
            "overall_score": 0.62,
            "provider": "mock",
            "degraded": True,
        }

        scores = extract_dimension_scores(baseline_eval, auditor_result, None)

        assert scores["reasoning"] == 0.92

    def test_extract_scores_skips_degraded_auditor_blend(self):
        """Test degraded auditors do not down-weight the baseline score."""
        baseline_eval = {
            "baseline_score": 0.92,
            "gates": {
                "all_required_blocks_generated": True,
                "render_success": True,
                "evidence_complete": True,
                "no_internal_metadata_leaks": True,
            },
        }
        auditor_result = {
            "overall_score": 0.62,
            "provider": "anthropic_direct",
            "degraded": True,
        }

        scores = extract_dimension_scores(baseline_eval, auditor_result, None)

        assert scores["reasoning"] == 0.92

    def test_extract_scores_gates_affect_dimensions(self):
        """Test that gate failures reduce relevant dimensions."""
        baseline_eval = {
            "baseline_score": 1.0,
            "gates": {
                "all_required_blocks_generated": False,  # Affects structure & completeness
                "render_success": False,  # Affects formatting
                "evidence_complete": False,  # Affects evidence
                "no_internal_metadata_leaks": False,  # Affects no_leakage
            },
        }

        scores = extract_dimension_scores(baseline_eval, None, None)

        # Failed gates should result in lower scores
        assert scores["structure"] < 1.0
        assert scores["completeness"] < 1.0
        assert scores["formatting"] < 1.0
        assert scores["evidence"] < 1.0
        assert scores["no_leakage"] < 1.0

    def test_extract_scores_clamps_auditor_values(self):
        """Test that auditor scores are clamped to [0.0, 1.0]."""
        baseline_eval = {"baseline_score": 0.5}
        auditor_result = {"overall_score": 2.5}  # Invalid

        scores = extract_dimension_scores(baseline_eval, auditor_result, None)

        # Should use clamped auditor_score (1.0)
        # effective_quality = 0.5 * 0.65 + 1.0 * 0.35 = 0.325 + 0.35 = 0.675
        assert 0.67 < scores["reasoning"] < 0.68


class TestQualityIterationEngine:
    """Test quality iteration engine orchestration."""

    def test_engine_initialization(self):
        """Test QualityIterationEngine initialization."""
        engine = QualityIterationEngine(
            workspace_dir="/tmp/quality_loop",
            target_ratio=0.95,
            stretch_target_ratio=0.98,
            max_iterations=7,
            plateau_patience=2,
        )
        assert engine.target_ratio == 0.95
        assert engine.stretch_target_ratio == 0.98
        assert engine.max_iterations == 7
        assert engine.plateau_patience == 2

    @patch("ops.docgen.quality_iteration_engine.run_vertical_slice")
    def test_engine_single_iteration_passes_target(self, mock_vertical_slice):
        """Test engine stops when target is passed."""
        # Mock vertical_slice to return a successful generation
        mock_vertical_slice.return_value = {
            "output_dir": "/tmp/iter_0",
            "verdict": "PASS",
            "baseline_eval_path": None,
            "final_decision_path": None,
            "auditor_result_path": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = QualityIterationEngine(
                workspace_dir=tmpdir,
                target_ratio=0.95,
                max_iterations=7,
            )

            with patch("ops.docgen.quality_iteration_engine.compare_to_benchmark") as mock_compare:
                # Mock comparison to return passing result
                mock_compare.return_value = BenchmarkComparisonResult(
                    document_type="technical_report",
                    candidate_score=0.96,
                    benchmark_score=1.0,
                    quality_ratio=0.96,
                    target_ratio=0.95,
                    passed_target=True,
                    passed_stretch_target=False,
                    stretch_target_ratio=0.98,
                    dimension_scores={k: 0.96 for k in [
                        "structure", "completeness", "reasoning", "specificity",
                        "actionability", "clarity", "formatting", "evidence", "no_leakage"
                    ]},
                    gaps=[],
                    recommendations=[],
                )

                result = engine.run("technical_report", "Test Topic")

                assert result["status"] == "DOCGEN_DOCUMENT_QUALITY_TARGET_REACHED"
                assert result["best_quality_ratio"] == 0.96
                assert result["iterations_count"] == 1

    @patch("ops.docgen.quality_iteration_engine.run_vertical_slice")
    def test_engine_plateau_detection(self, mock_vertical_slice):
        """Test engine detects plateau and stops."""
        # Mock vertical_slice to return constant scores
        mock_vertical_slice.return_value = {
            "output_dir": "/tmp/iter_0",
            "verdict": "PASS",
            "baseline_eval_path": None,
            "final_decision_path": None,
            "auditor_result_path": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = QualityIterationEngine(
                workspace_dir=tmpdir,
                target_ratio=0.95,
                max_iterations=7,
                plateau_patience=2,
                min_improvement_delta=0.01,
            )

            with patch("ops.docgen.quality_iteration_engine.compare_to_benchmark") as mock_compare:
                # Mock to return descending quality_ratio to trigger plateau
                call_count = [0]

                def comparison_result(*args, **kwargs):
                    # Iter 0: 0.80 (best), Iter 1: 0.78 (decline), Iter 2: 0.77 (no progress) → plateau
                    scores = [0.80, 0.78, 0.77]
                    quality = scores[min(call_count[0], 2)]
                    call_count[0] += 1

                    return BenchmarkComparisonResult(
                        document_type="technical_report",
                        candidate_score=quality,
                        benchmark_score=1.0,
                        quality_ratio=quality,
                        target_ratio=0.95,
                        passed_target=False,
                        passed_stretch_target=False,
                        stretch_target_ratio=0.98,
                        dimension_scores={k: quality for k in [
                            "structure", "completeness", "reasoning", "specificity",
                            "actionability", "clarity", "formatting", "evidence", "no_leakage"
                        ]},
                        gaps=["structure"],
                        recommendations=["Review structure"],
                    )

                mock_compare.side_effect = comparison_result

                result = engine.run("technical_report", "Test Topic")

                # Should stop after 3 iterations (iter 0: best 0.80, iter 1: 0.78 declines,
                # iter 2: 0.77 below best-delta, no_progress_count=2 → plateau)
                assert result["status"] == "DOCGEN_DOCUMENT_QUALITY_PLATEAU"
                assert result["iterations_count"] == 3

    @patch("ops.docgen.quality_iteration_engine.run_vertical_slice")
    def test_engine_error_handling(self, mock_vertical_slice):
        """Test engine handles errors gracefully."""
        mock_vertical_slice.side_effect = Exception("Vertical slice failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = QualityIterationEngine(
                workspace_dir=tmpdir,
                target_ratio=0.95,
                max_iterations=7,
            )

            result = engine.run("technical_report", "Test Topic")

            assert result["status"] == "DOCGEN_QUALITY_LOOP_BLOCKED"
            assert len(result["state_path"]) > 0
            # State should have error message
            with open(result["state_path"]) as f:
                state_data = json.load(f)
            assert len(state_data["errors"]) > 0
            assert "Vertical slice failed" in state_data["errors"][0]

    @patch("ops.docgen.quality_iteration_engine.run_vertical_slice")
    def test_engine_max_iterations_reached(self, mock_vertical_slice):
        """Test engine stops at max iterations."""
        mock_vertical_slice.return_value = {
            "output_dir": "/tmp/iter_0",
            "verdict": "PASS",
            "baseline_eval_path": None,
            "final_decision_path": None,
            "auditor_result_path": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = QualityIterationEngine(
                workspace_dir=tmpdir,
                target_ratio=0.95,
                max_iterations=3,
                plateau_patience=100,  # High patience to avoid early stop
            )

            with patch("ops.docgen.quality_iteration_engine.compare_to_benchmark") as mock_compare:
                # Mock to return suboptimal scores to avoid hitting target
                def comparison_result(*args, **kwargs):
                    return BenchmarkComparisonResult(
                        document_type="technical_report",
                        candidate_score=0.92,
                        benchmark_score=1.0,
                        quality_ratio=0.92,
                        target_ratio=0.95,
                        passed_target=False,
                        passed_stretch_target=False,
                        stretch_target_ratio=0.98,
                        dimension_scores={k: 0.92 for k in [
                            "structure", "completeness", "reasoning", "specificity",
                            "actionability", "clarity", "formatting", "evidence", "no_leakage"
                        ]},
                        gaps=[],
                        recommendations=[],
                    )

                mock_compare.side_effect = comparison_result

                result = engine.run("technical_report", "Test Topic")

                assert result["status"] == "DOCGEN_DOCUMENT_QUALITY_MAX_ITERATIONS_REACHED"
                assert result["iterations_count"] == 3

    @patch("ops.docgen.quality_iteration_engine.run_vertical_slice")
    def test_engine_stretch_target_overrides_target(self, mock_vertical_slice):
        """Test that stretch target triggers before regular target."""
        mock_vertical_slice.return_value = {
            "output_dir": "/tmp/iter_0",
            "verdict": "PASS",
            "baseline_eval_path": None,
            "final_decision_path": None,
            "auditor_result_path": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = QualityIterationEngine(
                workspace_dir=tmpdir,
                target_ratio=0.95,
                stretch_target_ratio=0.98,
                max_iterations=7,
            )

            with patch("ops.docgen.quality_iteration_engine.compare_to_benchmark") as mock_compare:
                mock_compare.return_value = BenchmarkComparisonResult(
                    document_type="technical_report",
                    candidate_score=0.99,
                    benchmark_score=1.0,
                    quality_ratio=0.99,
                    target_ratio=0.95,
                    passed_target=True,
                    passed_stretch_target=True,  # Both passed
                    stretch_target_ratio=0.98,
                    dimension_scores={k: 0.99 for k in [
                        "structure", "completeness", "reasoning", "specificity",
                        "actionability", "clarity", "formatting", "evidence", "no_leakage"
                    ]},
                    gaps=[],
                    recommendations=[],
                )

                result = engine.run("technical_report", "Test Topic")

                assert result["status"] == "DOCGEN_DOCUMENT_QUALITY_STRETCH_TARGET_REACHED"
