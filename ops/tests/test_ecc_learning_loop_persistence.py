"""Tests for ECC Learning Loop persistence (save/load round-trip).

Validates that all 4 learning loop classes correctly serialize state to JSON
and restore it on load, so state survives container restarts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.ecc_core.learning_loops import (
    CandidateStatus,
    FailureLearningLoop,
    FailurePattern,
    MetaLearningEngine,
    OptimizationLoop,
    ParameterCandidate,
    SkillFusionEngine,
)


class TestFailurePatternSerialization:
    def test_round_trip(self) -> None:
        fp = FailurePattern(
            pattern_id="timeout_repair_timeout",
            error_category="timeout",
            frequency=5,
            affected_skills={"repair_timeout", "repair_network"},
            suggested_fix="Fix timeout issues",
            confidence=0.50,
        )
        d = fp.to_dict()
        restored = FailurePattern.from_dict(d)
        assert restored.pattern_id == fp.pattern_id
        assert restored.affected_skills == fp.affected_skills
        assert restored.confidence == fp.confidence

    def test_set_serializes_as_sorted_list(self) -> None:
        fp = FailurePattern(
            pattern_id="x", error_category="e", frequency=1,
            affected_skills={"z_skill", "a_skill"},
            suggested_fix="f", confidence=0.1,
        )
        d = fp.to_dict()
        assert d["affected_skills"] == ["a_skill", "z_skill"]


class TestParameterCandidateSerialization:
    def test_round_trip(self) -> None:
        pc = ParameterCandidate(
            candidate_id="skill_latency",
            skill_id="skill",
            parameter_name="max_workers",
            baseline_value=4,
            candidate_value=8,
            expected_improvement=0.15,
            test_runs=3,
            improvement_observed=0.12,
            status=CandidateStatus.APPROVED,
        )
        d = pc.to_dict()
        restored = ParameterCandidate.from_dict(d)
        assert restored.candidate_id == pc.candidate_id
        assert restored.status == CandidateStatus.APPROVED
        assert restored.improvement_observed == 0.12


class TestFailureLearningLoopPersistence:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        loop = FailureLearningLoop()
        loop.analyze_failure_events([
            {"event_type": "skill_failure", "payload": {"skill_id": "repair_timeout", "error_category": "timeout"}},
            {"event_type": "skill_failure", "payload": {"skill_id": "repair_timeout", "error_category": "timeout"}},
        ])
        assert len(loop.patterns) == 1

        path = tmp_path / "failure.json"
        loop.save(path)
        assert path.exists()

        restored = FailureLearningLoop.load(path)
        assert len(restored.patterns) == 1
        key = list(restored.patterns.keys())[0]
        assert restored.patterns[key].frequency == 2
        assert restored.patterns[key].affected_skills == {"repair_timeout"}

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        loop = FailureLearningLoop.load(tmp_path / "nonexistent.json")
        assert loop.patterns == {}


class TestOptimizationLoopPersistence:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        loop = OptimizationLoop()
        loop.suggest_parameter_optimizations(
            "my_skill",
            {"latency_p95_ms": 2000},
            {"latency_p95_ms": 1000},
        )
        assert len(loop.candidates) == 1

        path = tmp_path / "opt.json"
        loop.save(path)

        restored = OptimizationLoop.load(path)
        assert len(restored.candidates) == 1
        c = list(restored.candidates.values())[0]
        assert c.skill_id == "my_skill"
        assert c.status == CandidateStatus.PROPOSED

    def test_approved_status_persists(self, tmp_path: Path) -> None:
        loop = OptimizationLoop()
        loop.suggest_parameter_optimizations("s", {"latency_p95_ms": 2000}, {"latency_p95_ms": 1000})
        cid = list(loop.candidates.keys())[0]
        loop.record_test_result(cid, 0.20)
        assert loop.candidates[cid].status == CandidateStatus.APPROVED

        path = tmp_path / "opt.json"
        loop.save(path)
        restored = OptimizationLoop.load(path)
        assert restored.candidates[cid].status == CandidateStatus.APPROVED

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        loop = OptimizationLoop.load(tmp_path / "nonexistent.json")
        assert loop.candidates == {}


class TestMetaLearningPersistence:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        engine = MetaLearningEngine()
        engine.strategies["skill_a"] = {"trend": "improving", "approach": "aggressive"}

        path = tmp_path / "meta.json"
        engine.save(path)

        restored = MetaLearningEngine.load(path)
        assert restored.strategies["skill_a"]["trend"] == "improving"

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        engine = MetaLearningEngine.load(tmp_path / "nonexistent.json")
        assert engine.strategies == {}


class TestSkillFusionPersistence:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        engine = SkillFusionEngine()
        engine.proposals["a_b"] = {"fusion_id": "a_b", "skills": ["a", "b"], "synergy": 0.25}

        path = tmp_path / "fusion.json"
        engine.save(path)

        restored = SkillFusionEngine.load(path)
        assert restored.proposals["a_b"]["synergy"] == 0.25

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        engine = SkillFusionEngine.load(tmp_path / "nonexistent.json")
        assert engine.proposals == {}


class TestLearningLoopConsumerPersistence:
    """Test that LearningLoopConsumer loads/saves state through its lifecycle."""

    def test_state_dir_created_on_init(self, tmp_path: Path) -> None:
        """Consumer creates state dir if it doesn't exist."""
        from unittest.mock import AsyncMock
        from ops.logi.learning_loop_consumer import LearningLoopConsumer

        state_dir = tmp_path / "ecc_state"
        bus = AsyncMock()
        consumer = LearningLoopConsumer(bus, state_dir=state_dir)
        assert state_dir.exists()
        assert consumer.failure_loop is not None

    def test_save_state_creates_files(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock
        from ops.logi.learning_loop_consumer import LearningLoopConsumer

        state_dir = tmp_path / "ecc_state"
        bus = AsyncMock()
        consumer = LearningLoopConsumer(bus, state_dir=state_dir)

        # Add some data and save
        consumer.failure_loop.patterns["test"] = FailurePattern(
            pattern_id="test", error_category="e", frequency=1,
            affected_skills=set(), suggested_fix="f", confidence=0.5,
        )
        consumer._save_state()

        assert (state_dir / "failure_patterns.json").exists()
        assert (state_dir / "optimization_candidates.json").exists()
        assert (state_dir / "meta_strategies.json").exists()
        assert (state_dir / "fusion_proposals.json").exists()

    def test_state_survives_reinstantiation(self, tmp_path: Path) -> None:
        """State persisted by one consumer is loaded by the next."""
        from unittest.mock import AsyncMock
        from ops.logi.learning_loop_consumer import LearningLoopConsumer

        state_dir = tmp_path / "ecc_state"
        bus = AsyncMock()

        # First consumer — add data and save
        c1 = LearningLoopConsumer(bus, state_dir=state_dir)
        c1.failure_loop.patterns["timeout_repair"] = FailurePattern(
            pattern_id="timeout_repair", error_category="timeout",
            frequency=7, affected_skills={"repair_timeout"},
            suggested_fix="Increase timeout", confidence=0.70,
        )
        c1._save_state()

        # Second consumer — should load the persisted state
        c2 = LearningLoopConsumer(bus, state_dir=state_dir)
        assert "timeout_repair" in c2.failure_loop.patterns
        assert c2.failure_loop.patterns["timeout_repair"].frequency == 7
