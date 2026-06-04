from __future__ import annotations

import datetime as dt
from typing import Any


def extract_skill_signal(dossier: dict[str, Any]) -> dict[str, Any]:
    patterns = dossier.get("reusable_patterns", [])
    candidate = (dossier.get("candidate_skills") or ["repairman_generic_improvement"])[0]
    next_action = "WAIT_FOR_MORE_EVIDENCE"
    if patterns:
        next_action = "SEND_TO_HERMES_FOR_REVIEW"
    if dossier.get("outcome_status") in {"REPAIR_FAILED", "NEEDS_HERMES_REVIEW"}:
        next_action = "CREATE_HERMES_INCUBATION_CANDIDATE"

    return {
        "signal_id": f"signal_{dossier['repair_case_id']}",
        "repair_case_id": dossier["repair_case_id"],
        "source_dossier_id": dossier["repair_case_id"],
        "target_agent": "repairman",
        "candidate_skill_name": candidate,
        "candidate_skill_domain": dossier.get("failure_domain", "repair"),
        "observed_pattern": "; ".join(patterns) if patterns else "no clear reusable pattern",
        "repeated_pattern_likely": bool(patterns),
        "adoption_path": "repairman_adoption_bridge",
        "scope_approval_required": True,
        "suggested_permission_level": "READ_ONLY_ANALYSIS",
        "suggested_risk_class": "LOW",
        "evidence_refs": dossier.get("evidence_refs", []),
        "next_action": next_action,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
