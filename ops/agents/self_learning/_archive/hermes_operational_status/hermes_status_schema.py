from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, UTC
from typing import Any
import uuid


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass
class HermesCurrentStatus:
    status_id: str = field(default_factory=lambda: new_id("hermes_status"))
    generated_at: str = field(default_factory=utc_now)
    hermes_agent_id: str = "hermes_external_worker"
    hermes_home: str = "/home/axi_omi_sphere/.hermes-aims-sandbox"
    model: str = "kr/claude-sonnet-4.5"
    provider: str = "custom"
    project_access_mode: str = "ARTIFACT_ONLY"
    tools_enabled: str = ""
    source_confidence: str = "UNVERIFIED"
    artifact_based: bool = True
    live_verified: bool = False
    current_status: str = "IDLE"
    current_phase: str = "NONE"
    current_task_summary: str = "No active Hermes assistance task"
    active_target_agent: str = "repairman"
    active_target_agent_role: str = "policy_bound_executor"
    active_repair_case_id: str | None = None
    active_audit_id: str | None = None
    active_issue_path: str | None = None
    active_log_path: str | None = None
    active_status_artifact: str | None = None
    active_skill_id: str | None = None
    active_skill_name: str | None = None
    active_skill_stage: str = "NONE"
    active_skill_origin: str = "HERMES_INCUBATED"
    active_skill_owner_after_adoption: str = "repairman"
    helping_agent: str = "repairman"
    help_type: str = "REVIEW"
    latest_assistance_request_id: str | None = None
    latest_hermes_prompt_path: str | None = None
    latest_hermes_result_path: str | None = None
    latest_skill_package_id: str | None = None
    latest_skill_test_report_id: str | None = None
    latest_adoption_plan_id: str | None = None
    latest_feedback_event_id: str | None = None
    input_artifacts: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    requests_received: list[str] = field(default_factory=list)
    work_completed: list[str] = field(default_factory=list)
    work_in_progress: list[str] = field(default_factory=list)
    pending_actions: list[str] = field(default_factory=list)
    pending_user_decisions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_action: str = "WAIT_FOR_REPAIRMAN_CASE_OR_USER_TASK"
    safety_constraints: list[str] = field(default_factory=lambda: [
        "Hermes is reviewer/incubator only",
        "No direct file patching",
        "No command execution",
        "No secrets access",
        "No service restart",
        "No model load/unload",
        "No training launch",
    ])
    forbidden_actions: list[str] = field(default_factory=lambda: [
        "patch files",
        "run commands",
        "restart services",
        "load_unload_models",
        "launch_training",
        "access_secrets",
        "become_executor",
        "become_governor",
        "direct_skill_activation",
    ])
    last_update_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ALLOWED_STATUSES = {
    "IDLE",
    "READING_DOSSIER",
    "REVIEWING_REPAIRMAN_FAILURE",
    "GENERATING_ASSISTANCE",
    "CREATING_SKILL_PACKAGE",
    "TESTING_SKILL_IN_SANDBOX",
    "HANDING_OFF_TO_REPAIRMAN",
    "WAITING_FOR_REPAIRMAN_ADOPTION_TEST",
    "WAITING_FOR_SCOPE_APPROVAL",
    "MONITORING_ADOPTED_SKILL",
    "BLOCKED",
    "FAILED",
    "COMPLETED",
}

ALLOWED_SKILL_STAGES = {
    "NONE",
    "DISCOVERED",
    "REVIEW_SUGGESTED",
    "PACKAGE_CREATED",
    "HERMES_SANDBOX_TESTING",
    "HERMES_SANDBOX_PASS",
    "HERMES_SANDBOX_FAIL",
    "HANDED_OFF_TO_REPAIRMAN",
    "REPAIRMAN_ADOPTION_TESTING",
    "ACTIVE_IN_REPAIRMAN",
    "MONITORING",
    "NEEDS_IMPROVEMENT",
}
