from __future__ import annotations

import datetime as dt
from typing import Any


def build_intake_queue(plans: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "queue_id": f"SIQ-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "queued_plans": [
            {
                "sandbox_plan_id": p.get("sandbox_plan_id"),
                "owner_agent_id": p.get("owner_agent_id"),
                "skill_name": p.get("skill_name"),
            }
            for p in plans
        ],
        "next_processor": "AUTOMATIC_SANDBOX_EXECUTION_AFTER_INTAKE",
        "required_phase": "PHASE_23_AUTOMATIC_SANDBOX_EXECUTION",
        "execution_allowed": False,
        "reason": "Materialized sandbox plans are ready, but execution remains disabled until automatic sandbox execution phase.",
    }
