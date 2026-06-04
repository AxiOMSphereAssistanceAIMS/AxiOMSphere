from __future__ import annotations

import datetime as dt


def update_active_skill_entry(active_entry: dict, delta: dict, scope_validation: dict, regression: dict) -> dict:
    out = dict(active_entry)
    out["version"] = delta["proposed_version"]
    out["lifecycle_state"] = "ACTIVE_RUNTIME_SKILL"
    out["activation_status"] = "ACTIVE_WITHIN_APPROVED_SCOPE"
    out["improvement_status"] = "UPDATED_WITHIN_SCOPE"
    out.setdefault("evidence_refs", [])
    out["evidence_refs"] = list(out["evidence_refs"]) + [
        f"scope_validation:{scope_validation['validation_id']}",
        f"regression:{regression['regression_test_id']}",
    ]
    out["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return out
