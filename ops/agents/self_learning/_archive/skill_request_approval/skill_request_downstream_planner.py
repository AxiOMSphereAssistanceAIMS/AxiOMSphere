from __future__ import annotations

import datetime as dt
from typing import Any


def build_downstream_plan(req: dict[str, Any]) -> dict[str, Any]:
    plan_id = f"DSP-{req['request_id']}"
    return {
        "downstream_plan_id": plan_id,
        "request_id": req["request_id"],
        "approved_skill_name": req["requested_skill_name"],
        "owner_agent_id": req["proposed_owner_agent_id"],
        "automatic_steps": [
            "generate_skill_pack",
            "validate_skill_pack",
            "register_candidate_skill",
            "create_sandbox_test_plan",
            "run_sandbox_test_later",
            "write_audit_evidence",
            "include_in_next_self_learning_cycle",
        ],
        "required_gates": ["argus", "logi", "qa"] + (["traini"] if req.get("training_related") or req.get("model_related") else []),
        "evidence_outputs": [
            "skill_request_approval_report.json",
            "skill_request_approval_report.md",
            "downstream_auto_plan.json",
        ],
        "rollback_plan": "mark request as REJECTED and archive generated candidate artifacts",
        "current_status": "READY_FOR_AUTOMATIC_SKILL_CREATION_PLAN",
        "next_step": "generate_skill_pack",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
