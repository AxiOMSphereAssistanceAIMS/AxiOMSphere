"""Pure, hash-bound contracts for governed policy evolution.

The module deliberately does not create a database, mutate policy, enqueue a
repair, or execute a permit. Existing AIMS stores remain authoritative. These
functions make the cross-store contract deterministic and fail closed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Any, Mapping


class ContractError(ValueError):
    """A governed contract is malformed, stale, or inconsistent."""


NON_SUCCESS_NEXT_ACTION = {
    "EVIDENCE_REQUIRED", "AUTHORITY_REVIEW_REQUIRED", "NOT_AUTHORIZED",
    "REWORK_REQUIRED", "REVALIDATION_FAILED", "RESTART_NOT_ALLOWED",
    "REAUDIT_REQUIRED", "OBSOLETE_CASE", "PENDING", "REJECTED",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry(*, minutes: int = 60) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _assert_fresh(expiry: Any, error: str) -> None:
    if not expiry:
        raise ContractError(error)
    try:
        if datetime.fromisoformat(str(expiry).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ContractError(error)
    except ValueError as exc:
        raise ContractError(error) from exc


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_digest(value: Mapping[str, Any], *, exclude: set[str] | None = None) -> str:
    excluded = exclude or {"attestation_hash", "approval_record_hash", "permit_hash",
                           "restart_hash", "revalidation_hash", "proposal_hash"}
    return hashlib.sha256(_json({k: v for k, v in value.items() if k not in excluded})).hexdigest()


def _require(record: Mapping[str, Any], *fields: str) -> None:
    missing = [field for field in fields if record.get(field) in (None, "", [])]
    if missing:
        raise ContractError("MISSING_REQUIRED_FIELDS:" + ",".join(missing))


def _hash_file_or_value(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ContractError("EXPECTED_SHA256_DIGEST")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ContractError("EXPECTED_SHA256_DIGEST") from exc
    return value


def _new_id(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}_{canonical_digest(payload)[:24]}"


def build_change_proposal(**fields: Any) -> dict[str, Any]:
    record = {
        "schema": "aims.change_proposal.v1", "proposal_id": fields.get("proposal_id") or _new_id("proposal", fields),
        "repair_case_id": fields.get("repair_case_id", ""), "failure_id": fields.get("failure_id", ""),
        "repair_identity": fields.get("repair_identity", {}), "source_revision": fields.get("source_revision", ""),
        "source_hash": fields.get("source_hash", ""), "affected_paths": list(fields.get("affected_paths", [])),
        "candidate_tree_hash": fields.get("candidate_tree_hash", ""), "candidate_diff_hash": fields.get("candidate_diff_hash", ""),
        "evidence_manifest_hash": fields.get("evidence_manifest_hash", ""), "targeted_test_plan": list(fields.get("targeted_test_plan", [])),
        "regression_plan": list(fields.get("regression_plan", [])), "rollback_reference": fields.get("rollback_reference", ""),
        "rollback_hash": fields.get("rollback_hash", ""), "reuse_scan_reference": fields.get("reuse_scan_reference", ""),
        "architecture_impact": fields.get("architecture_impact", ""), "blast_radius": fields.get("blast_radius", ""),
        "inherent_risk": fields.get("inherent_risk", ""), "controls": list(fields.get("controls", [])),
        "residual_risk": fields.get("residual_risk", ""), "created_by": fields.get("created_by", ""),
        "created_at": fields.get("created_at") or _now(), "supersedes_proposal_id": fields.get("supersedes_proposal_id", ""),
    }
    _require(record, "repair_case_id", "failure_id", "source_hash", "candidate_tree_hash", "candidate_diff_hash",
             "evidence_manifest_hash", "rollback_hash", "reuse_scan_reference", "created_by")
    for field in ("source_hash", "candidate_tree_hash", "candidate_diff_hash", "evidence_manifest_hash", "rollback_hash"):
        _hash_file_or_value(record[field])
    record["proposal_hash"] = canonical_digest(record)
    return record


def build_attestation(*, purpose: str, proposal: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    if purpose not in {"REPAIR_SOLUTION", "POLICY_CHANGE"}:
        raise ContractError("INVALID_ATTESTATION_PURPOSE")
    record = {
        "schema": "aims.auditor_attestation.v1", "attestation_id": fields.get("attestation_id") or secrets.token_hex(16),
        "purpose": purpose, "proposal_id": proposal.get("proposal_id"), "proposal_hash": proposal.get("proposal_hash"),
        "repair_case_id": proposal.get("repair_case_id", ""), "policy_change_id": fields.get("policy_change_id", ""),
        "candidate_tree_hash": proposal.get("candidate_tree_hash"), "candidate_diff_hash": proposal.get("candidate_diff_hash"),
        "evidence_manifest_hash": proposal.get("evidence_manifest_hash"), "test_evidence_hashes": list(fields.get("test_evidence_hashes", [])),
        "rollback_hash": proposal.get("rollback_hash"), "relevant_policy_revision": fields.get("relevant_policy_revision", ""),
        "auditor_identity": fields.get("auditor_identity", ""), "auditor_role": fields.get("auditor_role", ""),
        "auditor_engine": fields.get("auditor_engine", ""), "auditor_capability": fields.get("auditor_capability", ""),
        "root_cause_reviewed": fields.get("root_cause_reviewed", False), "solution_method_reviewed": fields.get("solution_method_reviewed", False),
        "architecture_compatibility_reviewed": fields.get("architecture_compatibility_reviewed", False), "tests_reviewed": fields.get("tests_reviewed", False),
        "test_results_verified": fields.get("test_results_verified", False), "rollback_reviewed": fields.get("rollback_reviewed", False),
        "known_risks": list(fields.get("known_risks", [])), "residual_risk": fields.get("residual_risk", proposal.get("residual_risk", "")),
        "verdict": fields.get("verdict", "REWORK_REQUIRED"), "conditions": list(fields.get("conditions", [])),
        "issued_at": fields.get("issued_at") or _now(), "expires_at": fields.get("expires_at") or _expiry(),
        "nonce": fields.get("nonce") or secrets.token_hex(16), "supersedes": fields.get("supersedes", ""),
    }
    _require(record, "proposal_id", "proposal_hash", "candidate_tree_hash", "candidate_diff_hash", "evidence_manifest_hash", "rollback_hash",
             "relevant_policy_revision", "auditor_identity", "auditor_role", "auditor_engine", "auditor_capability", "residual_risk")
    record["attestation_hash"] = canonical_digest(record)
    return record


def validate_attestation(attestation: Mapping[str, Any], proposal: Mapping[str, Any], *, current_policy_revision: str) -> None:
    _require(attestation, "attestation_hash", "proposal_hash", "candidate_tree_hash", "candidate_diff_hash", "evidence_manifest_hash", "rollback_hash", "nonce")
    if attestation.get("proposal_hash") != proposal.get("proposal_hash") or attestation.get("proposal_id") != proposal.get("proposal_id"):
        raise ContractError("ATTESTATION_PROPOSAL_MISMATCH")
    for field in ("candidate_tree_hash", "candidate_diff_hash", "evidence_manifest_hash", "rollback_hash"):
        if attestation.get(field) != proposal.get(field):
            raise ContractError("ATTESTATION_ARTIFACT_MISMATCH:" + field)
    if attestation.get("relevant_policy_revision") != current_policy_revision:
        raise ContractError("ATTESTATION_POLICY_STALE")
    _assert_fresh(attestation.get("expires_at"), "ATTESTATION_EXPIRED_OR_MISSING_EXPIRY")
    if attestation.get("verdict") not in {"APPROVED", "APPROVED_WITH_CONDITIONS"}:
        raise ContractError("ATTESTATION_NOT_EXECUTABLE")
    required = ("root_cause_reviewed", "solution_method_reviewed", "architecture_compatibility_reviewed", "tests_reviewed", "test_results_verified", "rollback_reviewed")
    if not all(attestation.get(field) is True for field in required):
        raise ContractError("ATTESTATION_REVIEW_INCOMPLETE")
    if canonical_digest(attestation) != attestation.get("attestation_hash"):
        raise ContractError("ATTESTATION_DIGEST_MISMATCH")


def build_permit(*, proposal: Mapping[str, Any], attestation: Mapping[str, Any], policy_revision: str, policy_hash: str,
                 decision: str = "AUTHORIZED", authority_state: str = "AUTHORIZED", reason_codes: list[str] | None = None,
                 allowed_scope: list[str] | None = None, forbidden_scope: list[str] | None = None, next_action_id: str = "") -> dict[str, Any]:
    if decision not in {"EVIDENCE_REQUIRED", "AUTHORIZED", "AUTHORIZED_WITH_CONTROLS", "AUTHORITY_REVIEW_REQUIRED", "NOT_AUTHORIZED"}:
        raise ContractError("INVALID_EXECUTION_STATE")
    record = {"schema":"aims.execution_permit.v1", "policy_decision_id":secrets.token_hex(12), "policy_revision":policy_revision,
              "policy_hash":policy_hash, "repair_case_id":proposal.get("repair_case_id"), "proposal_id":proposal.get("proposal_id"),
              "proposal_hash":proposal.get("proposal_hash"), "auditor_attestation_id":attestation.get("attestation_id"),
              "auditor_attestation_hash":attestation.get("attestation_hash"), "risk_evidence_hash":proposal.get("evidence_manifest_hash"),
              "execution_state":decision, "authority_state":authority_state, "reason_codes":list(reason_codes or []),
              "allowed_scope":list(allowed_scope or proposal.get("affected_paths", [])), "forbidden_scope":list(forbidden_scope or []),
              "permit_id":secrets.token_hex(16), "permit_nonce":secrets.token_hex(16), "issued_at":_now(), "expiry":_expiry(),
              "next_action_id":next_action_id or ("EXECUTE_PERMITTED_REPAIR" if decision.startswith("AUTHORIZED") else "REVALIDATE_REPAIR")}
    if decision.startswith("AUTHORIZED") and not record["permit_id"]:
        raise ContractError("PERMIT_ID_REQUIRED")
    record["permit_hash"] = canonical_digest(record)
    return record


def validate_permit(permit: Mapping[str, Any], *, proposal: Mapping[str, Any], attestation: Mapping[str, Any], current_policy_revision: str, current_policy_hash: str) -> None:
    if permit.get("execution_state") not in {"AUTHORIZED", "AUTHORIZED_WITH_CONTROLS"}:
        raise ContractError("PERMIT_NOT_AUTHORIZED")
    _require(permit, "permit_id", "permit_nonce", "permit_hash", "repair_case_id", "proposal_id", "proposal_hash", "auditor_attestation_id", "auditor_attestation_hash", "expiry")
    _assert_fresh(permit.get("expiry"), "PERMIT_EXPIRED_OR_MISSING_EXPIRY")
    pairs = (("policy_revision", current_policy_revision), ("policy_hash", current_policy_hash), ("repair_case_id", proposal.get("repair_case_id")),
             ("proposal_id", proposal.get("proposal_id")), ("proposal_hash", proposal.get("proposal_hash")),
             ("auditor_attestation_id", attestation.get("attestation_id")), ("auditor_attestation_hash", attestation.get("attestation_hash")),
             ("candidate_tree_hash", proposal.get("candidate_tree_hash")))
    for field, expected in pairs:
        if field in permit and permit.get(field) != expected:
            raise ContractError("PERMIT_STALE:" + field)
    if list(permit.get("allowed_scope") or []) != list(proposal.get("affected_paths") or []):
        raise ContractError("PERMIT_SCOPE_MISMATCH")
    if canonical_digest(permit) != permit.get("permit_hash"):
        raise ContractError("PERMIT_DIGEST_MISMATCH")


def build_owner_approval(*, approval_type: str, proposal_hash: str, owner_identity: str, owner_role: str, policy_change_proposal_id: str,
                         from_policy_revision: str, candidate_policy_revision: str, auditor_attestation_hash: str, risk_assessment_hash: str,
                         decision: str = "APPROVED", conditions: list[str] | None = None, callback_id: str = "", message_id: str = "") -> dict[str, Any]:
    if approval_type not in {"POLICY_DESIGN", "POLICY_APPLICATION", "POLICY_ACTIVATION"}:
        raise ContractError("INVALID_OWNER_APPROVAL_TYPE")
    if decision not in {"APPROVED", "APPROVED_WITH_CONDITIONS", "REWORK_REQUIRED", "REJECTED"}:
        raise ContractError("INVALID_OWNER_DECISION")
    record = {"schema":"aims.owner_approval.v1", "approval_id":secrets.token_hex(16), "approval_type":approval_type,
              "owner_identity":owner_identity, "owner_role":owner_role, "policy_change_proposal_id":policy_change_proposal_id,
              "proposal_hash":proposal_hash, "from_policy_revision":from_policy_revision, "candidate_policy_revision":candidate_policy_revision,
              "auditor_attestation_hash":auditor_attestation_hash, "risk_assessment_hash":risk_assessment_hash, "decision":decision,
              "conditions":list(conditions or []), "callback_id":callback_id, "message_id":message_id, "nonce":secrets.token_hex(16),
              "expiry":_expiry(), "issued_at":_now()}
    _require(record, "owner_identity", "owner_role", "policy_change_proposal_id", "proposal_hash", "auditor_attestation_hash", "risk_assessment_hash", "callback_id")
    record["approval_record_hash"] = canonical_digest(record)
    return record


def validate_owner_approval(approval: Mapping[str, Any], *, expected_type: str, proposal_hash: str, owner_identity: str, prior_state: str) -> None:
    if approval.get("approval_type") != expected_type or approval.get("proposal_hash") != proposal_hash:
        raise ContractError("OWNER_APPROVAL_STALE_OR_WRONG_STAGE")
    if approval.get("owner_identity") != owner_identity or approval.get("decision") not in {"APPROVED", "APPROVED_WITH_CONDITIONS"}:
        raise ContractError("OWNER_APPROVAL_IDENTITY_OR_DECISION_INVALID")
    _assert_fresh(approval.get("expiry"), "OWNER_APPROVAL_EXPIRED_OR_MISSING_EXPIRY")
    allowed_prior = {"POLICY_DESIGN": "DRAFT", "POLICY_APPLICATION": "CANDIDATE_IMPLEMENTED", "POLICY_ACTIVATION": "ACTIVATION_READY"}
    if prior_state != allowed_prior[expected_type]:
        raise ContractError("OWNER_APPROVAL_STAGE_RACE")
    if canonical_digest(approval) != approval.get("approval_record_hash"):
        raise ContractError("OWNER_APPROVAL_DIGEST_MISMATCH")


def build_revalidation(*, repair_case_id: str, old_policy_revision: str, current_policy_revision: str, old_proposal_hash: str,
                       checks: Mapping[str, bool], disposition: str, owner: str, next_action_id: str, evidence_needed: list[str],
                       recheck_preconditions: list[str], **extra: Any) -> dict[str, Any]:
    record = {"schema":"aims.revalidation_disposition.v1", "revalidation_id":secrets.token_hex(16), "repair_case_id":repair_case_id,
              "old_policy_revision":old_policy_revision, "current_policy_revision":current_policy_revision, "old_proposal_hash":old_proposal_hash,
              "checks":dict(checks), "disposition":disposition, "next_action_id":next_action_id, "owner":owner,
              "evidence_needed":list(evidence_needed), "recheck_preconditions":list(recheck_preconditions), "created_at":_now(), **extra}
    if disposition != "READY_FOR_NEW_PERMIT" and not next_action_id:
        raise ContractError("NON_SUCCESS_REQUIRES_NEXT_ACTION")
    record["revalidation_hash"] = canonical_digest(record)
    return record


def validate_revalidation(record: Mapping[str, Any], *, current_policy_revision: str) -> None:
    if record.get("current_policy_revision") != current_policy_revision:
        raise ContractError("REVALIDATION_POLICY_STALE")
    if record.get("disposition") == "READY_FOR_NEW_PERMIT" and not all(record.get("checks", {}).values()):
        raise ContractError("REVALIDATION_READY_WITH_FAILED_CHECK")
    if record.get("disposition") != "READY_FOR_NEW_PERMIT" and not record.get("next_action_id"):
        raise ContractError("NON_SUCCESS_REQUIRES_NEXT_ACTION")
    if canonical_digest(record) != record.get("revalidation_hash"):
        raise ContractError("REVALIDATION_DIGEST_MISMATCH")


def build_restart_record(*, repair_case_id: str, original_repair_id: str, original_failure_id: str, canonical_repair_identity: str,
                         revalidation: Mapping[str, Any], permit: Mapping[str, Any], proposal: Mapping[str, Any], attestation: Mapping[str, Any],
                         current_policy_revision: str, source_hash: str, queue_target: str, requested_by: str, authorized_by: str,
                         previous_attempt_count: int, bounded_new_attempt_budget: int, restart_mode: str = "REQUEUE_EXISTING", **extra: Any) -> dict[str, Any]:
    if revalidation.get("disposition") != "READY_FOR_NEW_PERMIT" or permit.get("execution_state") not in {"AUTHORIZED", "AUTHORIZED_WITH_CONTROLS"}:
        raise ContractError("RESTART_REQUIRES_CURRENT_REVALIDATION_AND_PERMIT")
    record = {"schema":"aims.repair_restart_record.v1", "restart_id":secrets.token_hex(16), "repair_case_id":repair_case_id,
              "original_repair_id":original_repair_id, "original_failure_id":original_failure_id, "canonical_repair_identity":canonical_repair_identity,
              "revalidation_id":revalidation.get("revalidation_id"), "new_permit_id":permit.get("permit_id"), "current_policy_revision":current_policy_revision,
              "current_proposal_id":proposal.get("proposal_id"), "current_proposal_hash":proposal.get("proposal_hash"), "auditor_attestation_id":attestation.get("attestation_id"),
              "restart_reason":extra.pop("restart_reason", "controlled stale-repair restart after revalidation"), "restart_mode":restart_mode,
              "previous_attempt_count":previous_attempt_count, "bounded_new_attempt_budget":bounded_new_attempt_budget, "source_hash":source_hash,
              "queue_target":queue_target, "lineage_parent":original_repair_id, "idempotency_key":f"{repair_case_id}:{permit.get('permit_id')}",
              "requested_by":requested_by, "authorized_by":authorized_by, "restart_state":"RESTART_QUEUED", "created_at":_now(),
              "next_action_id":"EXECUTE_RESTARTED_REPAIR", **extra}
    if bounded_new_attempt_budget < 1:
        raise ContractError("RESTART_BUDGET_REQUIRED")
    record["restart_hash"] = canonical_digest(record)
    return record


def validate_restart_record(record: Mapping[str, Any], *, current_policy_revision: str, seen_idempotency_keys: set[str] | None = None) -> None:
    if record.get("current_policy_revision") != current_policy_revision:
        raise ContractError("RESTART_POLICY_STALE")
    if record.get("lineage_parent") != record.get("original_repair_id"):
        raise ContractError("RESTART_LINEAGE_BROKEN")
    if int(record.get("bounded_new_attempt_budget", 0)) < 1:
        raise ContractError("RESTART_BUDGET_REQUIRED")
    if seen_idempotency_keys is not None and record.get("idempotency_key") in seen_idempotency_keys:
        raise ContractError("DUPLICATE_RESTART_IDEMPOTENCY_KEY")
    if canonical_digest(record) != record.get("restart_hash"):
        raise ContractError("RESTART_DIGEST_MISMATCH")


def non_success_disposition(*, state: str, next_action_id: str, owner: str, reason_codes: list[str], evidence_needed: list[str], retry_recheck_preconditions: list[str]) -> dict[str, Any]:
    if state not in NON_SUCCESS_NEXT_ACTION or not next_action_id:
        raise ContractError("NON_SUCCESS_REQUIRES_NEXT_ACTION")
    return {"state":state, "next_action_id":next_action_id, "next_action_type":"RECHECK_OR_REWORK", "owner":owner,
            "reason_codes":list(reason_codes), "evidence_needed":list(evidence_needed), "retry_recheck_preconditions":list(retry_recheck_preconditions)}
