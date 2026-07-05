"""Tests for audited_correction_loop.py"""
import json
import tempfile
from unittest.mock import patch

import pytest

from ops.agents.audited_correction_loop import run_audited_correction_loop, AuditedCorrectionResult
from ops.agents.codex_auditor_adapter import CodexAuditResult, CodexAuditFinding


def _base_context(tmp_path, actor_output="FINAL:\nanswer: OK\nstatus: PASS"):
    return {
        "task_id": "test-loop-001",
        "objective": "Test task",
        "user_request": "show project status",
        "actor_output": actor_output,
        "action_results": [{"type": "test_result", "status": "VERIFIED_PASS"}],
        "policy_context": {"source": "cli"},
        "files_changed": [],
        "evidence_files": [],
        "test_logs": [],
        "constraints": [],
        "evidence_dir": str(tmp_path),
    }


def test_loop_returns_dataclass(tmp_path):
    ctx = _base_context(tmp_path)
    with patch("ops.agents.audited_correction_loop.run_codex_audit",
               return_value=CodexAuditResult(status="SKIPPED", auditor_available=False)):
        with patch("ops.agents.audited_correction_loop._run_verifier",
                   return_value={"status": "VERIFIED_PASS"}):
            result = run_audited_correction_loop(ctx, max_iterations=2)
    assert isinstance(result, AuditedCorrectionResult)
    assert hasattr(result, "status")
    assert hasattr(result, "iterations")
    assert hasattr(result, "learning_events_written")


def test_codex_unavailable_does_not_fail_deterministic_flow(tmp_path):
    """If Codex unavailable (SKIPPED), loop still runs and verifier decides."""
    ctx = _base_context(tmp_path)
    with patch("ops.agents.audited_correction_loop.run_codex_audit",
               return_value=CodexAuditResult(status="SKIPPED", auditor_available=False)):
        with patch("ops.agents.audited_correction_loop._run_verifier",
                   return_value={"status": "VERIFIED_PASS"}):
            result = run_audited_correction_loop(ctx)
    assert result.status == "VERIFIED_PASS"
    assert result.codex_audit_status == "SKIPPED"


def test_codex_blocking_prevents_verified_pass(tmp_path):
    """Unresolved Codex BLOCKING finding blocks VERIFIED_PASS."""
    ctx = _base_context(tmp_path)
    blocking_result = CodexAuditResult(
        status="BLOCKED",
        auditor_available=True,
        findings=[CodexAuditFinding(
            severity="BLOCKING",
            category="safety",
            finding="Destructive action present",
            recommendation="Remove it",
        )],
    )
    with patch("ops.agents.audited_correction_loop.run_codex_audit",
               return_value=blocking_result):
        with patch("ops.agents.audited_correction_loop._run_verifier",
                   return_value={"status": "VERIFIED_PASS"}):
            # No correction_fn → cannot fix → BLOCKED after max_iterations
            result = run_audited_correction_loop(ctx, max_iterations=1)
    assert result.status == "BLOCKED"


def test_loop_stops_at_max_iterations(tmp_path):
    """Loop must not exceed max_iterations."""
    call_count = {"n": 0}
    def mock_audit(req, ev_dir, **kwargs):
        call_count["n"] += 1
        return CodexAuditResult(
            status="BLOCKED",
            auditor_available=True,
            findings=[CodexAuditFinding("BLOCKING", "tests", "still failing", "fix it")],
        )
    ctx = _base_context(tmp_path)
    with patch("ops.agents.audited_correction_loop.run_codex_audit", side_effect=mock_audit):
        with patch("ops.agents.audited_correction_loop._run_verifier",
                   return_value={"status": "VERIFIED_FAIL"}):
            result = run_audited_correction_loop(ctx, max_iterations=2)
    assert result.iterations <= 2
    assert call_count["n"] <= 2


def test_verifier_is_final_authority(tmp_path):
    """Only verifier may set VERIFIED_PASS or VERIFIED_FAIL."""
    ctx = _base_context(tmp_path)
    with patch("ops.agents.audited_correction_loop.run_codex_audit",
               return_value=CodexAuditResult(status="PASSED", auditor_available=True)):
        with patch("ops.agents.audited_correction_loop._run_verifier",
                   return_value={"status": "VERIFIED_FAIL"}):
            result = run_audited_correction_loop(ctx)
    assert result.status == "VERIFIED_FAIL"


def test_partial_when_verifier_unavailable(tmp_path):
    """If verifier not available, result must be PARTIAL, not VERIFIED_PASS."""
    ctx = _base_context(tmp_path)
    with patch("ops.agents.audited_correction_loop.run_codex_audit",
               return_value=CodexAuditResult(status="SKIPPED", auditor_available=False)):
        with patch("ops.agents.audited_correction_loop._run_verifier",
                   return_value={"status": "VERIFIER_UNAVAILABLE"}):
            result = run_audited_correction_loop(ctx)
    assert result.status == "PARTIAL"


def test_learning_event_written_after_verified_mistake(tmp_path):
    """Learning event is written when self-check finds a mistake and verifier confirms."""
    # Actor output with fake output pattern → self-check finds FAKE_OUTPUT
    ctx = _base_context(tmp_path, actor_output="files: 1234 5678 9101")
    events_written = []

    def mock_record(event_input):
        events_written.append(event_input)
        return {}

    with patch("ops.agents.audited_correction_loop.run_codex_audit",
               return_value=CodexAuditResult(status="SKIPPED", auditor_available=False)):
        with patch("ops.agents.audited_correction_loop._run_verifier",
                   return_value={"status": "VERIFIED_FAIL"}):
            with patch("ops.agents.audited_correction_loop.record_learning_event", side_effect=mock_record):
                result = run_audited_correction_loop(ctx)
    assert result.learning_events_written >= 1
    assert len(events_written) >= 1
