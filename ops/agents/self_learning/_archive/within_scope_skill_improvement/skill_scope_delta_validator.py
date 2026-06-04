from __future__ import annotations

import datetime as dt


def validate_scope_delta(delta: dict, active_entry: dict) -> dict:
    blocking = []
    warnings = []

    if delta.get("permission_delta") not in {"none", "no_expansion"}:
        blocking.append("permission expansion detected")
    if delta.get("risk_class_delta") != "unchanged":
        blocking.append("risk class increase/change detected")
    if delta.get("owner_agent_delta") != "unchanged":
        blocking.append("owner agent change detected")
    if delta.get("runtime_context_delta") not in {"unchanged", "narrower"}:
        blocking.append("runtime context expansion detected")
    if delta.get("forbidden_action_delta") not in {"unchanged", "stricter"}:
        blocking.append("forbidden action relaxation detected")

    inside = len(blocking) == 0
    status = "PASS_WITHIN_SCOPE" if inside else "BLOCKED_SCOPE_EXPANSION"

    return {
        "validation_id": f"SDV-{delta['delta_id']}",
        "delta_id": delta["delta_id"],
        "active_skill_id": active_entry["active_skill_id"],
        "approved_scope_id": active_entry.get("approved_scope_id", ""),
        "validation_status": status,
        "checks": {
            "permission_delta": delta.get("permission_delta"),
            "risk_class_delta": delta.get("risk_class_delta"),
            "owner_agent_delta": delta.get("owner_agent_delta"),
            "runtime_context_delta": delta.get("runtime_context_delta"),
            "forbidden_action_delta": delta.get("forbidden_action_delta"),
        },
        "blocking_reasons": blocking,
        "warning_reasons": warnings,
        "inside_approved_scope": inside,
        "permission_expansion_detected": any("permission" in b for b in blocking),
        "risk_class_increase_detected": any("risk" in b for b in blocking),
        "owner_agent_change_detected": any("owner" in b for b in blocking),
        "runtime_context_expansion_detected": any("runtime context" in b for b in blocking),
        "forbidden_action_relaxation_detected": any("forbidden action" in b for b in blocking),
        "new_approval_required": not inside,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
