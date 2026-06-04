from __future__ import annotations

import datetime as dt
from typing import Any


def build_certification_intake_queue(executions: list[dict[str, Any]]) -> dict[str, Any]:
    queued = []
    for e in executions:
        if e.get("result_status") in {"SANDBOX_PASS", "SANDBOX_WARN"}:
            queued.append(
                {
                    "execution_id": e.get("execution_id"),
                    "sandbox_plan_id": e.get("sandbox_plan_id"),
                    "status": "READY_FOR_CERTIFICATION_REVIEW",
                    "lifecycle_state": "SANDBOX_SKILL",
                }
            )

    return {
        "queue_id": f"CIQ-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "queued_items": queued,
        "next_processor": "AUTOMATIC_CERTIFICATION_INTAKE_AFTER_SANDBOX_EXECUTION",
        "required_phase": "PHASE_24_AUTOMATIC_CERTIFICATION_INTAKE",
        "execution_allowed": False,
        "reason": "Sandbox execution complete. Certification review remains disabled until automatic certification intake phase.",
    }
