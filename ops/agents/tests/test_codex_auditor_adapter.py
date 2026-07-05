"""Tests for codex_auditor_adapter.py — three-tier auditor chain."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from ops.agents.codex_auditor_adapter import (
    CodexAuditRequest,
    CodexAuditResult,
    run_codex_audit,
    _parse_findings,
    _auditor_chain,
    _run_preflight,
)


def _sample_request() -> CodexAuditRequest:
    return CodexAuditRequest(
        task_id="test-001",
        objective="Fix Redis connection",
        files_changed=["ops/scheduler/task_scheduler.py"],
        evidence_files=["aims_workspace/test/evidence.json"],
        test_logs=["pytest: 5 passed"],
        actor_output="Fixed the Redis connection by updating the URL.",
        self_check_output='{"status": "PASS", "findings": []}',
        constraints=["No Docker IPs", "No host port publishing"],
    )


def _make_proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


def _chain_override(primary_rc=13, secondary_rc=13, bedrock_rc=13,
                    primary_stdout="", secondary_stdout="", bedrock_stdout=""):
    """
    Patch subprocess.run to simulate the three-stage preflight chain.
    primary_rc, secondary_rc, bedrock_rc are preflight exit codes.
    """
    calls = iter([
        _make_proc(primary_rc, primary_stdout),
        _make_proc(secondary_rc, secondary_stdout),
        _make_proc(bedrock_rc, bedrock_stdout),
    ])
    return patch("subprocess.run", side_effect=lambda *a, **kw: next(calls))


# ─── chain ordering ─────────────────────────────────────────────────────────

def test_adapter_tries_primary_first(tmp_path):
    """Adapter must try primary auditor before secondary or Bedrock."""
    preflight_calls = []

    def mock_run(cmd, **kwargs):
        preflight_calls.append(cmd)
        return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')

    with patch("subprocess.run", side_effect=mock_run):
        result = run_codex_audit(_sample_request(), str(tmp_path))

    # At least the primary launcher was first
    assert len(preflight_calls) >= 1
    assert "primary" in preflight_calls[0][0].lower() or "codex_auditor_primary" in preflight_calls[0][0]


def test_adapter_falls_back_to_secondary_when_primary_unavailable(tmp_path):
    """When primary returns NOT_CONFIGURED, secondary must be tried."""
    call_order = []

    def mock_run(cmd, **kwargs):
        call_order.append(Path(cmd[0]).name)
        return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')

    with patch("subprocess.run", side_effect=mock_run):
        run_codex_audit(_sample_request(), str(tmp_path))

    names = [n for n in call_order if "codex_auditor" in n or "bedrock" in n]
    assert len(names) >= 2


def test_adapter_falls_back_to_bedrock_when_both_codex_unavailable(tmp_path):
    """When both Codex launchers fail, Claude Bedrock must be tried."""
    call_order = []

    def mock_run(cmd, **kwargs):
        call_order.append(Path(cmd[0]).name)
        return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')

    with patch("subprocess.run", side_effect=mock_run):
        run_codex_audit(_sample_request(), str(tmp_path))

    assert any("bedrock" in n.lower() for n in call_order)


# ─── wrong binary rejection ──────────────────────────────────────────────────

def test_wrong_codex_binary_rejected_preflight_returns_11(tmp_path):
    """WRONG_BINARY (exit 11) causes adapter to skip to next auditor."""
    call_order = []

    def mock_run(cmd, **kwargs):
        call_order.append(cmd[0])
        return _make_proc(returncode=11, stdout='{"status":"WRONG_BINARY"}')

    with patch("subprocess.run", side_effect=mock_run):
        result = run_codex_audit(_sample_request(), str(tmp_path))

    # WRONG_BINARY must not be accepted — all skipped → SKIPPED
    assert result.status == "SKIPPED"
    assert result.auditor_name == "none"


def test_npx_codex_static_site_generator_not_selected(tmp_path):
    """
    The adapter must never call `npx codex` directly.
    It only calls configured launcher scripts.
    """
    called_commands = []

    def mock_run(cmd, **kwargs):
        called_commands.append(cmd)
        return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')

    with patch("subprocess.run", side_effect=mock_run):
        run_codex_audit(_sample_request(), str(tmp_path))

    # No call should use 'npx' or raw 'codex' directly
    for cmd in called_commands:
        assert "npx" not in cmd[0], f"Adapter called npx: {cmd}"
        assert cmd[0].endswith("codex") is False or "/" in cmd[0], \
            f"Adapter called bare codex from PATH: {cmd}"


# ─── auth required ───────────────────────────────────────────────────────────

def test_auth_required_does_not_hang(tmp_path):
    """AUTH_REQUIRED (exit 10) must be returned quickly without hanging."""
    def mock_run(cmd, **kwargs):
        return _make_proc(returncode=10, stdout='{"status":"AUTH_REQUIRED","auth_required":true}')

    with patch("subprocess.run", side_effect=mock_run):
        result = run_codex_audit(_sample_request(), str(tmp_path), timeout_seconds=5)

    assert result.status == "SKIPPED"  # all auditored returned AUTH_REQUIRED → SKIPPED


def test_no_login_command_executed(tmp_path):
    """Adapter must never call sso login, browser auth, or device auth."""
    called_commands = []

    def mock_run(cmd, **kwargs):
        called_commands.append(cmd)
        return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')

    with patch("subprocess.run", side_effect=mock_run):
        run_codex_audit(_sample_request(), str(tmp_path))

    for cmd in called_commands:
        cmd_str = " ".join(str(c) for c in cmd)
        assert "sso login" not in cmd_str
        assert "browser" not in cmd_str
        assert "device" not in cmd_str


# ─── fallback auditor used when primary fails ────────────────────────────────

def test_fallback_used_and_result_returned(tmp_path):
    """When primary fails preflight, secondary is used and its result returned."""
    audit_json = json.dumps({
        "status": "PASSED",
        "findings": [],
        "recommended_next_action": "None",
    })

    call_n = [0]

    def mock_run(cmd, **kwargs):
        call_n[0] += 1
        name = Path(cmd[0]).name
        if "primary" in name:
            return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')
        if "secondary" in name:
            if "--preflight" in cmd:
                return _make_proc(returncode=0, stdout='{"status":"AVAILABLE"}')
            return _make_proc(returncode=0, stdout=audit_json)
        return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')

    with patch("subprocess.run", side_effect=mock_run):
        result = run_codex_audit(_sample_request(), str(tmp_path))

    assert result.status == "PASSED"
    assert result.auditor_name == "secondary_codex"


# ─── raw output saved ────────────────────────────────────────────────────────

def test_raw_output_saved(tmp_path):
    """Raw auditor output must be saved even when JSON is invalid."""
    raw = "This is plain text, not JSON"
    call_n = [0]

    def mock_run(cmd, **kwargs):
        name = Path(cmd[0]).name
        if "--preflight" in cmd:
            if "primary" in name:
                return _make_proc(0, '{"status":"AVAILABLE"}')
            return _make_proc(13, '{"status":"NOT_CONFIGURED"}')
        return _make_proc(0, raw)

    with patch("subprocess.run", side_effect=mock_run):
        result = run_codex_audit(_sample_request(), str(tmp_path))

    assert result.raw_output_path is not None
    saved = Path(result.raw_output_path).read_text()
    assert raw in saved


# ─── JSON parsing ────────────────────────────────────────────────────────────

def test_invalid_json_becomes_warn_finding():
    status, findings = _parse_findings("not json at all")
    assert status == "WARN"
    assert any("not valid JSON" in f.finding for f in findings)


def test_blocking_finding_parsed():
    raw = json.dumps({
        "status": "BLOCKED",
        "findings": [{
            "severity": "BLOCKING",
            "category": "tests",
            "finding": "Tests are failing",
            "recommendation": "Fix failing tests",
            "evidence_reference": None,
        }],
    })
    status, findings = _parse_findings(raw)
    assert status == "BLOCKED"
    assert findings[0].severity == "BLOCKING"


def test_markdown_fences_stripped():
    raw = '```json\n{"status": "PASSED", "findings": []}\n```'
    status, findings = _parse_findings(raw)
    assert status == "PASSED"
    assert findings == []


# ─── SKIPPED when all unavailable ────────────────────────────────────────────

def test_all_unavailable_returns_skipped(tmp_path):
    def mock_run(cmd, **kwargs):
        return _make_proc(returncode=13, stdout='{"status":"NOT_CONFIGURED"}')

    with patch("subprocess.run", side_effect=mock_run):
        result = run_codex_audit(_sample_request(), str(tmp_path))

    assert result.status == "SKIPPED"
    assert result.auditor_available is False


# ─── verifier remains final authority (integration with learning recorder) ───

def test_learning_event_not_eligible_without_verifier(tmp_path):
    """Confirmed via verified_learning_event_recorder — not adapter's job,
    but adapter must not claim training_eligible."""
    from ops.agents.verified_learning_event_recorder import record_learning_event, LearningEventInput

    ev_file = tmp_path / "events.jsonl"
    with patch("ops.agents.verified_learning_event_recorder._INBOX", tmp_path):
        with patch("ops.agents.verified_learning_event_recorder._EVENTS_FILE", ev_file):
            event = record_learning_event(LearningEventInput(
                task_id="t1",
                user_request="test",
                actor_initial_output="bad",
                actor_final_output="good",
                self_check_result={},
                codex_audit_result={"status": "SKIPPED"},
                verifier_result={"status": "VERIFIER_UNAVAILABLE"},
                correction_summary="",
                mistake_class=None,
                evidence_dir=str(tmp_path),
            ))
    assert event["training_eligible"] is False
