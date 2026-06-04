from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FORBIDDEN_TEXT = [".env", "secret", "raw claude-mem", "token", "password", "api_key"]


def verify_phase22_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    errs: list[str] = []
    req = [
        repo_root / "ops/agents/self_learning/automatic_sandbox_intake/sandbox_intake_schema.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_intake/sandbox_plan_materializer.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_intake/sandbox_intake_validator.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_intake/sandbox_intake_queue_writer.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_intake/sandbox_intake_evidence_writer.py",
        repo_root / "ops/agents/self_learning/automatic_sandbox_intake/sandbox_intake_workflow.py",
        repo_root / "ops/evals/aims_automatic_sandbox_intake_smoke.py",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_intake/materialized_sandbox_test_plans.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_intake/sandbox_test_intake_queue.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_intake/sandbox_intake_evidence_pack.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_intake/sandbox_intake_report.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_sandbox_intake/sandbox_intake_report.md",
    ]
    for p in req:
        if not p.exists():
            errs.append(f"missing phase22 artifact: {p}")
    return len(errs) == 0, errs


def validate_fixtures(fixtures_root: Path) -> tuple[bool, list[str]]:
    errs: list[str] = []
    for p in fixtures_root.glob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        if str(fixtures_root) not in str(p.parent):
            errs.append(f"fixture out of allowed path: {p}")
        blob = json.dumps(data, ensure_ascii=False).lower()
        if "raw claude-mem" in blob:
            errs.append(f"fixture includes forbidden raw claude-mem content: {p.name}")
        if "api_key" in blob or "password" in blob or "token" in blob:
            errs.append(f"fixture includes credential-like content: {p.name}")
    return len(errs) == 0, errs


def validate_results(results: list[dict[str, Any]], cert_queue: dict[str, Any]) -> dict[str, Any]:
    errs: list[str] = []
    for r in results:
        if r.get("execution_mode") != "DETERMINISTIC_SYNTHETIC_ONLY":
            errs.append(f"invalid execution_mode {r.get('execution_id')}")
        if r.get("model_endpoint_calls", 0) != 0:
            errs.append(f"model endpoint calls must be 0 in {r.get('execution_id')}")
        if r.get("training_launch_count", 0) != 0:
            errs.append(f"training launch must be 0 in {r.get('execution_id')}")
        if r.get("model_load_unload_count", 0) != 0:
            errs.append(f"model load/unload must be 0 in {r.get('execution_id')}")
        if r.get("service_restart_count", 0) != 0:
            errs.append(f"service restart must be 0 in {r.get('execution_id')}")
        if r.get("secrets_access_count", 0) != 0:
            errs.append(f"secrets access must be 0 in {r.get('execution_id')}")
        if r.get("raw_claude_mem_access_count", 0) != 0:
            errs.append(f"raw claude-mem access must be 0 in {r.get('execution_id')}")
        if r.get("active_registry_modification_count", 0) != 0:
            errs.append(f"active registry modification must be 0 in {r.get('execution_id')}")
        if r.get("runtime_activation_allowed") is not False:
            errs.append(f"runtime_activation_allowed must be false in {r.get('execution_id')}")
        if r.get("self_approval_allowed") is not False:
            errs.append(f"self_approval_allowed must be false in {r.get('execution_id')}")
        if r.get("lifecycle_state_after") == "ACTIVE_RUNTIME_SKILL":
            errs.append(f"ACTIVE_RUNTIME_SKILL transition forbidden in {r.get('execution_id')}")

    if cert_queue.get("execution_allowed") is not False:
        errs.append("certification queue execution_allowed must be false")

    return {
        "ok": len(errs) == 0,
        "errors": errs,
        "runtime_activation_count": 0,
        "model_endpoint_calls": 0,
        "training_launch_count": 0,
        "model_load_unload_count": 0,
        "service_restart_count": 0,
        "active_registry_modification_count": 0,
    }
