from __future__ import annotations

from pathlib import Path
from typing import Any


def verify_phase20_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    errs: list[str] = []
    req_files = [
        repo_root / "ops/agents/self_learning/skill_request_approval/skill_request_schema.py",
        repo_root / "ops/agents/self_learning/skill_request_approval/skill_request_registry.py",
        repo_root / "ops/agents/self_learning/skill_request_approval/skill_request_validator.py",
        repo_root / "ops/agents/self_learning/skill_request_approval/skill_request_approval_policy.py",
        repo_root / "ops/agents/self_learning/skill_request_approval/skill_request_downstream_planner.py",
        repo_root / "ops/agents/self_learning/skill_request_approval/axi_skill_request_aggregator.py",
        repo_root / "ops/agents/self_learning/skill_request_approval/skill_request_approval_workflow.py",
        repo_root / "ops/evals/aims_skill_request_approval_gate_smoke.py",
    ]
    for p in req_files:
        if not p.exists():
            errs.append(f"missing file: {p}")
    return len(errs) == 0, errs


def validate_generated(
    skill_packs: list[dict[str, Any]],
    candidate_skills: list[dict[str, Any]],
    sandbox_stubs: list[dict[str, Any]],
    queue: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    for p in skill_packs:
        if p.get("lifecycle_state") != "CANDIDATE_SKILL":
            errors.append(f"pack {p.get('skill_pack_id')} lifecycle must be CANDIDATE_SKILL")
        if not p.get("owner_agent_id"):
            errors.append(f"pack {p.get('skill_pack_id')} missing owner")
        if not p.get("evidence_refs"):
            errors.append(f"pack {p.get('skill_pack_id')} missing evidence_refs")
        if not p.get("safety_gates"):
            errors.append(f"pack {p.get('skill_pack_id')} missing safety_gates")
        for flag in (
            "self_approval_allowed","runtime_activation_allowed","training_launch_allowed",
            "model_load_unload_allowed","service_restart_allowed","secrets_access_allowed",
            "deletion_quarantine_allowed","registry_direct_write_allowed",
        ):
            if p.get(flag) is not False:
                errors.append(f"pack {p.get('skill_pack_id')} {flag} must be false")

    for c in candidate_skills:
        if c.get("lifecycle_state") != "CANDIDATE_SKILL":
            errors.append(f"candidate {c.get('candidate_skill_id')} invalid lifecycle")

    if queue.get("execution_allowed") is not False:
        errors.append("execution_allowed must be false")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "runtime_activation_count": 0,
        "training_launch_count": 0,
        "model_load_unload_count": 0,
        "service_restart_count": 0,
        "model_endpoint_calls_count": 0,
    }
