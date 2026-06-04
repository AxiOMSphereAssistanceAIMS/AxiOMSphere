from __future__ import annotations

from pathlib import Path


def verify_phase24_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    errs = []
    req = [
        repo_root / "ops/agents/self_learning/automatic_certification_intake/certification_intake_schema.py",
        repo_root / "ops/agents/self_learning/automatic_certification_intake/certification_package_builder.py",
        repo_root / "ops/agents/self_learning/automatic_certification_intake/certification_gate_checklist_builder.py",
        repo_root / "ops/agents/self_learning/automatic_certification_intake/certification_intake_validator.py",
        repo_root / "ops/agents/self_learning/automatic_certification_intake/certification_review_queue_writer.py",
        repo_root / "ops/agents/self_learning/automatic_certification_intake/certification_intake_evidence_writer.py",
        repo_root / "ops/agents/self_learning/automatic_certification_intake/certification_intake_workflow.py",
        repo_root / "ops/evals/aims_automatic_certification_intake_smoke.py",
        repo_root / "aims_workspace/agent_self_learning/automatic_certification_intake/certification_candidate_packages.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_certification_intake/certification_gate_checklists.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_certification_intake/certification_review_queue.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_certification_intake/certification_intake_evidence_pack.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_certification_intake/certification_intake_report.json",
        repo_root / "aims_workspace/agent_self_learning/automatic_certification_intake/certification_intake_report.md",
    ]
    for p in req:
        if not p.exists():
            errs.append(f"missing phase24 artifact: {p}")
    return len(errs) == 0, errs


def validate_outputs(report: dict, active_registry: list[dict], bindings: list[dict], first_use: list[dict]) -> dict:
    errs = []
    if report.get("runtime_skills_activated", 0) > 0:
        if not active_registry:
            errs.append("runtime activated but active registry empty")
        if not bindings:
            errs.append("runtime activated but owner bindings empty")
        if not first_use:
            errs.append("runtime activated but first use record empty")

    for e in active_registry:
        if e.get("lifecycle_state") != "ACTIVE_RUNTIME_SKILL":
            errs.append("active registry entry lifecycle must be ACTIVE_RUNTIME_SKILL")
        if e.get("activation_status") != "ACTIVE_WITHIN_APPROVED_SCOPE":
            errs.append("activation_status must be ACTIVE_WITHIN_APPROVED_SCOPE")

    return {"ok": len(errs) == 0, "errors": errs}
