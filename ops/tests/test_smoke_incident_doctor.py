"""Smoke tests for IncidentDoctor (M-003 + M-010) — argus_crash_incident_doctor skill."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from ops.argus.incident_doctor import (
    CLOSURE_ESCALATED,
    CLOSURE_FAILED_LIMIT,
    CLOSURE_REPAIRED,
    CLOSURE_WAITING_HUMAN,
    ROUTE_CLOSED_SELF_HEALED,
    ROUTE_HERMES_ANALYSIS,
    ROUTE_HUMAN_ESCALATION,
    ROUTE_REPAIRMAN_FIX,
    ROUTE_REPAIRMAN_INSPECT,
    DoctorVerdict,
    IncidentDoctor,
    _classify_root_cause,
    get_doctor,
)
from ops.argus.repair_ledger import MAX_RETRY_BUDGET


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_incident(**kwargs) -> dict:
    base = {
        "incident_id": "INC-test-001",
        "service_name": "test-service",
        "exit_code": 1,
        "oom_killed": False,
        "thermal_guard_state": "",
        "logs": "",
        "critical_service": False,
        "restart_result": "NOT_ATTEMPTED",
        "post_restart_health": None,
        "event_type": "crash",
    }
    base.update(kwargs)
    return base


def _fresh_ledger(attempts: int = 0, exhausted: bool = False):
    ledger = MagicMock()
    ledger.get_stats.return_value = {
        "total_attempts": attempts,
        "retry_budget_exhausted": exhausted,
    }
    return ledger


# ── root cause classification ─────────────────────────────────────────────────

class TestRootCauseClassification:
    def test_oom_via_flag(self):
        assert _classify_root_cause(_make_incident(oom_killed=True)) == "OOM"

    def test_oom_via_exit_137(self):
        assert _classify_root_cause(_make_incident(exit_code=137)) == "OOM"

    def test_thermal(self):
        assert _classify_root_cause(_make_incident(thermal_guard_state="thermal paused")) == "THERMAL"

    def test_config_error(self):
        assert _classify_root_cause(_make_incident(exit_code=1, logs="no such file or directory")) == "CONFIG_ERROR"

    def test_dependency_failure(self):
        assert _classify_root_cause(_make_incident(exit_code=1, logs="connection refused errno 111")) == "DEPENDENCY_FAILURE"

    def test_ambiguous_exit_zero(self):
        assert _classify_root_cause(_make_incident(exit_code=0)) == "AMBIGUOUS_EXIT_ZERO"

    def test_sigkill(self):
        assert _classify_root_cause(_make_incident(exit_code=130)) == "SIGKILL"

    def test_unknown(self):
        assert _classify_root_cause(_make_incident(exit_code=99)) == "UNKNOWN"


# ── routing decisions ─────────────────────────────────────────────────────────

class TestDoctorRouting:
    def test_self_healed(self):
        doc = IncidentDoctor(ledger=_fresh_ledger())
        inc = _make_incident(restart_result="OK", post_restart_health="OK")
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_CLOSED_SELF_HEALED
        assert v.closure_path == CLOSURE_REPAIRED
        assert not v.hermes_required
        assert not v.human_required

    def test_oom_first_time_inspect(self):
        doc = IncidentDoctor(ledger=_fresh_ledger(attempts=0))
        inc = _make_incident(exit_code=137)
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_REPAIRMAN_INSPECT
        assert v.hermes_required
        assert v.root_cause_category == "OOM"

    def test_oom_critical_repeated_fix(self):
        doc = IncidentDoctor(ledger=_fresh_ledger(attempts=2))
        inc = _make_incident(exit_code=137, critical_service=True)
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_REPAIRMAN_FIX
        assert v.closure_path == CLOSURE_ESCALATED

    def test_thermal_human_escalation(self):
        doc = IncidentDoctor(ledger=_fresh_ledger())
        inc = _make_incident(thermal_guard_state="thermal paused")
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_HUMAN_ESCALATION
        assert v.closure_path == CLOSURE_WAITING_HUMAN
        assert v.human_required

    def test_config_error_repairman_inspect(self):
        doc = IncidentDoctor(ledger=_fresh_ledger())
        inc = _make_incident(exit_code=1, logs="env variable missing config error")
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_REPAIRMAN_INSPECT

    def test_ambiguous_hermes_analysis(self):
        doc = IncidentDoctor(ledger=_fresh_ledger())
        inc = _make_incident(exit_code=0)
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_HERMES_ANALYSIS
        assert v.hermes_required

    def test_critical_unknown_repairman(self):
        doc = IncidentDoctor(ledger=_fresh_ledger())
        inc = _make_incident(exit_code=99, critical_service=True)
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_REPAIRMAN_INSPECT

    def test_budget_exhausted_forces_human_escalation(self):
        doc = IncidentDoctor(ledger=_fresh_ledger(attempts=MAX_RETRY_BUDGET + 1))
        inc = _make_incident(exit_code=137)
        v = doc.examine(inc)
        assert v.routing_decision == ROUTE_HUMAN_ESCALATION
        assert v.closure_path == CLOSURE_FAILED_LIMIT
        assert v.retry_budget_exhausted
        assert v.escalate_immediately

    def test_budget_flag_alone_forces_escalation(self):
        doc = IncidentDoctor(ledger=_fresh_ledger(attempts=0, exhausted=True))
        inc = _make_incident(exit_code=137)
        v = doc.examine(inc)
        assert v.closure_path == CLOSURE_FAILED_LIMIT


# ── verdict structure ─────────────────────────────────────────────────────────

class TestDoctorVerdictStructure:
    def test_verdict_has_required_fields(self):
        doc = IncidentDoctor(ledger=_fresh_ledger())
        v = doc.examine(_make_incident())
        assert isinstance(v, DoctorVerdict)
        assert v.incident_id == "INC-test-001"
        assert v.service_name == "test-service"
        assert v.verdict_at.endswith("Z")
        assert isinstance(v.repair_attempt_count, int)
        assert isinstance(v.hermes_required, bool)
        assert isinstance(v.human_required, bool)

    def test_get_doctor_returns_instance(self):
        assert isinstance(get_doctor(), IncidentDoctor)

    def test_record_verdict_writes_file(self, tmp_path):
        import ops.argus.incident_doctor as mod
        original = mod.DOCTOR_LOG_ROOT
        mod.DOCTOR_LOG_ROOT = tmp_path
        try:
            doc = IncidentDoctor(ledger=_fresh_ledger())
            v = doc.examine(_make_incident())
            p = doc.record_verdict(v)
            assert p.exists()
            import json
            data = json.loads(p.read_text())
            assert data["incident_id"] == "INC-test-001"
        finally:
            mod.DOCTOR_LOG_ROOT = original
