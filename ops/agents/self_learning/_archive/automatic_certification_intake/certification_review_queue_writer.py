from __future__ import annotations

import datetime as dt


def build_review_queue(packages: list[dict]) -> dict:
    items = [
        {
            "certification_candidate_id": p["certification_candidate_id"],
            "source_execution_id": p["source_execution_id"],
            "status": "READY_FOR_GATE_REVIEW",
            "lifecycle_state": "SANDBOX_SKILL",
            "proposed_lifecycle_state": "CERTIFIED_SKILL",
        }
        for p in packages
    ]
    return {
        "queue_id": f"CRQ-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "queued_items": items,
        "next_processor": "AUTOMATIC_CERTIFICATION_GATE_REVIEW",
        "required_phase": "PHASE_25_AUTOMATIC_CERTIFICATION_GATE_REVIEW",
        "execution_allowed": False,
        "reason": "Certification package created. Gate review remains disabled until automatic certification gate phase.",
    }
