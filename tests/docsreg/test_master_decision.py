"""
Tests for ops/docsreg/docsreg_master_decision.py

Covers:
- GateResult dataclass fields and defaults
- MasterDecision dataclass fields, serialisation, and round-trip
- DecisionEngine verdict logic: CERTIFIED, BLOCKED, ADVISORY_ONLY_FAIL, mixed
- create_engine() factory
"""
from __future__ import annotations

import json

import pytest

from ops.docsreg.docsreg_master_decision import (
    GateResult,
    MasterDecision,
    DecisionEngine,
    create_engine,
)


# ── TestGateResult ─────────────────────────────────────────────────────────────


class TestGateResult:
    def test_required_fields_stored(self):
        g = GateResult(gate_name="my_gate", passed=True)
        assert g.gate_name == "my_gate"
        assert g.passed is True

    def test_default_details_is_empty_string(self):
        g = GateResult(gate_name="g", passed=False)
        assert g.details == ""

    def test_default_blocking_is_true(self):
        g = GateResult(gate_name="g", passed=False)
        assert g.blocking is True

    def test_custom_details(self):
        g = GateResult(gate_name="g", passed=True, details="all OK")
        assert g.details == "all OK"

    def test_blocking_false(self):
        g = GateResult(gate_name="g", passed=False, blocking=False)
        assert g.blocking is False

    def test_passed_false(self):
        g = GateResult(gate_name="fail_gate", passed=False)
        assert g.passed is False


# ── TestMasterDecisionDataclass ────────────────────────────────────────────────


class TestMasterDecisionDataclass:
    def _make_decision(self, verdict="CERTIFIED", passed=True, score=0.9):
        return MasterDecision(
            verdict=verdict,
            passed=passed,
            quality_score=score,
            gate_results=[GateResult("g1", True), GateResult("g2", False, blocking=False)],
            blocking_failures=[],
            advisory_failures=["g2"],
            created_at="2026-06-10T00:00:00+00:00",
            notes="test note",
        )

    def test_fields_accessible(self):
        d = self._make_decision()
        assert d.verdict == "CERTIFIED"
        assert d.passed is True
        assert d.quality_score == 0.9
        assert len(d.gate_results) == 2
        assert d.blocking_failures == []
        assert d.advisory_failures == ["g2"]
        assert d.notes == "test note"

    def test_default_notes_is_empty_string(self):
        d = MasterDecision(
            verdict="CERTIFIED",
            passed=True,
            quality_score=1.0,
            gate_results=[],
            blocking_failures=[],
            advisory_failures=[],
            created_at="2026-06-10T00:00:00+00:00",
        )
        assert d.notes == ""

    def test_to_dict_keys(self):
        d = self._make_decision()
        result = d.to_dict()
        expected_keys = {
            "verdict", "passed", "quality_score", "gate_results",
            "blocking_failures", "advisory_failures", "created_at", "notes",
        }
        assert set(result.keys()) == expected_keys

    def test_to_dict_gate_results_are_dicts(self):
        d = self._make_decision()
        result = d.to_dict()
        assert isinstance(result["gate_results"], list)
        assert isinstance(result["gate_results"][0], dict)

    def test_to_json_is_valid_json(self):
        d = self._make_decision()
        raw = d.to_json()
        parsed = json.loads(raw)
        assert parsed["verdict"] == "CERTIFIED"

    def test_from_dict_round_trip_verdict(self):
        d = self._make_decision()
        restored = MasterDecision.from_dict(d.to_dict())
        assert restored.verdict == d.verdict

    def test_from_dict_round_trip_quality_score(self):
        d = self._make_decision()
        restored = MasterDecision.from_dict(d.to_dict())
        assert restored.quality_score == d.quality_score

    def test_from_dict_round_trip_gate_results_count(self):
        d = self._make_decision()
        restored = MasterDecision.from_dict(d.to_dict())
        assert len(restored.gate_results) == len(d.gate_results)

    def test_from_dict_round_trip_gate_result_fields(self):
        d = self._make_decision()
        restored = MasterDecision.from_dict(d.to_dict())
        assert restored.gate_results[0].gate_name == "g1"
        assert restored.gate_results[0].passed is True
        assert restored.gate_results[1].gate_name == "g2"
        assert restored.gate_results[1].blocking is False

    def test_from_dict_round_trip_failures(self):
        d = self._make_decision()
        restored = MasterDecision.from_dict(d.to_dict())
        assert restored.blocking_failures == d.blocking_failures
        assert restored.advisory_failures == d.advisory_failures

    def test_from_dict_round_trip_notes(self):
        d = self._make_decision()
        restored = MasterDecision.from_dict(d.to_dict())
        assert restored.notes == d.notes

    def test_from_dict_empty_gate_results(self):
        d = MasterDecision(
            verdict="CERTIFIED",
            passed=True,
            quality_score=1.0,
            gate_results=[],
            blocking_failures=[],
            advisory_failures=[],
            created_at="2026-06-10T00:00:00+00:00",
        )
        restored = MasterDecision.from_dict(d.to_dict())
        assert restored.gate_results == []


# ── TestDecisionEngineCertified ────────────────────────────────────────────────


class TestDecisionEngineCertified:
    def test_all_gates_pass_high_score_certified(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        engine.add_gate(GateResult("g2", passed=True))
        decision = engine.decide(quality_score=0.95)
        assert decision.verdict == "CERTIFIED"

    def test_certified_passed_is_true(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        decision = engine.decide(quality_score=0.80)
        assert decision.passed is True

    def test_certified_exact_threshold_0_60(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        decision = engine.decide(quality_score=0.60)
        assert decision.verdict == "CERTIFIED"

    def test_certified_no_blocking_failures(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        decision = engine.decide(quality_score=0.75)
        assert decision.blocking_failures == []

    def test_certified_no_advisory_failures(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        decision = engine.decide(quality_score=0.75)
        assert decision.advisory_failures == []

    def test_certified_gate_results_preserved(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("alpha", passed=True, details="OK"))
        decision = engine.decide(quality_score=0.90)
        assert len(decision.gate_results) == 1
        assert decision.gate_results[0].gate_name == "alpha"

    def test_certified_no_gates_added_high_score(self):
        engine = DecisionEngine()
        decision = engine.decide(quality_score=0.99)
        assert decision.verdict == "CERTIFIED"


# ── TestDecisionEngineBlocked ──────────────────────────────────────────────────


class TestDecisionEngineBlocked:
    def test_blocking_gate_failure_yields_blocked(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("blocker", passed=False, blocking=True))
        decision = engine.decide(quality_score=0.95)
        assert decision.verdict == "BLOCKED"

    def test_blocked_passed_is_false(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("blocker", passed=False))
        decision = engine.decide(quality_score=0.95)
        assert decision.passed is False

    def test_blocking_failure_name_in_blocking_failures(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("quality_gate", passed=False, blocking=True))
        decision = engine.decide(quality_score=0.95)
        assert "quality_gate" in decision.blocking_failures

    def test_quality_below_threshold_yields_blocked(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        decision = engine.decide(quality_score=0.59)
        assert decision.verdict == "BLOCKED"

    def test_quality_exactly_0_59_blocked(self):
        engine = DecisionEngine()
        decision = engine.decide(quality_score=0.59)
        assert decision.verdict == "BLOCKED"

    def test_quality_zero_blocked(self):
        engine = DecisionEngine()
        decision = engine.decide(quality_score=0.0)
        assert decision.verdict == "BLOCKED"

    def test_blocking_failure_quality_also_low(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=False, blocking=True))
        decision = engine.decide(quality_score=0.30)
        assert decision.verdict == "BLOCKED"
        assert "g1" in decision.blocking_failures


# ── TestDecisionEngineAdvisoryFail ─────────────────────────────────────────────


class TestDecisionEngineAdvisoryFail:
    def test_only_non_blocking_failure_advisory(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        engine.add_gate(GateResult("advisory_gate", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.85)
        assert decision.verdict == "ADVISORY_ONLY_FAIL"

    def test_advisory_passed_is_false(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("adv", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.80)
        assert decision.passed is False

    def test_advisory_failure_name_in_advisory_failures(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("docs_gate", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.75)
        assert "docs_gate" in decision.advisory_failures

    def test_advisory_no_blocking_failures(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("adv", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.80)
        assert decision.blocking_failures == []

    def test_multiple_advisory_failures(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("adv1", passed=False, blocking=False))
        engine.add_gate(GateResult("adv2", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.70)
        assert decision.verdict == "ADVISORY_ONLY_FAIL"
        assert "adv1" in decision.advisory_failures
        assert "adv2" in decision.advisory_failures


# ── TestDecisionEngineMixed ────────────────────────────────────────────────────


class TestDecisionEngineMixed:
    def test_blocking_and_advisory_failures_yields_blocked(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("blocker", passed=False, blocking=True))
        engine.add_gate(GateResult("advisory", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.90)
        assert decision.verdict == "BLOCKED"

    def test_mixed_both_failure_lists_populated(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("b1", passed=False, blocking=True))
        engine.add_gate(GateResult("a1", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.80)
        assert "b1" in decision.blocking_failures
        assert "a1" in decision.advisory_failures

    def test_passing_gate_not_in_any_failure_list(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("ok_gate", passed=True))
        engine.add_gate(GateResult("b1", passed=False, blocking=True))
        decision = engine.decide(quality_score=0.85)
        assert "ok_gate" not in decision.blocking_failures
        assert "ok_gate" not in decision.advisory_failures

    def test_mixed_passed_is_false(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("blocker", passed=False, blocking=True))
        engine.add_gate(GateResult("advisory", passed=False, blocking=False))
        decision = engine.decide(quality_score=0.90)
        assert decision.passed is False

    def test_quality_score_preserved_in_decision(self):
        engine = DecisionEngine()
        engine.add_gate(GateResult("g1", passed=True))
        decision = engine.decide(quality_score=0.734)
        assert abs(decision.quality_score - 0.734) < 1e-9


# ── TestCreateEngine ───────────────────────────────────────────────────────────


class TestCreateEngine:
    def test_returns_decision_engine(self):
        engine = create_engine()
        assert isinstance(engine, DecisionEngine)

    def test_fresh_engine_has_no_gates(self):
        engine = create_engine()
        decision = engine.decide(quality_score=1.0)
        assert decision.gate_results == []

    def test_two_engines_are_independent(self):
        e1 = create_engine()
        e2 = create_engine()
        e1.add_gate(GateResult("only_in_e1", passed=False, blocking=True))
        d2 = e2.decide(quality_score=0.90)
        assert d2.verdict == "CERTIFIED"

    def test_fluent_chaining(self):
        engine = create_engine()
        returned = engine.add_gate(GateResult("g1", passed=True))
        assert returned is engine

    def test_notes_preserved_in_decision(self):
        engine = create_engine()
        decision = engine.decide(quality_score=0.80, notes="pipeline run 42")
        assert decision.notes == "pipeline run 42"

    def test_created_at_is_non_empty_string(self):
        engine = create_engine()
        decision = engine.decide(quality_score=0.80)
        assert isinstance(decision.created_at, str)
        assert len(decision.created_at) > 0
