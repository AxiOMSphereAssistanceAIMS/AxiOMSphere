from __future__ import annotations

import datetime as dt


def build_owner_binding(active_entry: dict, scope: dict) -> dict:
    return {
        "binding_id": f"BND-{active_entry['active_skill_id']}",
        "owner_agent_id": active_entry["owner_agent_id"],
        "active_skill_id": active_entry["active_skill_id"],
        "skill_name": active_entry["skill_name"],
        "allowed_runtime_contexts": list(scope.get("allowed_runtime_contexts", [])),
        "trigger_conditions": list(scope.get("activation_conditions", [])),
        "execution_mode": "CONTROLLED_SCOPE_ONLY",
        "activation_status": active_entry["activation_status"],
        "monitoring_required": True,
        "evidence_required": True,
        "rollback_manifest_id": active_entry["rollback_manifest_id"],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
