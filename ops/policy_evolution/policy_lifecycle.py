"""Canonical projection and old-vs-candidate shadow evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ORDER = ("DRAFT", "DESIGN_APPROVED", "CANDIDATE_IMPLEMENTED", "POLICY_CHANGE_AUDITED", "TESTED",
         "APPLICATION_APPROVED", "INSTALLED_NOT_ACTIVE", "SHADOW_EVALUATION", "ACTIVATION_READY",
         "ACTIVATION_APPROVED", "ACTIVE")


@dataclass
class PolicyLifecycle:
    state: str = "DRAFT"
    revision: str = ""
    policy_hash: str = ""

    def transition(self, target: str) -> "PolicyLifecycle":
        if target not in ORDER or ORDER.index(target) != ORDER.index(self.state) + 1:
            raise ValueError(f"INVALID_POLICY_TRANSITION:{self.state}->{target}")
        return PolicyLifecycle(target, self.revision, self.policy_hash)


def shadow_compare(old_policy: Callable[[dict[str, Any]], Any], candidate_policy: Callable[[dict[str, Any]], Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [{"case_id": str(case.get("case_id", i)), "old": old_policy(case), "candidate": candidate_policy(case), "hard_boundary": bool(case.get("hard_boundary"))} for i, case in enumerate(cases)]
    unintended = [row for row in rows if row["old"] in {"DENY", "NOT_AUTHORIZED"} and row["candidate"] in {"ALLOW", "AUTHORIZED"} and row.get("hard_boundary")]
    return {"schema":"aims.policy_shadow_result.v1", "cases":rows, "hard_boundary_violations":unintended,
            "status":"PASS" if not unintended else "FAIL", "newly_authorized_count":sum(r["old"] != r["candidate"] for r in rows)}
