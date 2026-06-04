from __future__ import annotations

import datetime as dt
from typing import Any


def build_evidence_pack(
    approved_requests: list[str],
    skill_packs: list[dict[str, Any]],
    candidate_skills: list[dict[str, Any]],
    sandbox_stubs: list[dict[str, Any]],
    queue_path: str,
) -> dict[str, Any]:
    return {
        "evidence_pack_id": f"EVP-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "approved_requests_consumed": approved_requests,
        "skill_packs_generated": len(skill_packs),
        "candidate_skills_generated": len(candidate_skills),
        "sandbox_plan_stubs_generated": len(sandbox_stubs),
        "rejected_or_skipped_requests": [],
        "safety_checks": {
            "runtime_activation": "not_executed",
            "training_launch": "not_executed",
            "model_load_unload": "not_executed",
            "service_restart": "not_executed",
        },
        "downstream_steps_completed": [
            "generate_skill_pack",
            "validate_skill_pack",
            "register_candidate_skill_as_artifact",
            "create_sandbox_test_plan_stub",
            "write_audit_evidence",
            "include_in_next_self_learning_cycle_queue",
        ],
        "downstream_steps_not_executed": [
            "run_sandbox_test_later",
            "certify_skill",
            "activate_runtime_skill",
        ],
        "next_cycle_queue_path": queue_path,
        "audit_trail": ["phase20 downstream plan", "phase21 auto skill creator"],
    }
