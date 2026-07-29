"""Fast Poli checklist for Codex-reviewed Fullstack changes."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Any

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = Path(os.environ.get("AIMS_WORKSPACE", ""))
_CANDIDATE_DECISION_PATHS = (
    _WORKSPACE_ROOT / "agent_architecture_status/poli_policy/project_decisions.json"
    if str(_WORKSPACE_ROOT) not in {"", "."} else Path("/nonexistent"),
    _SOURCE_ROOT / "aims_workspace/agent_architecture_status/poli_policy/project_decisions.json",
    Path("/data/agent_architecture_status/poli_policy/project_decisions.json"),
    Path("/workspace/aims_workspace/agent_architecture_status/poli_policy/project_decisions.json"),
)
DECISIONS_PATH = next((path for path in _CANDIDATE_DECISION_PATHS if path.is_file()), _CANDIDATE_DECISION_PATHS[0])


def load_project_decisions(path: Path = DECISIONS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_evidence_manifest(manifest: dict[str, Any], expected_task_id: str = "") -> bool:
    """Verify the trusted handoff manifest, not caller booleans."""
    if not isinstance(manifest, dict) or not manifest.get("task_id"):
        return False
    if expected_task_id and manifest.get("task_id") != expected_task_id:
        return False
    path = Path(str(manifest.get("manifest_path", "")))
    if not path.is_file():
        return False
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
        if actual.get("task_id") != manifest.get("task_id"):
            return False
        qa = actual.get("qa_result") or actual.get("qa") or {}
        qa_artifact = Path(str(qa.get("artifact", "")))
        if (qa.get("exit_code") != 0 or not isinstance(qa.get("test_count"), int)
                or qa.get("test_count") <= 0 or not qa_artifact.is_file()
                or not qa.get("command") or not qa.get("artifact_sha256")
                or hashlib.sha256(qa_artifact.read_bytes()).hexdigest() != qa.get("artifact_sha256")):
            return False
        final = actual.get("final_report") or {}
        final_path = Path(str(final.get("path", "")))
        if not final_path.is_file() or hashlib.sha256(final_path.read_bytes()).hexdigest() != final.get("sha256"):
            return False
        rollback = actual.get("rollback") or {}
        baseline_dir = Path(str(rollback.get("baseline_dir", "")))
        if (rollback.get("operator_confirmation_required") is not True
                or not baseline_dir.is_dir() or not rollback.get("baseline_inventory")
                or not rollback.get("restore_command")):
            return False
        reviewed = actual.get("reviewed_files", [])
        expected = actual.get("expected_reviewed_files")
        if not reviewed or not expected or sorted(expected) != sorted(str(item.get("path", "")) for item in reviewed):
            return False
        for item in reviewed:
            source = Path(str(item.get("path", "")))
            if not source.is_absolute():
                source = Path.cwd() / source
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != item.get("sha256"):
                return False
        for item in rollback.get("baseline_inventory", []):
            baseline_file = baseline_dir / str(item.get("path", ""))
            if not baseline_file.is_file() or hashlib.sha256(baseline_file.read_bytes()).hexdigest() != item.get("sha256"):
                return False
        handoff = actual.get("implementation_handoff") or {}
        handoff_path = Path(str(handoff.get("path", "")))
        if (not handoff_path.is_file() or hashlib.sha256(handoff_path.read_bytes()).hexdigest() != handoff.get("sha256")
                or json.loads(handoff_path.read_text(encoding="utf-8")).get("implementation_status") not in {"COMPLETED_VERIFIED", "COMPLETED"}):
            return False
        return (actual.get("constraints") or {}).get("production_mutation") is False
    except (OSError, ValueError, TypeError):
        return False


# Paths whose modification a proposal must never self-certify as "clear" —
# an independently checkable fact, not a trusted proposer flag.
_PROTECTED_PATH_PREFIXES = (
    "ops/agents/poli_",
    "ops/self_healing/",
    "ops/docsreg/docsreg_protected_actions_gate.py",
    "ops/scripts/msdg_sequential_promotion_queue.py",
)


def _manifest_touches_protected_path(manifest: dict[str, Any], expected_task_id: str) -> bool | None:
    """True/False from the verified manifest's changed files; None if the manifest itself doesn't verify."""
    if not verify_evidence_manifest(manifest, expected_task_id):
        return None
    path = Path(str(manifest.get("manifest_path", "")))
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    changed = actual.get("changed_files") or actual.get("reviewed_files") or []
    for item in changed:
        rel = str(item.get("path", ""))
        if any(rel.startswith(prefix) for prefix in _PROTECTED_PATH_PREFIXES):
            return True
    return False


def _codex_independently_clean(codex_audit: dict[str, Any]) -> bool:
    """Codex, a separate process from the proposer, reviewed the actual diff
    and reported no BLOCKING finding. This is the closest verifiable stand-in
    this pipeline has for a claim like "concept preserved" or "restorative" —
    self-report from the same analysis that proposed the change is not."""
    if codex_audit.get("status") != "PASSED":
        return False
    return not any(
        str(f.get("severity", "")).upper() == "BLOCKING" for f in codex_audit.get("findings", [])
    )


CHECKLIST = (
    ("codex_pass", "Codex CLI status is PASSED and auditor is available"),
    ("strategy_preserved", "strategy_change is false"),
    ("concept_preserved", "concept_preserved is true"),
    ("restorative", "restorative is true"),
    ("certified_pipeline_compatibility", "certified pipeline regression evidence is PASS"),
    ("provenance_complete", "source/evidence hashes and handoffs are complete"),
    ("rollback_present", "rollback pointer/plan exists"),
    ("production_scope", "production_mutation is false for bounded execution"),
    ("protected_boundary_clear", "no protected project boundary is being mutated"),
)


def build_checklist_packet(
    proposal: dict[str, Any], codex_audit: dict[str, Any], *, decisions: dict[str, Any] | None = None
) -> dict[str, Any]:
    decisions = decisions or load_project_decisions()
    checks: list[dict[str, Any]] = []
    for check_id, description in CHECKLIST:
        evidence_manifest = proposal.get("evidence_manifest") or {}
        task_id = str(proposal.get("task_id", ""))
        has_evidence_text = bool(str(proposal.get(f"{check_id}_evidence", "")).strip())
        if check_id == "codex_pass":
            passed = codex_audit.get("status") == "PASSED" and codex_audit.get("auditor_available") is True
        elif check_id == "strategy_preserved":
            # A proposer claiming "no strategy change" is not itself evidence:
            # require Codex — a separate process reviewing the real diff — to
            # independently corroborate with a clean, non-blocking pass.
            passed = (
                proposal.get("strategy_change") is False
                and _codex_independently_clean(codex_audit)
                and has_evidence_text
            )
        elif check_id in {"concept_preserved", "restorative"}:
            passed = (
                proposal.get(check_id) is True
                and _codex_independently_clean(codex_audit)
                and has_evidence_text
            )
        elif check_id == "production_scope":
            passed = proposal.get("production_mutation") is False
        elif check_id == "protected_boundary_clear":
            touches_protected = _manifest_touches_protected_path(evidence_manifest, task_id)
            passed = (
                touches_protected is False
                and not proposal.get("protected_boundary_mutation", False)
                and has_evidence_text
            )
        elif check_id == "rollback_present":
            # The rollback claim is only real once the manifest's own rollback
            # block (baseline dir, per-file hashes, restore command) verifies
            # against disk — a truthy string is not a rollback.
            passed = (
                bool(proposal.get("rollback_plan"))
                and has_evidence_text
                and verify_evidence_manifest(evidence_manifest, task_id)
            )
        else:
            passed = proposal.get(check_id) is True
            if passed and check_id in {"certified_pipeline_compatibility", "provenance_complete"}:
                evidence = proposal.get("evidence_manifest") or {}
                passed = bool(str(proposal.get(f"{check_id}_evidence", "")).strip()) and (
                    verify_evidence_manifest(evidence, str(proposal.get("task_id", "")))
                )
        checks.append({"id": check_id, "description": description, "status": "PASS" if passed else "BLOCK", "evidence": proposal.get(f"{check_id}_evidence", "")})
    blocked = [item for item in checks if item["status"] != "PASS"]
    return {
        "schema": "aims.poli.checklist_packet.v1",
        "holder": "Poli",
        "technical_auditor": "CodexCLI",
        "decision_matrix_version": decisions.get("version"),
        "checks": checks,
        "decision": "ALLOW" if not blocked else "DENY",
        "allowed": not blocked,
        "blocked_checks": [item["id"] for item in blocked],
        "telegram_action": "result_only_human_summary",
    }


__all__ = ["CHECKLIST", "DECISIONS_PATH", "build_checklist_packet", "load_project_decisions"]
