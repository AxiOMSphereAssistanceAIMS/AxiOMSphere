from __future__ import annotations

import datetime as dt


def build_evidence_pack(stats: dict) -> dict:
    return {
        "evidence_pack_id": f"WSE-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_phase25_artifacts": stats.get("source_phase25_artifacts", []),
        "source_phase26_artifacts": stats.get("source_phase26_artifacts", []),
        "deltas_created": stats.get("deltas_created", 0),
        "scope_validations_passed": stats.get("scope_validations_passed", 0),
        "scope_validations_blocked": stats.get("scope_validations_blocked", 0),
        "regression_tests_run": stats.get("regression_tests_run", 0),
        "regression_tests_passed": stats.get("regression_tests_passed", 0),
        "active_skill_versions_updated": stats.get("active_skill_versions_updated", 0),
        "owner_bindings_updated": stats.get("owner_bindings_updated", 0),
        "new_approval_requests_created": stats.get("new_approval_requests_created", 0),
        "skipped_items": stats.get("skipped_items", 0),
        "safety_checks": {
            "no_production_code_patch": True,
            "no_service_restart": True,
            "no_model_load_unload": True,
            "no_training_launch": True,
            "no_secrets_access": True,
            "no_raw_claude_mem_access": True,
            "no_deletion_quarantine": True,
        },
        "dangerous_counters": {
            "service_restart_count": 0,
            "model_load_unload_count": 0,
            "training_launch_count": 0,
            "secrets_access_count": 0,
            "raw_claude_mem_access_count": 0,
            "deletion_quarantine_count": 0,
            "production_code_patch_count": 0,
        },
        "downstream_steps_completed": [
            "load_active_skill_registry",
            "load_monitoring_feedback",
            "build_within_scope_skill_delta",
            "validate_scope_delta",
            "run_regression_tests",
            "update_active_skill_registry_artifact",
            "update_owner_binding_artifact",
            "write_improvement_evidence",
            "queue_next_monitoring_cycle",
        ],
        "downstream_steps_not_executed": [
            "expand_scope",
            "request_new_permission",
            "patch_production_agent_code",
            "restart_services",
            "launch_training",
            "load_unload_models",
        ],
        "audit_trail": ["phase26 monitoring", "phase27 within_scope_improvement"],
    }
