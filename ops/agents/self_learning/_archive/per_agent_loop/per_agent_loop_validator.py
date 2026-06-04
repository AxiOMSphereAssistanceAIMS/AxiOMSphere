from __future__ import annotations

import json
from pathlib import Path


def verify_phase27_acceptance(root: Path) -> tuple[bool, list[str]]:
    issues: list[str] = []
    report = root / "aims_workspace/agent_self_learning/within_scope_skill_improvement/within_scope_skill_improvement_report.json"
    smoke = root / "aims_workspace/agent_self_learning/within_scope_skill_improvement/skill_improvement_evidence_pack.json"
    if not report.exists() or not smoke.exists():
        issues.append("missing phase27 outputs")
        return False, issues
    r = json.loads(report.read_text(encoding="utf-8"))
    expected = {
        "active_skills_loaded": 1,
        "monitoring_queue_items_loaded": 1,
        "within_scope_items_consumed": 1,
        "deltas_created": 1,
        "scope_validations_passed": 1,
        "scope_validations_blocked": 0,
        "regression_tests_run": 1,
        "regression_pass": 1,
        "regression_warn_pass": 0,
        "regression_fail": 0,
        "active_skill_versions_updated": 1,
        "owner_bindings_updated": 1,
        "new_approval_requests_created": 0,
        "next_monitoring_items_queued": 1,
    }
    for k, v in expected.items():
        if r.get(k) != v:
            issues.append(f"{k} expected {v} got {r.get(k)}")
    if r.get("safety_status") != "PASS":
        issues.append("phase27 safety_status not PASS")
    if r.get("next_action") != "CONTINUE_ACTIVE_SKILL_MONITORING_LOOP":
        issues.append("phase27 next_action mismatch")
    return len(issues) == 0, issues


def validate_outputs(data: dict) -> dict:
    errors: list[str] = []
    profiles = data["profiles"]
    states = data["states"]
    outboxes = data["outboxes"]
    cycles = data["cycles"]
    policy = data["policy"]

    if len(profiles) < 15:
        errors.append("not enough agent profiles")
    for p in profiles:
        if p.get("approval_required_for_new_skill") is not True:
            errors.append(f"new skill approval disabled for {p.get('agent_id')}")
        if p.get("approval_required_for_scope_expansion") is not True:
            errors.append(f"scope expansion approval disabled for {p.get('agent_id')}")
        if p.get("within_scope_improvement_allowed") is not True:
            errors.append(f"within scope improvement disabled for {p.get('agent_id')}")
        if "self_approval" not in p.get("forbidden_actions", []):
            errors.append(f"self approval not forbidden for {p.get('agent_id')}")
        if p.get("loop_mode") not in {"SELF_LEARNING_DRY_RUN", "OBSERVATION_ONLY", "SELF_LEARNING_ACTIVE_WITH_APPROVAL_GATE", "SELF_LEARNING_ACTIVE_WITHIN_SCOPE"}:
            errors.append(f"bad loop mode for {p.get('agent_id')}")

    if len(states) != len(profiles):
        errors.append("state/profile count mismatch")
    if len(outboxes) != len(profiles):
        errors.append("outbox/profile count mismatch")
    if len(cycles) != len(profiles):
        errors.append("cycle/profile count mismatch")
    if policy.get("central_runner_created") is not False:
        errors.append("central runner created")
    if "mass_runner_owns_all_learning" not in policy.get("central_forbidden", []):
        errors.append("central boundary missing")

    return {"ok": len(errors) == 0, "errors": errors}
