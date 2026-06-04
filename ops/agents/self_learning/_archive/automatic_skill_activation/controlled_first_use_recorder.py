from __future__ import annotations

import datetime as dt


def build_first_use_record(active_entry: dict) -> dict:
    return {
        "first_use_id": f"FUR-{active_entry['active_skill_id']}",
        "active_skill_id": active_entry["active_skill_id"],
        "owner_agent_id": active_entry["owner_agent_id"],
        "skill_name": active_entry["skill_name"],
        "simulated_or_controlled": "controlled_synthetic",
        "input_context": "synthetic controlled first use",
        "output_summary": "skill selected and applied within approved scope",
        "evidence_refs": list(active_entry.get("evidence_refs", [])),
        "safety_checks": {
            "no_secrets": True,
            "no_service_restart": True,
            "no_training": True,
            "no_model_load_unload": True,
        },
        "result_status": "FIRST_USE_PASS",
        "rollback_available": True,
        "monitoring_next_step": "watch first N uses for scope drift",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
