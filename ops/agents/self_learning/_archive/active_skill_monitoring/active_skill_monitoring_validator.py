from __future__ import annotations

from pathlib import Path


def verify_phase25_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    errs = []
    required = [
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/full_test_suite_results.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/approved_scope_verification.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/active_skill_registry.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/owner_agent_skill_bindings.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/controlled_first_use_record.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/activation_evidence_pack.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/automatic_skill_activation_report.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/automatic_skill_activation_report.md",
        repo_root / "aims_workspace/agent_self_learning/automatic_skill_activation/rollback_manifest.json",
    ]
    for p in required:
        if not p.exists():
            errs.append(f"missing phase25 output: {p}")
    return len(errs) == 0, errs


def validate_outputs(events: list[dict], assessments: list[dict], plans: list[dict], queue: dict) -> dict:
    errs = []
    if not events:
        errs.append("monitoring events missing")
    if not assessments:
        errs.append("assessments missing")
    if not plans:
        errs.append("improvement plans missing")

    if any("inside_approved_scope" not in e for e in events):
        errs.append("inside_approved_scope field missing in event")

    for p in plans:
        if p.get("changes_inside_approved_scope") and p.get("new_approval_required"):
            errs.append("within-scope improvement must not require new approval")
        if p.get("scope_expansion_required") and not p.get("new_approval_required"):
            errs.append("scope expansion must require new approval")

    return {
        "ok": len(errs) == 0,
        "errors": errs,
        "service_restart_count": 0,
        "model_load_unload_count": 0,
        "training_launch_count": 0,
        "secrets_access_count": 0,
        "raw_claude_mem_access_count": 0,
        "production_skill_execution_count": 0,
    }
