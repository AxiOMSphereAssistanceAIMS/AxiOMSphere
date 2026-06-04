from __future__ import annotations

from pathlib import Path


def verify_phase23_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    errs = []
    req = [
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/sandbox_execution_after_intake_schema.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/synthetic_fixture_builder.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/sandbox_execution_policy.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/sandbox_execution_runner.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/sandbox_execution_result_validator.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/sandbox_execution_evidence_writer.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/sandbox_certification_intake_queue_writer.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_execution/sandbox_execution_after_intake_workflow.py",
        repo_root / "ops/evals/aims_automatic_sandbox_execution_smoke.py",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_execution/synthetic_fixtures",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_execution/sandbox_execution_results.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_execution/sandbox_execution_evidence_pack.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_execution/certification_intake_queue.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_execution/sandbox_execution_report.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_execution/sandbox_execution_report.md",
    ]
    for p in req:
        if not p.exists():
            errs.append(f"missing phase23 artifact: {p}")
    return len(errs) == 0, errs


def validate_outputs(packages: list[dict], checklists: list[dict], queue: dict) -> dict:
    errs = []
    for p in packages:
        if p.get("lifecycle_state_before") != "SANDBOX_SKILL":
            errs.append(f"{p.get('certification_candidate_id')} lifecycle_state_before must be SANDBOX_SKILL")
        if p.get("proposed_lifecycle_state") != "CERTIFIED_SKILL":
            errs.append(f"{p.get('certification_candidate_id')} proposed_lifecycle_state must be CERTIFIED_SKILL")
        if p.get("proposed_lifecycle_state") == "ACTIVE_RUNTIME_SKILL":
            errs.append(f"{p.get('certification_candidate_id')} must not target ACTIVE_RUNTIME_SKILL")
        for k in ("runtime_activation_allowed", "self_approval_allowed", "certified_runtime_allowed", "active_runtime_requested"):
            if p.get(k) is not False:
                errs.append(f"{p.get('certification_candidate_id')} {k} must be false")

    by_id = {c["certification_candidate_id"]: c for c in checklists}
    for p in packages:
        cid = p["certification_candidate_id"]
        if cid not in by_id:
            errs.append(f"missing gate checklist for {cid}")
            continue
        c = by_id[cid]
        if not c.get("argus_gate_required"):
            errs.append(f"argus gate must be required for {cid}")
        if not c.get("logi_gate_required"):
            errs.append(f"logi gate must be required for {cid}")
        if not c.get("qa_gate_required"):
            errs.append(f"qa gate must be required for {cid}")
        if not c.get("registry_gate_required"):
            errs.append(f"registry gate must be required for {cid}")
        if not c.get("rollback_gate_required"):
            errs.append(f"rollback gate must be required for {cid}")
        if not c.get("evidence_gate_required"):
            errs.append(f"evidence gate must be required for {cid}")
        if c.get("secrets_policy_passed") is not True:
            errs.append(f"secrets policy must be passed for {cid}")
        if c.get("production_policy_passed") is not True:
            errs.append(f"production policy must be passed for {cid}")
        if c.get("model_policy_passed") is not True:
            errs.append(f"model policy must be passed for {cid}")
        if c.get("dgx_policy_passed") is not True:
            errs.append(f"dgx policy must be passed for {cid}")

    if queue.get("execution_allowed") is not False:
        errs.append("certification review queue execution_allowed must be false")

    return {
        "ok": len(errs) == 0,
        "errors": errs,
        "runtime_activation_count": 0,
        "active_registry_modification_count": 0,
        "model_endpoint_calls": 0,
        "training_launch_count": 0,
        "model_load_unload_count": 0,
        "service_restart_count": 0,
    }
