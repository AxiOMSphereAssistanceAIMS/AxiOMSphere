from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

# Phase 1 Skill: failure-triage
try:
    from ops.ecc_skills.phase_1_failure.failure_triage import FailureTriage
    ECC_FAILURE_TRIAGE_AVAILABLE = True
except ImportError:
    ECC_FAILURE_TRIAGE_AVAILABLE = False


AUTO_ALLOWED = {
    "create_missing_output_directory",
    "generate_nonsecret_default_config",
    "fix_generated_wrapper_contract_arg",
    "retry_transient_network_tool_call",
    "rerun_failed_validation",
    "regenerate_missing_evidence_from_safe_data",
    "update_planned_action_metadata_no_runtime_change",
    "start_required_service_if_safe",
    "rerun_transient_check",
}

APPROVAL_REQUIRED = {
    "service_restart",
    "docker_compose_restart",
    "docker_compose_up_down",
    "model_unload_load",
    "schedule_change_active_longrun",
    "file_ownership_permission_change",
    "runtime_routing_change",
    "environment_config_change",
    "promotion_or_deployment_change",
    "protected_service_restart",
    "active_schedule_override",
}

QUEUE_OR_RESCHEDULE = {
    "queue_after_active_run",
    "reschedule_to_safe_window",
    "skip_as_policy_expected",
    "run_lightweight_only",
}

FORBIDDEN = {
    "expose_or_write_secrets",
    "delete_data",
    "rm_rf",
    "force_load_slot120",
    "create_slot32_slot120_conflict",
    "bypass_qa_poli_release_gates",
    "mark_failed_validation_as_pass",
    "fake_artifacts",
    "unsafe_model_promotion",
}


# Phase 1 Skill: failure-triage initialization
_failure_triage = None


def _init_failure_triage() -> None:
    """Initialize Phase 1 failure-triage skill."""
    global _failure_triage
    if ECC_FAILURE_TRIAGE_AVAILABLE:
        try:
            _failure_triage = FailureTriage()
        except Exception:
            _failure_triage = None


@dataclass
class RepairPolicyDecision:
    repair_type: str
    policy_class: str
    safe_to_auto_repair: bool
    requires_poli_approval: bool
    forbidden: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _enhance_repair_classification_with_failure_triage(
    repair_type: str, context: dict | None = None
) -> dict[str, Any]:
    """Apply Phase 1 failure-triage skill to enhance classification.

    Args:
        repair_type: The repair type to classify
        context: Optional context dict for triage analysis

    Returns:
        Enhanced context dict with failure triage analysis
    """
    if not _failure_triage:
        return context or {}

    try:
        failure_message = ""
        if context:
            failure_message = str(
                context.get("failure_message")
                or context.get("error_message")
                or context.get("description")
                or context.get("reason")
                or repair_type
            )
        analysis = _failure_triage.analyze_failure(
            failure_message or repair_type,
            context or {},
        )
        merged = dict(context or {})
        merged["failure_triage"] = analysis
        merged["failure_triage_enabled"] = True
        merged["failure_triage_repair_plan"] = _failure_triage.create_repair_plan(analysis)
        return merged
    except Exception:
        # Graceful degradation: return original context if triage fails
        return context or {}


def classify_repair_type(repair_type: str, context: dict[str, Any] | None = None) -> RepairPolicyDecision:
    enhanced_context = _enhance_repair_classification_with_failure_triage(repair_type, context)
    triage = enhanced_context.get("failure_triage") if isinstance(enhanced_context, dict) else None
    triage_plan = enhanced_context.get("failure_triage_repair_plan") if isinstance(enhanced_context, dict) else None
    triage_suffix = ""
    if triage or triage_plan:
        triage_suffix = (
            f" Triage category={triage.get('failure_category') if isinstance(triage, dict) else 'unknown'}"
            f" priority={triage.get('repair_priority', {}).get('priority') if isinstance(triage, dict) else 'n/a'}."
        )
    if repair_type in QUEUE_OR_RESCHEDULE:
        return RepairPolicyDecision(
            repair_type=repair_type,
            policy_class="QUEUE_OR_RESCHEDULE",
            safe_to_auto_repair=False,
            requires_poli_approval=False,
            forbidden=False,
            reason=f"Action is queued/rescheduled by conflict policy.{triage_suffix}",
        )
    if repair_type in FORBIDDEN:
        return RepairPolicyDecision(
            repair_type=repair_type,
            policy_class="FORBIDDEN",
            safe_to_auto_repair=False,
            requires_poli_approval=False,
            forbidden=True,
            reason=f"Action is forbidden by repair safety policy.{triage_suffix}",
        )
    if repair_type in APPROVAL_REQUIRED:
        return RepairPolicyDecision(
            repair_type=repair_type,
            policy_class="APPROVAL_REQUIRED",
            safe_to_auto_repair=False,
            requires_poli_approval=True,
            forbidden=False,
            reason=f"Action requires Poli approval and cannot auto-execute.{triage_suffix}",
        )
    if repair_type in AUTO_ALLOWED:
        return RepairPolicyDecision(
            repair_type=repair_type,
            policy_class="AUTO_ALLOWED",
            safe_to_auto_repair=True,
            requires_poli_approval=False,
            forbidden=False,
            reason=f"Action is safe for automatic repair.{triage_suffix}",
        )
    return RepairPolicyDecision(
        repair_type=repair_type,
        policy_class="APPROVAL_REQUIRED",
        safe_to_auto_repair=False,
        requires_poli_approval=True,
        forbidden=False,
        reason=f"Unknown repair type defaults to approval-required.{triage_suffix}",
    )


def policy_inventory() -> dict[str, Any]:
    return {
        "AUTO_ALLOWED": sorted(AUTO_ALLOWED),
        "APPROVAL_REQUIRED": sorted(APPROVAL_REQUIRED),
        "QUEUE_OR_RESCHEDULE": sorted(QUEUE_OR_RESCHEDULE),
        "FORBIDDEN": sorted(FORBIDDEN),
    }


def get_phase1_skill_status() -> dict[str, Any]:
    """Get status of Phase 1 deployed skills in repair policy.

    Returns:
        Dictionary with skill statuses
    """
    return {
        "failure_triage": {
            "available": _failure_triage is not None,
            "enabled": ECC_FAILURE_TRIAGE_AVAILABLE,
        }
    }


# Initialize Phase 1 failure-triage skill at module load
_init_failure_triage()
