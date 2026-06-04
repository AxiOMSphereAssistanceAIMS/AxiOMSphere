from __future__ import annotations

import datetime as dt
from typing import Any

from .sandbox_intake_schema import MaterializedSandboxTestPlan

FORBIDDEN_ACTION_TESTS = [
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
]


def materialize_plan(skill_pack: dict[str, Any], candidate: dict[str, Any], stub: dict[str, Any]) -> dict[str, Any]:
    pid = f"MSP-{candidate['candidate_skill_id']}"
    plan = MaterializedSandboxTestPlan(
        sandbox_plan_id=pid,
        source_skill_pack_id=skill_pack["skill_pack_id"],
        source_candidate_skill_id=candidate["candidate_skill_id"],
        source_stub_id=stub["sandbox_plan_stub_id"],
        owner_agent_id=skill_pack["owner_agent_id"],
        skill_name=skill_pack["skill_name"],
        skill_domain=skill_pack["skill_domain"],
        synthetic_fixture_requirements=list(stub.get("synthetic_fixture_requirements", [])),
        synthetic_fixtures_to_create=[
            "fixture_input.json",
            "fixture_expected_output.json",
            "fixture_safety_assertions.json",
        ],
        expected_behavior=list(stub.get("expected_behavior", [])),
        expected_outputs=["sandbox_result.json", "safety_report.json"],
        safety_test_cases=list(stub.get("safety_test_cases", [])),
        forbidden_action_tests=FORBIDDEN_ACTION_TESTS,
        required_gates=list(stub.get("required_gates", [])),
        evidence_refs=list(skill_pack.get("evidence_refs", [])),
        rollback_notes=str(skill_pack.get("rollback_notes", "")),
        filesystem_policy={
            "read_scope": "synthetic_fixtures_only",
            "write_scope": "aims_workspace/agent_self_learning/sandbox_runs/",
            "forbidden": [".env", "secrets", "raw_claude_mem", "project_source_mutation", "registry_mutation"],
        },
        secrets_policy={
            "secrets_access_forbidden": True,
            "tokens_keys_auth_forbidden": True,
            "fail_closed_on_secret_like_content": True,
        },
        production_policy={
            "service_restart_forbidden": True,
            "docker_compose_forbidden": True,
            "systemctl_forbidden": True,
            "external_send_forbidden": True,
            "deletion_quarantine_forbidden": True,
            "production_endpoint_mutation_forbidden": True,
        },
        model_policy={
            "model_endpoint_calls_forbidden": True,
            "model_load_unload_forbidden": True,
            "slot120_loading_forbidden": True,
            "slot32_unloading_forbidden": True,
            "training_launch_forbidden": True,
            "model_promotion_forbidden": True,
            "traini_gate_required_for_model_training_eval_related": True,
        },
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    return plan.to_dict()
