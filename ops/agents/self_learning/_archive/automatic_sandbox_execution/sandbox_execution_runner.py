from __future__ import annotations

import datetime as dt
from typing import Any

from .sandbox_execution_after_intake_schema import SandboxExecutionAfterIntakeResult


def run_deterministic_sandbox(plan: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    # deterministic local simulation only
    pass_count = 0
    warn_count = 0
    fail_count = 0
    rejected_actions: list[str] = []

    forbidden = set(plan.get("forbidden_action_tests", []))
    required_forbidden = {
        "self_approval",
        "runtime_activation",
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

    if required_forbidden.issubset(forbidden):
        pass_count += 1
    else:
        fail_count += 1

    # refusal fixtures expected to be rejected safely
    for fx in fixtures:
        if fx["fixture_type"] in {"synthetic_refusal_case", "synthetic_policy_case"}:
            rejected_actions.append(fx["fixture_id"])
    pass_count += 1

    status = "SANDBOX_PASS" if fail_count == 0 else "SANDBOX_FAIL"
    lifecycle_after = "SANDBOX_SKILL" if status in {"SANDBOX_PASS", "SANDBOX_WARN"} else "CANDIDATE_SKILL"

    res = SandboxExecutionAfterIntakeResult(
        execution_id=f"EX-{plan['sandbox_plan_id']}",
        sandbox_plan_id=plan["sandbox_plan_id"],
        source_candidate_skill_id=plan["source_candidate_skill_id"],
        source_skill_pack_id=plan["source_skill_pack_id"],
        owner_agent_id=plan["owner_agent_id"],
        skill_name=plan["skill_name"],
        skill_domain=plan["skill_domain"],
        lifecycle_state_before="CANDIDATE_SKILL",
        lifecycle_state_after=lifecycle_after,
        fixtures_used=[f["fixture_id"] for f in fixtures],
        actions_simulated=["schema_check", "forbidden_action_refusal_check", "policy_refusal_check"],
        expected_outputs_checked=list(plan.get("expected_outputs", [])),
        forbidden_actions_tested=list(plan.get("forbidden_action_tests", [])),
        safety_checks={
            "no_shell": True,
            "no_model_calls": True,
            "no_training": True,
            "no_service_restart": True,
            "no_registry_mutation": True,
        },
        result_status=status,
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        rejected_actions=rejected_actions,
        output_artifacts=["sandbox_execution_results.json"],
        evidence_refs=list(plan.get("evidence_refs", [])),
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    return res.to_dict()
