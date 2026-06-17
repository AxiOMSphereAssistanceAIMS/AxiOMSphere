"""
test_chain_project_control.py

Covers the project control plane chain:
  logi_controlled_autonomy_status → pipeline_coordinator → project_audit_evidence

All tests are STATIC — they read existing files and check invariants.
No services are started, no HTTP calls are made, no containers are required.
"""
import json
import os
from pathlib import Path

import pytest

# Root of the AIMS workspace, resolved relative to this test file.
AIMS_ROOT = Path(__file__).parent.parent.parent.resolve()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def autonomy_status() -> dict:
    """Parse and return the current logi controlled autonomy status JSON."""
    status_path = AIMS_ROOT / "aims_workspace" / "logi_controlled_autonomy_status" / "current_status.json"
    assert status_path.exists(), f"Autonomy status file missing: {status_path}"
    with status_path.open() as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_autonomy_status_file_exists_and_parseable(autonomy_status):
    """aims_workspace/logi_controlled_autonomy_status/current_status.json must exist and parse."""
    # The fixture already asserts existence and parses — reaching here means both pass.
    assert isinstance(autonomy_status, dict), "Status file must parse to a JSON object"
    assert len(autonomy_status) > 0, "Status object must not be empty"


def test_autonomy_mode_is_controlled(autonomy_status):
    """The mode field must equal CONTROLLED_AUTONOMY."""
    mode = autonomy_status.get("mode")
    assert mode == "CONTROLLED_AUTONOMY", (
        f"Expected mode='CONTROLLED_AUTONOMY', got '{mode}'. "
        "The system must be in controlled autonomy state."
    )


def test_next_scheduled_night_certification_is_valid_iso(autonomy_status):
    """next_scheduled_night_certification must be a non-empty string resembling an ISO timestamp."""
    ts = autonomy_status.get("next_scheduled_night_certification", "")
    assert isinstance(ts, str) and len(ts) >= 10, (
        f"next_scheduled_night_certification is missing or too short: '{ts}'"
    )
    # Must contain 'T' separator (ISO 8601) and at least a date portion.
    assert "T" in ts or ts.count("-") >= 2, (
        f"next_scheduled_night_certification does not look like an ISO timestamp: '{ts}'"
    )


def test_pipeline_coordinator_wiring_file_present():
    """ops/core/pipeline_coordinator.py must exist (required by SA11 project control check)."""
    coord_path = AIMS_ROOT / "ops" / "core" / "pipeline_coordinator.py"
    assert coord_path.exists(), (
        f"Pipeline coordinator missing at {coord_path}. "
        "SA11 requires ops/core/pipeline_coordinator.py for project control plane wiring."
    )


def test_project_audits_directory_has_runs():
    """aims_workspace/project_audits/ must exist and contain at least one completed run."""
    audits_dir = AIMS_ROOT / "aims_workspace" / "project_audits"
    assert audits_dir.exists(), f"Project audits directory missing: {audits_dir}"
    run_dirs = [d for d in audits_dir.iterdir() if d.is_dir()]
    assert len(run_dirs) >= 1, (
        f"No audit run directories found in {audits_dir}. "
        "At least one completed audit run is required."
    )


def test_each_audit_run_has_final_gate_decision():
    """Every audit run directory must contain final_gate_decision.json."""
    audits_dir = AIMS_ROOT / "aims_workspace" / "project_audits"
    run_dirs = [d for d in audits_dir.iterdir() if d.is_dir()]
    assert run_dirs, f"No run dirs in {audits_dir}"
    missing = [
        str(d) for d in run_dirs
        if not (d / "final_gate_decision.json").exists()
    ]
    assert not missing, (
        f"The following audit run dirs are missing final_gate_decision.json:\n"
        + "\n".join(missing)
    )
