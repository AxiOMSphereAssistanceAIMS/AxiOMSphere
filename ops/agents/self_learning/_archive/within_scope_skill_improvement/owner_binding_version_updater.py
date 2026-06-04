from __future__ import annotations

import datetime as dt


def update_owner_binding(binding: dict, delta: dict, updated_skill: dict) -> dict:
    out = dict(binding)
    out["binding_version"] = delta.get("proposed_version", updated_skill.get("version", "v1"))
    out["activation_status"] = "ACTIVE_WITHIN_APPROVED_SCOPE"
    out["monitoring_required"] = True
    out.setdefault("evidence_refs", [])
    out["evidence_refs"] = list(out["evidence_refs"]) + [f"delta:{delta['delta_id']}"]
    out["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return out
