from __future__ import annotations

def validate_incubated_candidate(c: dict) -> list[str]:
    errs = []
    if c.get("tested_by_hermes") is not True:
        errs.append("tested_by_hermes_false")
    if c.get("maturity_status") != "READY_FOR_REPAIRMAN_HANDOFF":
        errs.append("maturity_not_ready")
    return errs
