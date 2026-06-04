from __future__ import annotations

import datetime as dt
from typing import Any


def build_evidence_pack(
    source_phase21_artifacts: list[str],
    skill_packs_loaded: int,
    candidate_skills_loaded: int,
    stubs_loaded: int,
    plans_materialized: int,
    plans_rejected: int,
) -> dict[str, Any]:
    return {
        "evidence_pack_id": f"SIE-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_phase21_artifacts": source_phase21_artifacts,
        "skill_packs_loaded": skill_packs_loaded,
        "candidate_skills_loaded": candidate_skills_loaded,
        "stubs_loaded": stubs_loaded,
        "plans_materialized": plans_materialized,
        "plans_rejected": plans_rejected,
        "safety_checks": {
            "sandbox_tests_executed": 0,
            "runtime_activation_count": 0,
            "model_endpoint_calls": 0,
            "training_launch_count": 0,
            "service_restart_count": 0,
        },
        "downstream_steps_completed": [
            "load_phase21_outputs",
            "materialize_sandbox_test_plans",
            "validate_sandbox_test_plans",
            "write_sandbox_test_intake_queue",
            "write_audit_evidence",
        ],
        "downstream_steps_not_executed": [
            "run_sandbox_test",
            "certify_skill",
            "activate_runtime_skill",
        ],
        "audit_trail": ["phase21 automatic skill creator", "phase22 automatic sandbox intake"],
    }
