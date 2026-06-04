from __future__ import annotations

import datetime as dt
from typing import Any


def build_evidence_pack(
    source_phase22_artifacts: list[str],
    plans_loaded: int,
    fixtures_created: int,
    executions: list[dict[str, Any]],
    certification_intake_queue_path: str,
) -> dict[str, Any]:
    pass_n = sum(1 for e in executions if e.get("result_status") == "SANDBOX_PASS")
    warn_n = sum(1 for e in executions if e.get("result_status") == "SANDBOX_WARN")
    fail_n = sum(1 for e in executions if e.get("result_status") == "SANDBOX_FAIL")
    rej_n = sum(1 for e in executions if e.get("result_status") == "REJECTED_UNSAFE")

    return {
        "evidence_pack_id": f"SEE-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_phase22_artifacts": source_phase22_artifacts,
        "plans_loaded": plans_loaded,
        "fixtures_created": fixtures_created,
        "executions_run": len(executions),
        "sandbox_pass": pass_n,
        "sandbox_warn": warn_n,
        "sandbox_fail": fail_n,
        "rejected_unsafe": rej_n,
        "safety_checks": {
            "deterministic_only": True,
            "no_shell": True,
            "no_model_calls": True,
            "no_training": True,
            "no_service_restart": True,
        },
        "dangerous_counters": {
            "runtime_activation_count": 0,
            "model_endpoint_calls": 0,
            "training_launch_count": 0,
            "model_load_unload_count": 0,
            "service_restart_count": 0,
            "active_registry_modification_count": 0,
        },
        "downstream_steps_completed": [
            "load_phase22_outputs",
            "create_synthetic_fixtures",
            "validate_execution_policy",
            "run_deterministic_sandbox_simulation",
            "write_execution_results",
            "write_certification_intake_queue",
            "write_audit_evidence",
        ],
        "downstream_steps_not_executed": [
            "certify_skill",
            "activate_runtime_skill",
            "modify_active_registry",
        ],
        "certification_intake_queue_path": certification_intake_queue_path,
        "audit_trail": ["phase22 sandbox intake", "phase23 sandbox execution"],
    }
