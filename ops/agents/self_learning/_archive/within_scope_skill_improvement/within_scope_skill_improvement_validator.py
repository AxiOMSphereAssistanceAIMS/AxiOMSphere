from __future__ import annotations

from pathlib import Path


def verify_phase26_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    errs = []
    req = [
        repo_root / "ops/agents/self_learning/active_skill_monitoring/active_skill_monitoring_schema.py",
        repo_root / "ops/agents/self_learning/active_skill_monitoring/active_skill_event_collector.py",
        repo_root / "ops/agents/self_learning/active_skill_monitoring/active_skill_performance_assessor.py",
        repo_root / "ops/agents/self_learning/active_skill_monitoring/active_skill_improvement_planner.py",
        repo_root / "ops/agents/self_learning/active_skill_monitoring/active_skill_feedback_loop.py",
        repo_root / "ops/agents/self_learning/active_skill_monitoring/active_skill_monitoring_validator.py",
        repo_root / "ops/agents/self_learning/active_skill_monitoring/active_skill_monitoring_workflow.py",
        repo_root / "ops/evals/aims_active_skill_monitoring_smoke.py",
        repo_root / "aims_workspace/agent_self_learning/active_skill_monitoring/active_skill_monitoring_events.json",
        repo_root / "aims_workspace/agent_self_learning/active_skill_monitoring/active_skill_performance_assessment.json",
        repo_root / "aims_workspace/agent_self_learning/active_skill_monitoring/skill_improvement_plan.json",
        repo_root / "aims_workspace/agent_self_learning/active_skill_monitoring/skill_feedback_evidence_pack.json",
        repo_root / "aims_workspace/agent_self_learning/active_skill_monitoring/next_self_learning_feedback_queue.json",
        repo_root / "aims_workspace/agent_self_learning/active_skill_monitoring/active_skill_monitoring_report.json",
        repo_root / "aims_workspace/agent_self_learning/active_skill_monitoring/active_skill_monitoring_report.md",
    ]
    for p in req:
        if not p.exists():
            errs.append(f"missing phase26 artifact: {p}")
    return len(errs) == 0, errs


def validate_result(report: dict) -> dict:
    errs = []
    if report.get("active_skill_versions_updated", 0) < 0:
        errs.append("invalid active_skill_versions_updated")
    if report.get("owner_bindings_updated", 0) < 0:
        errs.append("invalid owner_bindings_updated")
    return {"ok": len(errs) == 0, "errors": errs}
