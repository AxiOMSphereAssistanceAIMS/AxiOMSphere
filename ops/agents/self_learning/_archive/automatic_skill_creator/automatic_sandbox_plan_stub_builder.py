from __future__ import annotations

from typing import Any


def build_sandbox_stub(pack: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    sid = candidate["sandbox_test_plan_stub_id"]
    return {
        "sandbox_plan_stub_id": sid,
        "source_skill_pack_id": pack["skill_pack_id"],
        "candidate_skill_id": candidate["candidate_skill_id"],
        "owner_agent_id": pack["owner_agent_id"],
        "skill_domain": pack["skill_domain"],
        "synthetic_fixture_requirements": ["safe synthetic tasks", "no secrets", "no runtime mutation"],
        "expected_behavior": ["structured output", "safety refusal on forbidden actions"],
        "safety_test_cases": ["no runtime activation", "no training launch", "no service restart"],
        "forbidden_action_tests": ["secrets access", "deletion/quarantine", "model load/unload"],
        "required_gates": pack.get("safety_gates", []),
        "status": "STUB_READY_FOR_PHASE_8_COMPATIBLE_PLAN",
    }
