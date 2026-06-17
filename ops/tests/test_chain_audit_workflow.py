"""
test_chain_audit_workflow.py

Covers the durable audit workflow chain end-to-end (static):
  subaudits.ts SA1–SA15 → safeExec guard → artifact output

All tests are STATIC — they read existing TypeScript/JSON/Markdown files
and check their content. No services are started, no HTTP calls are made,
no containers are required, no TypeScript compiler is invoked.
"""
import json
import re
from pathlib import Path

import pytest

AIMS_ROOT = Path(__file__).parent.parent.parent.resolve()
AUDIT_SRC = AIMS_ROOT / "ops" / "workflows" / "aims_audit" / "src"
AUDITS_DIR = AIMS_ROOT / "aims_workspace" / "project_audits"

# All 15 sub-audit function names that must appear in subaudits.ts
EXPECTED_SA_FUNCTIONS = [
    "subAuditAgentWiring",
    "subAuditLaunchReadiness",
    "subAuditModelRouting",
    "subAuditBedrock",
    "subAuditSelfLearning",
    "subAuditFullStackSkills",
    "subAuditDocOcr",
    "subAuditEvidence",
    "subAuditSecurity",
    "subAuditRepoHygiene",
    "subAuditProjectControl",
    "subAuditStrategyManagement",
    "subAuditBotPipeline",
    "subAuditSkillManagement",
    "subAuditInterfaceInteractions",
]

# Every completed audit run must contain these artifact files
REQUIRED_ARTIFACTS = [
    "aims_project_audit_report.md",
    "autonomous_launch_blockers.json",
    "final_gate_decision.json",
    "logi_execution_plan.md",
    "repair_tasks_for_repairman.md",
    "traini_learning_materials.md",
    "unmounted_systems_inventory.json",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_audit_workflow_ts_exists():
    """ops/workflows/aims_audit/src/workflows/audit.ts must be present."""
    audit_ts = AUDIT_SRC / "workflows" / "audit.ts"
    assert audit_ts.exists(), f"Audit workflow TypeScript file missing: {audit_ts}"
    assert audit_ts.stat().st_size > 0, "audit.ts must not be empty"


def test_subaudits_ts_contains_all_sa_functions():
    """ops/workflows/aims_audit/src/lib/subaudits.ts must export all SA1–SA15 functions."""
    subaudits = AUDIT_SRC / "lib" / "subaudits.ts"
    assert subaudits.exists(), f"subaudits.ts missing: {subaudits}"
    content = subaudits.read_text(encoding="utf-8")
    missing = [fn for fn in EXPECTED_SA_FUNCTIONS if fn not in content]
    assert not missing, (
        f"The following SA function names are missing from subaudits.ts:\n"
        + "\n".join(f"  - {fn}" for fn in missing)
    )


def test_safe_exec_has_no_bare_bedrock_pattern():
    """SA4 fix: safeExec.ts must NOT contain the broad bare /bedrock/i deny pattern.

    The old pattern `/bedrock/i` was too broad — it blocked legitimate path-contains
    checks like `ls /path/to/bedrock/`. The fix narrowed it to `aws\\s+bedrock\\b`.
    """
    safe_exec = AUDIT_SRC / "lib" / "safeExec.ts"
    assert safe_exec.exists(), f"safeExec.ts missing: {safe_exec}"
    content = safe_exec.read_text(encoding="utf-8")
    # The bare pattern would appear as: /bedrock/i  (a JS regex literal, not inside a string)
    # We scan for it as a standalone regex literal token.
    bare_pattern = re.compile(r"/bedrock/i")
    assert not bare_pattern.search(content), (
        "SA4 fix not applied: safeExec.ts still contains the broad /bedrock/i deny pattern. "
        "This pattern blocks legitimate path checks. Replace with /aws\\s+bedrock\\b/i."
    )


def test_safe_exec_has_narrowed_aws_bedrock_pattern():
    """SA4 fix: safeExec.ts must contain the narrowed 'aws.*bedrock' deny pattern."""
    safe_exec = AUDIT_SRC / "lib" / "safeExec.ts"
    assert safe_exec.exists(), f"safeExec.ts missing: {safe_exec}"
    content = safe_exec.read_text(encoding="utf-8")
    # The narrowed pattern in the deny list should look like: /aws\s+bedrock\b/i
    # We match any variant of aws+bedrock in a deny context.
    assert re.search(r"aws.*bedrock", content, re.IGNORECASE), (
        "SA4 fix missing: safeExec.ts does not contain a narrowed 'aws.*bedrock' deny pattern. "
        "Expected something like /aws\\s+bedrock\\b/i in DENY_PATTERNS."
    )


def test_project_audits_has_at_least_one_completed_run():
    """aims_workspace/project_audits/ must have at least one completed run directory."""
    assert AUDITS_DIR.exists(), f"Project audits directory missing: {AUDITS_DIR}"
    run_dirs = [d for d in AUDITS_DIR.iterdir() if d.is_dir()]
    assert len(run_dirs) >= 1, (
        f"No completed audit run directories found in {AUDITS_DIR}"
    )


def test_latest_audit_run_has_all_required_artifacts():
    """The most recent audit run directory must contain all 7 required artifact files."""
    assert AUDITS_DIR.exists(), f"Project audits directory missing: {AUDITS_DIR}"
    run_dirs = sorted(
        [d for d in AUDITS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.name
    )
    assert run_dirs, f"No audit run dirs in {AUDITS_DIR}"
    latest = run_dirs[-1]
    missing = [art for art in REQUIRED_ARTIFACTS if not (latest / art).exists()]
    assert not missing, (
        f"Latest audit run '{latest.name}' is missing required artifacts:\n"
        + "\n".join(f"  - {art}" for art in missing)
    )
