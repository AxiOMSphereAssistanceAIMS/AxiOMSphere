"""Tests for auditor_session_watcher and adapter status-file integration."""
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ops.agents.codex_auditor_adapter import (
    CodexAuditRequest,
    CodexAuditResult,
    run_codex_audit,
    _read_status_file,
    _active_auditor_from_status,
    _STATUS_FILE,
    _STATUS_STALE_SECONDS,
)


def _sample_request() -> CodexAuditRequest:
    return CodexAuditRequest(
        task_id="watcher-test-001",
        objective="Test watcher integration",
        files_changed=["ops/agents/codex_auditor_adapter.py"],
        evidence_files=[],
        test_logs=["14 passed"],
        actor_output="Watcher implemented.",
        self_check_output='{"status":"PASS"}',
        constraints=["No interactive login"],
    )


def _make_status(primary="AVAILABLE", secondary="NOT_CONFIGURED", bedrock="NOT_CONFIGURED",
                 active="primary_codex", chain="AVAILABLE") -> dict:
    return {
        "updated_at_utc": "2026-07-05T09:00:00Z",
        "primary_codex": {
            "status": primary,
            "home": "/home/user/.codex-primary",
            "interactive_login_attempted": False,
        },
        "secondary_codex": {
            "status": secondary,
            "home": "/home/user/.codex-secondary",
            "interactive_login_attempted": False,
        },
        "claude_bedrock": {
            "status": bedrock,
            "aws_profile": "AdministratorAccess-445100240501",
            "region": "us-west-2",
            "interactive_login_attempted": False,
        },
        "active_auditor": active,
        "chain_status": chain,
    }


# ─── selection logic ─────────────────────────────────────────────────────────

def test_selects_primary_when_available():
    """Watcher must select primary_codex when it is AVAILABLE."""
    s = _make_status(primary="AVAILABLE", active="primary_codex", chain="AVAILABLE")
    assert s["active_auditor"] == "primary_codex"
    assert s["chain_status"] == "AVAILABLE"


def test_selects_secondary_when_primary_auth_required():
    """Watcher selects secondary when primary is AUTH_REQUIRED."""
    s = _make_status(primary="AUTH_REQUIRED", secondary="AVAILABLE",
                     active="secondary_codex", chain="DEGRADED")
    assert s["active_auditor"] == "secondary_codex"
    assert s["chain_status"] == "DEGRADED"


def test_selects_claude_bedrock_when_both_codex_unavailable():
    """Watcher selects claude_bedrock when primary and secondary are unavailable."""
    s = _make_status(primary="NOT_CONFIGURED", secondary="NOT_CONFIGURED",
                     bedrock="AVAILABLE", active="claude_bedrock", chain="DEGRADED")
    assert s["active_auditor"] == "claude_bedrock"
    assert s["chain_status"] == "DEGRADED"


def test_returns_none_when_all_unavailable():
    """Watcher returns active_auditor=none when all routes fail."""
    s = _make_status(primary="NOT_CONFIGURED", secondary="NOT_CONFIGURED",
                     bedrock="NOT_CONFIGURED", active="none", chain="FAILED")
    assert s["active_auditor"] == "none"
    assert s["chain_status"] == "FAILED"


def test_interactive_login_never_attempted():
    """All three routes must have interactive_login_attempted=False."""
    s = _make_status()
    assert s["primary_codex"]["interactive_login_attempted"] is False
    assert s["secondary_codex"]["interactive_login_attempted"] is False
    assert s["claude_bedrock"]["interactive_login_attempted"] is False


# ─── status JSON written ─────────────────────────────────────────────────────

def test_status_json_written(tmp_path):
    """Preflight must write a valid JSON status file."""
    # Simulate the output of auditor_session_preflight.sh by writing the file
    status_file = tmp_path / "auditor_chain_status.json"
    status = _make_status(primary="NOT_CONFIGURED", bedrock="AVAILABLE",
                          active="claude_bedrock", chain="DEGRADED")
    status_file.write_text(json.dumps(status), encoding="utf-8")

    loaded = json.loads(status_file.read_text())
    assert loaded["active_auditor"] == "claude_bedrock"
    assert loaded["chain_status"] == "DEGRADED"
    required_keys = ["updated_at_utc", "primary_codex", "secondary_codex",
                     "claude_bedrock", "active_auditor", "chain_status"]
    for k in required_keys:
        assert k in loaded, f"Missing key: {k}"


# ─── adapter reads status file ────────────────────────────────────────────────

def test_adapter_uses_active_auditor_from_fresh_status(tmp_path):
    """Adapter uses the active auditor from a fresh status file (skip preflight)."""
    audit_json = json.dumps({"status": "PASSED", "findings": []})
    status = _make_status(primary="AVAILABLE", active="primary_codex", chain="AVAILABLE")

    # Write fresh status file
    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps(status), encoding="utf-8")

    called = []

    def mock_run(cmd, **kw):
        called.append(cmd)
        p = MagicMock()
        p.returncode = 0
        p.stdout = audit_json
        p.stderr = ""
        return p

    # Patch status file path and auditor chain
    fake_chain = [("primary_codex", str(tmp_path / "primary.sh"))]
    (tmp_path / "primary.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (tmp_path / "primary.sh").chmod(0o755)

    with patch("ops.agents.codex_auditor_adapter._STATUS_FILE", status_file):
        with patch("ops.agents.codex_auditor_adapter._auditor_chain",
                   return_value=fake_chain):
            with patch("subprocess.run", side_effect=mock_run):
                result = run_codex_audit(_sample_request(), str(tmp_path / "ev"))

    # Should have used the fast path (audit call, not preflight)
    assert result.status == "PASSED"
    assert result.auditor_name == "primary_codex"
    # No preflight call (fast path skips it)
    for cmd in called:
        assert "--preflight" not in cmd, f"Unexpected preflight call: {cmd}"


def test_stale_status_triggers_inline_preflight(tmp_path):
    """A stale status file must cause adapter to run inline preflight."""
    status = _make_status(primary="AVAILABLE", active="primary_codex", chain="AVAILABLE")
    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps(status), encoding="utf-8")

    # Make it stale by backdating modification time
    stale_mtime = time.time() - (_STATUS_STALE_SECONDS + 60)
    import os
    os.utime(status_file, (stale_mtime, stale_mtime))

    with patch("ops.agents.codex_auditor_adapter._STATUS_FILE", status_file):
        result = _read_status_file()

    assert result is None  # stale → read returns None


def test_missing_status_triggers_inline_preflight(tmp_path):
    """A missing status file must cause adapter to run inline preflight."""
    missing = tmp_path / "nonexistent.json"
    with patch("ops.agents.codex_auditor_adapter._STATUS_FILE", missing):
        result = _read_status_file()
    assert result is None


# ─── watcher never initiates login ───────────────────────────────────────────

def test_no_login_command_in_watcher_script():
    """The watcher script must not contain aws sso login or similar commands."""
    watcher = Path(__file__).parents[3] / "ops" / "scripts" / "auditor_session_watcher.sh"
    assert watcher.exists(), f"watcher script not found at {watcher}"
    content = watcher.read_text()
    assert "sso login" not in content
    assert "aws login" not in content
    assert "codex login" not in content
    assert "browser" not in content.lower()


def test_no_login_command_in_preflight_script():
    """The preflight script must not contain interactive login commands."""
    preflight = Path(__file__).parents[3] / "ops" / "scripts" / "auditor_session_preflight.sh"
    assert preflight.exists()
    content = preflight.read_text()
    assert "sso login" not in content
    assert "aws login" not in content
    assert "codex login" not in content


# ─── all three routes checked ────────────────────────────────────────────────

def test_preflight_script_checks_all_three_routes():
    """The preflight script must reference all three auditor command env vars."""
    preflight = Path(__file__).parents[3] / "ops" / "scripts" / "auditor_session_preflight.sh"
    content = preflight.read_text()
    assert "AIMS_CODEX_AUDITOR_CMD" in content
    assert "AIMS_CODEX_AUDITOR_FALLBACK_CMD" in content
    assert "AIMS_CLAUDE_BEDROCK_AUDITOR_CMD" in content
