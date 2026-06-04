from __future__ import annotations

from typing import Any

REQUIRED_DOSSIER_FIELDS = {
    "repair_case_id",
    "created_at",
    "source",
    "trigger_type",
    "trigger_payload_summary",
    "requester",
    "mode",
    "audit_id",
    "policy_gate_results",
    "owner_agent",
    "executing_agent",
    "consultant_agent",
    "repairman_model_slot",
    "repairman_model_requested",
    "repairman_model_resolved",
    "repairman_model_used",
    "hermes_consultant_model",
    "repo_root_used",
    "repo_markers_found",
    "problem_statement",
    "observed_symptoms",
    "expected_behavior",
    "actual_behavior",
    "failure_domain",
    "suspected_root_causes",
    "evidence_refs",
    "issue_file_path",
    "log_file_path",
    "commands_or_tools_used",
    "endpoints_called",
    "files_inspected",
    "files_changed",
    "tests_run",
    "test_results",
    "safety_constraints",
    "forbidden_actions_respected",
    "actions_blocked_by_policy",
    "repair_actions_attempted",
    "repair_actions_not_attempted",
    "outcome_status",
    "remaining_blockers",
    "rollback_notes",
    "lessons_learned",
    "reusable_patterns",
    "candidate_skills",
    "hermes_review_needed",
    "hermes_review_reason",
    "sanitized",
}

ALLOWED_OUTCOMES = {
    "DIAGNOSIS_ONLY",
    "REPAIR_PROPOSED",
    "REPAIR_APPLIED",
    "REPAIR_FAILED",
    "BLOCKED_BY_POLICY",
    "BLOCKED_BY_MODEL",
    "BLOCKED_BY_CONTEXT",
    "INVALID_CONTEXT",
    "NEEDS_HERMES_REVIEW",
}


def validate_dossier_shape(dossier: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_DOSSIER_FIELDS - set(dossier)
    if missing:
        errors.append(f"missing_fields:{','.join(sorted(missing))}")
    if dossier.get("owner_agent") not in {"repairman", "mainy_repairman"}:
        errors.append("owner_agent_invalid")
    if dossier.get("consultant_agent") != "hermes":
        errors.append("consultant_agent_invalid")
    if dossier.get("outcome_status") not in ALLOWED_OUTCOMES:
        errors.append("outcome_status_invalid")
    if dossier.get("mode") == "inspect" and dossier.get("files_changed") not in ([], None):
        errors.append("inspect_mode_files_changed_nonempty")
    if dossier.get("repairman_model_slot") != 32:
        errors.append("repairman_model_slot_not_32")
    return errors
