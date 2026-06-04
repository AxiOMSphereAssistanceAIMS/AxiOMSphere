"""
AIMS Self-Learning — Pre-Production Certification Pack Schema.

Defines the data structure for the Phase 15 certification dossier.
No model calls, no I/O, no activation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CERTIFICATION_STATUS_READY_BLOCKED = "PRE_PRODUCTION_CERTIFICATION_READY_WITH_RUNTIME_BLOCKED"
CERTIFICATION_STATUS_READY = "PRE_PRODUCTION_CERTIFICATION_READY"
CERTIFICATION_STATUS_BLOCKED = "PRE_PRODUCTION_CERTIFICATION_BLOCKED"
CERTIFICATION_SCHEMA_VERSION = "1.0"

PHASES_COVERED = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]

FINAL_RECOMMENDATION = (
    "Ready for human review and controlled runtime-activation planning. "
    "Not ready for production activation. "
    "Runtime remains blocked by design."
)

# Go/No-Go matrix categories (18)
GO_NO_GO_CATEGORIES = (
    "phase_coverage_complete",
    "smoke_tests_all_pass",
    "direct_workflows_all_pass",
    "phase5_skill_patterns_collected",
    "phase6_candidate_skills_generated",
    "phase7_evaluation_suite_ready",
    "phase8_evaluation_results_available",
    "phase9_sandbox_executions_verified",
    "phase10_certifications_generated",
    "phase11_staged_registry_built",
    "phase12_activation_proposals_generated",
    "phase13_approval_gate_all_blocked",
    "phase14_binding_simulation_all_blocked",
    "runtime_activation_blocked",
    "active_registry_unchanged",
    "agent_behavior_unchanged",
    "human_decisions_required_documented",
    "safety_confirmations_all_pass",
)

# Safety confirmation items (20)
SAFETY_CONFIRMATION_ITEMS = (
    "no_skill_activated",
    "no_active_runtime_registry_modified",
    "no_agent_behavior_modified",
    "no_model_endpoints_called",
    "no_service_restarted",
    "no_hermes_runtime_invoked",
    "no_secrets_accessed",
    "no_external_sends_performed",
    "no_training_or_eval_launched",
    "no_model_load_or_unload",
    "no_self_approval_granted",
    "approval_gate_all_blocked",
    "binding_simulation_all_blocked",
    "runtime_activation_allowed_false_all",
    "dgx_slot120_policy_preserved",
    "forbidden_controls_absent",
    "forbidden_governors_absent",
    "dry_run_only_requested_state",
    "human_review_required_before_activation",
    "rollback_plans_documented",
)


@dataclass
class PreproductionCertificationPack:
    certification_id: str
    created_at: str
    certification_status: str
    runtime_activation_status: str
    phases_covered: list[int]
    phase_artifacts: dict[str, Any]
    smoke_results: dict[str, Any]
    direct_workflow_summaries: dict[str, Any]
    safety_confirmations: dict[str, bool]
    unresolved_blockers: list[str]
    unresolved_warnings: list[str]
    go_no_go_matrix: dict[str, bool]
    activation_blockers: list[str]
    rollback_readiness: dict[str, Any]
    audit_trail_paths: list[str]
    required_human_decisions_before_runtime: list[str]
    final_recommendation: str = FINAL_RECOMMENDATION
    schema_version: str = CERTIFICATION_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid_statuses = {
            CERTIFICATION_STATUS_READY_BLOCKED,
            CERTIFICATION_STATUS_READY,
            CERTIFICATION_STATUS_BLOCKED,
        }
        if self.certification_status not in valid_statuses:
            raise ValueError(
                f"Invalid certification_status: {self.certification_status!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "certification_id": self.certification_id,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "certification_status": self.certification_status,
            "runtime_activation_status": self.runtime_activation_status,
            "phases_covered": self.phases_covered,
            "phase_artifacts": self.phase_artifacts,
            "smoke_results": self.smoke_results,
            "direct_workflow_summaries": self.direct_workflow_summaries,
            "safety_confirmations": self.safety_confirmations,
            "unresolved_blockers": self.unresolved_blockers,
            "unresolved_warnings": self.unresolved_warnings,
            "go_no_go_matrix": self.go_no_go_matrix,
            "activation_blockers": self.activation_blockers,
            "rollback_readiness": self.rollback_readiness,
            "audit_trail_paths": self.audit_trail_paths,
            "required_human_decisions_before_runtime": self.required_human_decisions_before_runtime,
            "final_recommendation": self.final_recommendation,
            "metadata": self.metadata,
        }
