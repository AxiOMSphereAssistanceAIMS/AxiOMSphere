from __future__ import annotations

import datetime as dt
from typing import Any

from .automatic_skill_creator_schema import AutomaticSkillPack


def build_skill_pack(plan: dict[str, Any]) -> dict[str, Any]:
    req_id = str(plan.get("request_id", ""))
    spid = f"SPK-{req_id}"
    pack = AutomaticSkillPack(
        skill_pack_id=spid,
        source_request_id=req_id,
        source_downstream_plan_id=str(plan.get("downstream_plan_id", "")),
        owner_agent_id=str(plan.get("owner_agent_id", "")),
        skill_name=str(plan.get("approved_skill_name", "")),
        skill_domain="general",
        trigger_conditions=["approved_skill_request", "next_self_learning_cycle"],
        instructions=[
            "Use approved request context",
            "Generate structured outputs",
            "Do not activate runtime skill",
        ],
        expected_inputs=["approved skill request", "downstream plan"],
        expected_outputs=["candidate skill record", "sandbox test plan stub", "evidence"],
        refusal_conditions=[
            "request not approved",
            "unsafe flags present",
            "missing gates",
        ],
        safety_gates=list(plan.get("required_gates", [])),
        evidence_refs=list(plan.get("evidence_outputs", [])),
        sandbox_test_stub={"status": "STUB_READY_FOR_PHASE_8_COMPATIBLE_PLAN"},
        rollback_notes=str(plan.get("rollback_plan", "")),
        deprecation_notes="No runtime activation in Phase 21",
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    return pack.to_dict()
