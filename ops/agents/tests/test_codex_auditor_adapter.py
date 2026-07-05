"""Tests for codex_auditor_adapter.py"""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from ops.agents.codex_auditor_adapter import (
    CodexAuditRequest,
    CodexAuditResult,
    run_codex_audit,
    _parse_findings,
    _detect_auditor,
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


def test_codex_unavailable_returns_skipped(tmp_path):
    """Codex unavailable → SKIPPED without failing deterministic flow."""
    with patch("ops.agents.codex_auditor_adapter._detect_auditor", return_value=None):
        result = run_codex_audit(_sample_request(), str(tmp_path))
    assert result.status == "SKIPPED"
    assert result.auditor_available is False
    assert result.command_used == []


def test_skipped_does_not_raise(tmp_path):
    """SKIPPED result must be returned, never raise."""
    with patch("ops.agents.codex_auditor_adapter._detect_auditor", return_value=None):
        result = run_codex_audit(_sample_request(), str(tmp_path))
    assert isinstance(result, CodexAuditResult)


def test_codex_raw_output_saved(tmp_path):
    """Raw Codex output must be saved to evidence dir."""
    raw_json = json.dumps({
        "status": "PASSED",
        "findings": [],
        "recommended_next_action": "None required",
    })
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = raw_json
    mock_proc.stderr = ""
    with patch("ops.agents.codex_auditor_adapter._detect_auditor", return_value=["fake-auditor"]):
        with patch("subprocess.run", return_value=mock_proc):
            result = run_codex_audit(_sample_request(), str(tmp_path))
    assert result.raw_output_path is not None
    raw_path = tmp_path / "codex_audit_raw.txt"
    assert raw_path.exists()
    assert raw_json in raw_path.read_text()


def test_invalid_json_becomes_warn_finding(tmp_path):
    """Non-JSON Codex output becomes a WARN finding, not an exception."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "This is not JSON at all — just plain text"
    mock_proc.stderr = ""
    with patch("ops.agents.codex_auditor_adapter._detect_auditor", return_value=["fake-auditor"]):
        with patch("subprocess.run", return_value=mock_proc):
            result = run_codex_audit(_sample_request(), str(tmp_path))
    assert result.status == "WARN"
    assert any(f.category == "auditor_format" for f in result.findings)
    assert any("not valid JSON" in f.finding for f in result.findings)


def test_blocking_finding_parsed():
    """BLOCKING severity finding is correctly parsed from JSON."""
    raw = json.dumps({
        "status": "BLOCKED",
        "findings": [{
            "severity": "BLOCKING",
            "category": "tests",
            "finding": "Tests are failing",
            "recommendation": "Fix failing tests before merge",
            "evidence_reference": "pytest.log",
        }],
        "recommended_next_action": "Fix tests",
    })
    status, findings = _parse_findings(raw)
    assert status == "BLOCKED"
    assert len(findings) == 1
    assert findings[0].severity == "BLOCKING"
    assert findings[0].category == "tests"


def test_codex_blocking_finding_signals_blocked(tmp_path):
    """BLOCKING finding from Codex must result in BLOCKED status."""
    raw = json.dumps({
        "status": "BLOCKED",
        "findings": [{"severity": "BLOCKING", "category": "safety",
                       "finding": "Destructive action present",
                       "recommendation": "Remove it", "evidence_reference": None}],
    })
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = raw
    mock_proc.stderr = ""
    with patch("ops.agents.codex_auditor_adapter._detect_auditor", return_value=["fake"]):
        with patch("subprocess.run", return_value=mock_proc):
            result = run_codex_audit(_sample_request(), str(tmp_path))
    assert result.status == "BLOCKED"


def test_markdown_fences_stripped_from_json():
    """JSON wrapped in markdown code fences is still parsed correctly."""
    raw = '```json\n{"status": "PASSED", "findings": []}\n```'
    status, findings = _parse_findings(raw)
    assert status == "PASSED"
    assert findings == []


def test_discovery_file_written_when_unavailable(tmp_path):
    """When Codex unavailable, discovery file explains why."""
    with patch("ops.agents.codex_auditor_adapter._detect_auditor", return_value=None):
        run_codex_audit(_sample_request(), str(tmp_path))
    discovery = tmp_path / "codex_cli_discovery.txt"
    assert discovery.exists()
    content = discovery.read_text()
    assert "NO_USABLE_AUDITOR_FOUND" in content
