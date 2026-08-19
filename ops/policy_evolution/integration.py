"""Runtime adapters over existing AIMS governance primitives.

Adapters are intentionally side-effect bounded: policy lifecycle and restart
operations are dry-run by default. Durable owner records use the existing
GovernedExecutionStore event ledger rather than a new store.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from .contracts import (ContractError, build_permit, build_restart_record,
                        validate_attestation, validate_permit, validate_revalidation,
                        validate_restart_record)


@dataclass(frozen=True)
class GovernanceDisposition:
    state: str
    next_action_id: str
    owner: str
    reason_codes: tuple[str, ...] = ()
    evidence_needed: tuple[str, ...] = ()
    recheck_preconditions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "next_action_id": self.next_action_id, "owner": self.owner,
                "reason_codes": list(self.reason_codes), "evidence_needed": list(self.evidence_needed),
                "recheck_preconditions": list(self.recheck_preconditions)}


def require_governed_execution(preflight: Mapping[str, Any] | None, *, action_type: str) -> dict[str, Any]:
    """Fail closed at a live execution boundary for governed repair actions."""
    if not isinstance(preflight, Mapping):
        raise PermissionError(f"EXECUTION_GOVERNANCE_REQUIRED:{action_type}")
    if preflight.get("execution_state") not in {"AUTHORIZED", "AUTHORIZED_WITH_CONTROLS"}:
        raise PermissionError("EXECUTION_NOT_AUTHORIZED:" + str(preflight.get("next_action_id") or "REVALIDATE_REPAIR"))
    if not preflight.get("permit_hash") or not preflight.get("permit_nonce"):
        raise PermissionError("EXECUTION_PERMIT_INCOMPLETE:REVALIDATE_PERMIT")
    return dict(preflight)


def authorize_repair(*, proposal: Mapping[str, Any], attestation: Mapping[str, Any], policy_revision: str,
                     policy_hash: str, actor_authorized: bool, current_risk: str = "LOW",
                     allowed_scope: list[str] | None = None) -> dict[str, Any]:
    """Real governed preflight used before the existing Repairman pipeline."""
    validate_attestation(attestation, proposal, current_policy_revision=policy_revision)
    if not actor_authorized:
        return GovernanceDisposition("AUTHORITY_REVIEW_REQUIRED", "AUTHORITY_REVIEW", "Poli", ("ACTOR_AUTHORITY_MISSING",), ("authority_record",), ("authority_current",)).to_dict()
    if current_risk.upper() not in {"LOW", "MODERATE"}:
        return GovernanceDisposition("NOT_AUTHORIZED", "RISK_REVIEW", "Poli", ("RESIDUAL_RISK_TOO_HIGH",), ("risk_assessment",), ("risk_within_envelope",)).to_dict()
    permit = build_permit(proposal=proposal, attestation=attestation, policy_revision=policy_revision,
                          policy_hash=policy_hash, decision="AUTHORIZED_WITH_CONTROLS" if current_risk.upper() == "MODERATE" else "AUTHORIZED",
                          allowed_scope=allowed_scope)
    validate_permit(permit, proposal=proposal, attestation=attestation,
                    current_policy_revision=policy_revision, current_policy_hash=policy_hash)
    return permit


def persist_owner_approval(store: Any, approval: Mapping[str, Any], *, expected_prior_state: str) -> dict[str, Any]:
    """Append an owner approval to the existing governed execution event ledger."""
    if not hasattr(store, "record_governance_approval"):
        raise ContractError("GOVERNED_STORE_APPROVAL_ADAPTER_MISSING")
    return store.record_governance_approval(dict(approval), expected_prior_state=expected_prior_state)


def persist_owner_test_event(store: Any, event: Mapping[str, Any], *, expected_correlation_root: str,
                             expected_owner_identity: str, expected_prior_state: str = "DRAFT") -> dict[str, Any]:
    """Persist a non-activating Owner trace event through the existing ledger."""
    required = ("approval_id", "approval_type", "owner_identity", "correlation_root_id", "request_fingerprint", "nonce")
    missing = [key for key in required if not event.get(key)]
    if missing:
        raise ContractError("OWNER_TEST_EVENT_MISSING:" + ",".join(missing))
    if event.get("approval_type") in {"POLICY_APPLICATION", "POLICY_ACTIVATION"}:
        raise ContractError("OWNER_TEST_EVENT_ACTIVATION_FORBIDDEN")
    if event.get("correlation_root_id") != expected_correlation_root:
        raise ContractError("OWNER_TEST_EVENT_CORRELATION_MISMATCH")
    if event.get("owner_identity") != expected_owner_identity:
        raise ContractError("OWNER_TEST_EVENT_OWNER_MISMATCH")
    existing = [item for item in getattr(store, "events", [])
                if item.get("event") == "OWNER_APPROVAL_RECORDED" and item.get("approval_id") == event.get("approval_id")]
    if existing and existing[-1].get("approval") != dict(event):
        raise ContractError("OWNER_TEST_EVENT_REPLAY_MISMATCH")
    return persist_owner_approval(store, event, expected_prior_state=expected_prior_state)


def revalidate_and_prepare_restart(*, revalidation: Mapping[str, Any], proposal: Mapping[str, Any],
                                   attestation: Mapping[str, Any], permit: Mapping[str, Any],
                                   current_policy_revision: str, current_policy_hash: str,
                                   repair_case_id: str, original_repair_id: str, original_failure_id: str,
                                   canonical_repair_identity: str, source_hash: str, queue_target: str,
                                   requested_by: str, authorized_by: str, previous_attempt_count: int,
                                   attempt_budget: int, seen_idempotency_keys: set[str] | None = None) -> dict[str, Any]:
    validate_revalidation(revalidation, current_policy_revision=current_policy_revision)
    validate_permit(permit, proposal=proposal, attestation=attestation,
                    current_policy_revision=current_policy_revision, current_policy_hash=current_policy_hash)
    restart = build_restart_record(repair_case_id=repair_case_id, original_repair_id=original_repair_id,
        original_failure_id=original_failure_id, canonical_repair_identity=canonical_repair_identity,
        revalidation=revalidation, permit=permit, proposal=proposal, attestation=attestation,
        current_policy_revision=current_policy_revision, source_hash=source_hash, queue_target=queue_target,
        requested_by=requested_by, authorized_by=authorized_by, previous_attempt_count=previous_attempt_count,
        bounded_new_attempt_budget=attempt_budget)
    validate_restart_record(restart, current_policy_revision=current_policy_revision,
                            seen_idempotency_keys=seen_idempotency_keys)
    return restart


def queue_restart_dry_run(restart: Mapping[str, Any], *, existing_lineage: set[str], execute: bool = False) -> dict[str, Any]:
    """Validate queue attachment; only the existing queue adapter may execute."""
    if not execute:
        return {"status": "RESTART_QUEUED_DRY_RUN", "would_attach_lineage": restart.get("lineage_parent"), "mutated": False}
    if restart.get("lineage_parent") not in existing_lineage:
        return GovernanceDisposition("RESTART_NOT_ALLOWED", "REPAIR_LINEAGE_REVIEW", "Repairman", ("LINEAGE_NOT_FOUND",), ("existing_repair_record",), ("lineage_present",)).to_dict()
    return {"status": "READY_FOR_EXISTING_QUEUE_ADAPTER", "lineage": restart.get("lineage_parent"), "mutated": False}


def classify_stalled_case(chain: Mapping[str, Any], *, second_pass: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic evidence-completeness and policy-gap classification."""
    required = ("failure", "root_cause", "proposal", "candidate", "tests", "rollback", "policy_decision")
    missing = [key for key in required if not chain.get(key)]
    if missing: cause = "ROOT_CAUSE_NOT_PROVEN" if "root_cause" in missing else "TEST_EVIDENCE_INSUFFICIENT"
    elif chain.get("attestation_stale"): cause = "AUDITOR_ATTESTATION_STALE"
    elif chain.get("retry_conflict"): cause = "RETRY_RECONCILIATION_DEFECT"
    elif chain.get("authority_boundary"): cause = "AUTHORITY_BOUNDARY"
    elif chain.get("policy_rule_too_coarse") or chain.get("policy_false_negative"): cause = "POLICY_RULE_TOO_COARSE"
    else: cause = str(chain.get("stop_cause") or "PIPELINE_IMPLEMENTATION_DEFECT")
    genuine = cause in {"POLICY_RULE_TOO_COARSE", "POLICY_MISSING_POSITIVE_ENVELOPE", "POLICY_FALSE_NEGATIVE"}
    if genuine and second_pass and second_pass.get("cause") != cause:
        cause, genuine = "UNKNOWN_REQUIRES_INVESTIGATION", False
    return {"cause": cause, "genuine_policy_gap": genuine, "evidence_chain_complete": not missing,
            "missing": missing, "next_action_id": "CREATE_POLICY_CHANGE_PROPOSAL" if genuine else "REPAIR_PIPELINE_REWORK",
            "owner": "Poli" if genuine else "Logi/Repairman"}


def capture_policy_gap(*, case_id: str, correlation_root_id: str, chain: Mapping[str, Any],
                       second_pass: Mapping[str, Any] | None = None,
                       current_policy_revision: str = "unknown", current_policy_hash: str = "") -> dict[str, Any]:
    """Permanent, idempotent, non-mutating Logi policy-gap capture boundary."""
    base = classify_stalled_case(chain, second_pass=second_pass)
    if chain.get("authority_boundary"):
        primary = "VALID_AUTHORITY_BOUNDARY"
    elif chain.get("attestation_missing"):
        primary = "MISSING_AUDITOR_ATTESTATION"
    elif chain.get("attestation_stale"):
        primary = "STALE_EVIDENCE"
    elif chain.get("rollback_missing"):
        primary = "ROLLBACK_INSUFFICIENT"
    elif chain.get("tests_missing"):
        primary = "INSUFFICIENT_TEST_EVIDENCE"
    elif chain.get("retry_conflict"):
        primary = "RETRY_RECONCILIATION_DEFECT"
    elif chain.get("pipeline_defect"):
        primary = "PIPELINE_DEFECT"
    elif base["genuine_policy_gap"]:
        primary = "GENUINE_POLICY_FALSE_NEGATIVE"
    else:
        primary = "UNKNOWN_EVIDENCE_GAP"
    candidate = bool(base["genuine_policy_gap"] and primary in {"GENUINE_POLICY_FALSE_NEGATIVE", "POLICY_RULE_TOO_COARSE", "POLICY_MISSING_POSITIVE_ENVELOPE"})
    identity = f"{case_id}|{correlation_root_id}|{primary}|{current_policy_revision}|{current_policy_hash}"
    record = {
        "schema": "aims.policy_evolution.logi_policy_gap_capture.v1",
        "case_id": case_id, "correlation_root_id": correlation_root_id,
        "primary_classification": primary, "genuine_policy_gap": candidate,
        "candidate_disposition": "POLICY_CHANGE_CANDIDATE_DETECTED" if candidate else "ROUTE_TO_EVIDENCE_OR_REPAIR_REVIEW",
        "next_action_id": "PREPARE_POLICY_CHANGE_PROPOSAL" if candidate else base["next_action_id"],
        "owner": "Poli/Owner" if candidate else base["owner"],
        "reason_codes": [primary, "SECOND_PASS_REQUIRED" if candidate else "FALSE_POSITIVE_SUPPRESSED"],
        "evidence_complete": base["evidence_chain_complete"], "missing": base["missing"],
        "current_policy_revision": current_policy_revision, "current_policy_hash": current_policy_hash,
        "idempotency_key": "policy-gap-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
        "input_fingerprint": hashlib.sha256(json.dumps(dict(chain), sort_keys=True).encode()).hexdigest(),
        "mutations": {"policy": False, "candidate_approval": False, "permit": False, "queue": False, "repair": False},
    }
    if candidate and second_pass and second_pass.get("cause") != base["cause"]:
        record.update({"genuine_policy_gap": False, "candidate_disposition": "REWORK_REQUIRED", "next_action_id": "SECOND_PASS_RECONCILIATION"})
    return record


def project_legacy(record: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    if kind in {"auditor", "approval"} and not record.get("proposal_hash"):
        return {"state": "LEGACY_UNBOUND", "next_action_id": "REAUDIT_REQUIRED", "evidence_needed": ["exact_proposal_hash", "candidate_hash", "evidence_hash"]}
    if kind == "policy_decision" and record.get("decision") in {"ALLOW", "DENY"}:
        return {"state": "COMPATIBILITY_PROJECTION", "next_action_id": "MIGRATION_REVIEW", "execution_authority": "NONE"}
    return {"state": "CURRENT", "next_action_id": "NONE"}
