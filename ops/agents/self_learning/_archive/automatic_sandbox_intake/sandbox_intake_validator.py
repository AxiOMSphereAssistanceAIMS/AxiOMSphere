from __future__ import annotations

from pathlib import Path
from typing import Any

REQUIRED_FORBIDDEN = {
    "self_approval",
    "runtime_activation",
    "active_runtime_promotion",
    "production_service_restart",
    "deletion",
    "quarantine",
    "model_training_launch",
    "model_promotion",
    "model_load_unload",
    "slot32_slot120_conflict",
    "secret_access",
    "raw_claude_mem_access",
    "registry_direct_write",
    "external_send",
}


def verify_phase21_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    errs: list[str] = []
    req = [
        repo_root / "ops/agents/self_learning/automatic_skill_creator/automatic_skill_creator_schema.py",
        repo_root / "ops/agents/self_learning/automatic_skill_creator/automatic_skill_pack_builder.py",
        repo_root / "ops/agents/self_learning/automatic_skill_creator/automatic_skill_pack_validator.py",
        repo_root / "ops/agents/self_learning/automatic_skill_creator/automatic_candidate_skill_writer.py",
        repo_root / "ops/agents/self_learning/automatic_skill_creator/automatic_sandbox_plan_stub_builder.py",
        repo_root / "ops/agents/self_learning/automatic_skill_creator/automatic_skill_evidence_writer.py",
        repo_root / "ops/agents/self_learning/automatic_skill_creator/automatic_skill_creator_workflow.py",
        repo_root / "ops/evals/aims_automatic_skill_creator_smoke.py",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_creator/generated_skill_packs.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_creator/generated_candidate_skills.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_creator/generated_sandbox_plan_stubs.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_creator/skill_creation_evidence_pack.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_creator/automatic_skill_creator_report.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_creator/automatic_skill_creator_report.md",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_creator/next_self_learning_cycle_queue.json",
    ]
    for p in req:
        if not p.exists():
            errs.append(f"missing required phase21 artifact: {p}")
    return len(errs) == 0, errs


def validate_materialized(
    plans: list[dict[str, Any]],
    queue: dict[str, Any],
) -> dict[str, Any]:
    errs: list[str] = []
    for p in plans:
        if p.get("lifecycle_transition") != "CANDIDATE_SKILL -> SANDBOX_SKILL":
            errs.append(f"invalid lifecycle transition in {p.get('sandbox_plan_id')}")
        if p.get("runtime_activation_allowed") is not False:
            errs.append(f"runtime_activation_allowed must be false in {p.get('sandbox_plan_id')}")
        if p.get("self_approval_allowed") is not False:
            errs.append(f"self_approval_allowed must be false in {p.get('sandbox_plan_id')}")
        if p.get("execution_allowed") is not False:
            errs.append(f"execution_allowed must be false in {p.get('sandbox_plan_id')}")
        fset = set(p.get("forbidden_action_tests", []))
        if not REQUIRED_FORBIDDEN.issubset(fset):
            errs.append(f"forbidden_action_tests incomplete in {p.get('sandbox_plan_id')}")

        fs = p.get("filesystem_policy", {})
        prod = p.get("production_policy", {})
        model = p.get("model_policy", {})
        if ".env" not in fs.get("forbidden", []):
            errs.append("filesystem_policy must forbid .env")
        if "secrets" not in fs.get("forbidden", []):
            errs.append("filesystem_policy must forbid secrets")
        if "raw_claude_mem" not in fs.get("forbidden", []):
            errs.append("filesystem_policy must forbid raw_claude_mem")
        if "project_source_mutation" not in fs.get("forbidden", []):
            errs.append("filesystem_policy must forbid source mutation")

        if prod.get("service_restart_forbidden") is not True:
            errs.append("production_policy must block service restart")
        if prod.get("deletion_quarantine_forbidden") is not True:
            errs.append("production_policy must block deletion/quarantine")
        if prod.get("external_send_forbidden") is not True:
            errs.append("production_policy must block external send")

        if model.get("model_endpoint_calls_forbidden") is not True:
            errs.append("model_policy must block model endpoint calls")
        if model.get("model_load_unload_forbidden") is not True:
            errs.append("model_policy must block model load/unload")
        if model.get("training_launch_forbidden") is not True:
            errs.append("model_policy must block training launch")
        if model.get("model_promotion_forbidden") is not True:
            errs.append("model_policy must block promotion")

    if queue.get("execution_allowed") is not False:
        errs.append("intake queue execution_allowed must be false")

    return {
        "ok": len(errs) == 0,
        "errors": errs,
        "sandbox_tests_executed": 0,
        "runtime_activation_count": 0,
        "model_endpoint_calls": 0,
        "training_launch_count": 0,
        "model_load_unload_count": 0,
        "service_restart_count": 0,
        "slot32_slot120_policy_preserved": True,
        "active_registry_modification_count": 0,
    }
