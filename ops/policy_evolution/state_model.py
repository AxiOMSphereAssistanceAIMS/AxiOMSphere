"""Canonical governed-repair lifecycle and deterministic recovery actions.

This is the semantic state authority for policy-evolution repair cases. Queue
storage remains the existing queue authority; it projects only execution
states and cannot invent governance transitions.
"""
from __future__ import annotations

from dataclasses import dataclass


TRANSITIONS: dict[str, frozenset[str]] = {
    "DETECTED": frozenset({"DIAGNOSED", "OBSOLETE_CASE"}),
    "DIAGNOSED": frozenset({"PROPOSAL_READY", "EVIDENCE_REQUIRED", "OBSOLETE_CASE"}),
    "PROPOSAL_READY": frozenset({"AUDIT_REQUIRED", "OBSOLETE_CASE"}),
    "AUDIT_REQUIRED": frozenset({"AUDITED", "REWORK_REQUIRED", "OBSOLETE_CASE"}),
    "AUDITED": frozenset({"POLICY_EVALUATION", "REAUDIT_REQUIRED", "OBSOLETE_CASE"}),
    "POLICY_EVALUATION": frozenset({"AUTHORIZED", "EVIDENCE_REQUIRED", "AUTHORITY_REVIEW_REQUIRED", "OBSOLETE_CASE"}),
    "AUTHORIZED": frozenset({"QUEUED", "OBSOLETE_CASE"}),
    "QUEUED": frozenset({"EXECUTING", "REVALIDATION_REQUIRED", "OBSOLETE_CASE"}),
    "EXECUTING": frozenset({"VERIFYING", "STALLED", "REVALIDATION_REQUIRED"}),
    "VERIFYING": frozenset({"COMPLETED_VERIFIED", "REWORK_REQUIRED", "STALLED"}),
    "STALLED": frozenset({"REVALIDATION_REQUIRED", "OBSOLETE_CASE"}),
    "REVALIDATION_REQUIRED": frozenset({"REVALIDATING", "OBSOLETE_CASE"}),
    "REVALIDATING": frozenset({"READY_FOR_NEW_PERMIT", "REVALIDATION_FAILED", "OBSOLETE_CASE"}),
    "READY_FOR_NEW_PERMIT": frozenset({"PERMIT_ISSUED", "POLICY_EVALUATION", "OBSOLETE_CASE"}),
    "PERMIT_ISSUED": frozenset({"RESTART_QUEUED", "OBSOLETE_CASE"}),
    "RESTART_QUEUED": frozenset({"RESTARTING", "REVALIDATION_REQUIRED"}),
    "RESTARTING": frozenset({"EXECUTING", "STALLED"}),
    "EVIDENCE_REQUIRED": frozenset({"DIAGNOSED", "AUDIT_REQUIRED", "OBSOLETE_CASE"}),
    "AUTHORITY_REVIEW_REQUIRED": frozenset({"POLICY_EVALUATION", "OBSOLETE_CASE"}),
    "REAUDIT_REQUIRED": frozenset({"AUDIT_REQUIRED", "OBSOLETE_CASE"}),
    "REWORK_REQUIRED": frozenset({"DIAGNOSED", "PROPOSAL_READY", "OBSOLETE_CASE"}),
    "REVALIDATION_FAILED": frozenset({"REVALIDATION_REQUIRED", "OBSOLETE_CASE"}),
    "OBSOLETE_CASE": frozenset(),
    "COMPLETED_VERIFIED": frozenset(),
}

NEXT_ACTION: dict[str, str] = {
    "DETECTED": "DIAGNOSE_FAILURE",
    "DIAGNOSED": "BUILD_CHANGE_PROPOSAL",
    "PROPOSAL_READY": "REQUEST_AUDITOR_ATTESTATION",
    "AUDIT_REQUIRED": "COMPLETE_INDEPENDENT_AUDIT",
    "AUDITED": "EVALUATE_CURRENT_POLICY",
    "POLICY_EVALUATION": "RESOLVE_AUTHORITY_OR_EVIDENCE",
    "AUTHORIZED": "ISSUE_EXECUTION_PERMIT",
    "QUEUED": "EXECUTE_PERMITTED_REPAIR",
    "EXECUTING": "VERIFY_REPAIR_RESULT",
    "VERIFYING": "PERSIST_COMPLETION_OR_REWORK",
    "STALLED": "START_STALE_REVALIDATION",
    "REVALIDATION_REQUIRED": "PERFORM_REVALIDATION",
    "REVALIDATING": "ISSUE_FRESH_PERMIT_OR_REWORK",
    "READY_FOR_NEW_PERMIT": "ISSUE_EXECUTION_PERMIT",
    "PERMIT_ISSUED": "QUEUE_EXISTING_LINEAGE_RESTART",
    "RESTART_QUEUED": "EXECUTE_RESTARTED_REPAIR",
    "RESTARTING": "EXECUTE_RESTARTED_REPAIR",
    "EVIDENCE_REQUIRED": "COLLECT_REQUIRED_EVIDENCE",
    "AUTHORITY_REVIEW_REQUIRED": "REQUEST_AUTHORITY_REVIEW",
    "REAUDIT_REQUIRED": "REQUEST_FRESH_AUDIT",
    "REWORK_REQUIRED": "REWORK_PROPOSAL_OR_DIAGNOSIS",
    "REVALIDATION_FAILED": "REPAIR_REVALIDATION_FAILURE",
    "OBSOLETE_CASE": "NONE",
    "COMPLETED_VERIFIED": "NONE",
}


@dataclass(frozen=True)
class RepairLifecycle:
    state: str
    next_action_id: str

    @classmethod
    def start(cls) -> "RepairLifecycle":
        return cls("DETECTED", NEXT_ACTION["DETECTED"])

    def transition(self, target: str) -> "RepairLifecycle":
        if target not in TRANSITIONS.get(self.state, frozenset()):
            raise ValueError(f"INVALID_REPAIR_TRANSITION:{self.state}->{target}")
        return RepairLifecycle(target, NEXT_ACTION[target])

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state, "next_action_id": self.next_action_id}


def validate_projection(record: dict) -> None:
    state = str(record.get("state") or "")
    if state not in NEXT_ACTION:
        raise ValueError("UNKNOWN_REPAIR_STATE")
    if record.get("next_action_id") != NEXT_ACTION[state]:
        raise ValueError("NEXT_ACTION_STATE_MISMATCH")
