from __future__ import annotations

from pathlib import Path


def policy_snapshot(out_root: Path) -> dict:
    return {
        "read_allowed_only": [
            "phase22_materialized_plans",
            "phase22_intake_queue",
            "generated_synthetic_fixtures",
        ],
        "write_allowed_only_under": str(out_root),
        "no_shell_command_execution": True,
        "no_model_endpoint_calls": True,
        "no_hermes_invocation": True,
        "no_raw_claude_mem_access": True,
        "no_env_or_secrets_access": True,
        "no_project_source_mutation": True,
        "no_active_registry_mutation": True,
        "no_service_restart": True,
        "no_deletion_quarantine": True,
        "no_training_launch": True,
        "no_model_load_unload": True,
        "no_slot120_loading": True,
        "no_slot32_unloading": True,
        "no_external_send": True,
        "no_self_approval": True,
        "no_active_runtime_transition": True,
    }


def policy_allows_plan(plan: dict) -> bool:
    return (
        plan.get("status") == "READY_FOR_SANDBOX_EXECUTION_PHASE"
        and plan.get("lifecycle_transition") == "CANDIDATE_SKILL -> SANDBOX_SKILL"
        and plan.get("sandbox_scope") == "SYNTHETIC_FIXTURE_ONLY"
        and plan.get("runtime_activation_allowed") is False
        and plan.get("self_approval_allowed") is False
        and plan.get("execution_allowed") is False
    )
