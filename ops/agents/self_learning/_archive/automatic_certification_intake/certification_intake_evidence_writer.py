from __future__ import annotations

import datetime as dt


def build_evidence_pack(
    source_phase23_artifacts: list[str],
    execution_results_loaded: int,
    certification_candidates_created: int,
    gate_checklists_created: int,
    review_queue_items_created: int,
    skipped_results: int,
    certification_review_queue_path: str,
) -> dict:
    return {
        "evidence_pack_id": f"CIE-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_phase23_artifacts": source_phase23_artifacts,
        "execution_results_loaded": execution_results_loaded,
        "certification_candidates_created": certification_candidates_created,
        "gate_checklists_created": gate_checklists_created,
        "review_queue_items_created": review_queue_items_created,
        "skipped_results": skipped_results,
        "safety_checks": {
            "runtime_activation": 0,
            "active_registry_modification": 0,
            "model_endpoint_calls": 0,
            "training_launch": 0,
            "model_load_unload": 0,
            "service_restart": 0,
        },
        "dangerous_counters": {
            "runtime_activation_count": 0,
            "active_registry_modification_count": 0,
            "model_endpoint_calls": 0,
            "training_launch_count": 0,
            "model_load_unload_count": 0,
            "service_restart_count": 0,
        },
        "downstream_steps_completed": [
            "load_phase23_outputs",
            "filter_passed_sandbox_results",
            "build_certification_candidate_packages",
            "build_gate_checklists",
            "write_certification_review_queue",
            "write_audit_evidence",
        ],
        "downstream_steps_not_executed": [
            "pass_certification_gates",
            "register_certified_skill",
            "activate_runtime_skill",
            "modify_active_registry",
        ],
        "certification_review_queue_path": certification_review_queue_path,
        "audit_trail": ["phase23 sandbox execution", "phase24 certification intake"],
    }
