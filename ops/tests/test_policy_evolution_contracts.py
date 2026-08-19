from __future__ import annotations

import hashlib

import pytest

from ops.policy_evolution import (
    ContractError,
    build_attestation,
    build_change_proposal,
    build_owner_approval,
    build_permit,
    build_revalidation,
    build_restart_record,
    validate_attestation,
    validate_owner_approval,
    validate_permit,
    validate_revalidation,
    validate_restart_record,
)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def proposal():
    return build_change_proposal(
        repair_case_id="case-1", failure_id="failure-1", source_hash=digest("source"),
        candidate_tree_hash=digest("tree"), candidate_diff_hash=digest("diff"),
        evidence_manifest_hash=digest("evidence"), rollback_hash=digest("rollback"),
        reuse_scan_reference="scan-1", created_by="repairman", affected_paths=["ops/example.py"],
        residual_risk="LOW",
    )


def attestation(p):
    return build_attestation(
        purpose="REPAIR_SOLUTION", proposal=p, relevant_policy_revision="policy:v1",
        auditor_identity="auditor-1", auditor_role="technical_auditor", auditor_engine="test",
        auditor_capability="repair-review", root_cause_reviewed=True, solution_method_reviewed=True,
        architecture_compatibility_reviewed=True, tests_reviewed=True, test_results_verified=True,
        rollback_reviewed=True, residual_risk="LOW", verdict="APPROVED",
    )


def test_exact_attestation_and_permit_are_valid():
    p = proposal(); a = attestation(p)
    validate_attestation(a, p, current_policy_revision="policy:v1")
    permit = build_permit(proposal=p, attestation=a, policy_revision="policy:v1", policy_hash=digest("policy"))
    validate_permit(permit, proposal=p, attestation=a, current_policy_revision="policy:v1", current_policy_hash=digest("policy"))


def test_source_or_policy_mutation_invalidates_attestation_and_permit():
    p = proposal(); a = attestation(p)
    changed = dict(p, candidate_tree_hash=digest("changed"))
    with pytest.raises(ContractError, match="ARTIFACT_MISMATCH"):
        validate_attestation(a, changed, current_policy_revision="policy:v1")
    permit = build_permit(proposal=p, attestation=a, policy_revision="policy:v1", policy_hash=digest("policy"))
    with pytest.raises(ContractError, match="PERMIT_STALE"):
        validate_permit(permit, proposal=p, attestation=a, current_policy_revision="policy:v2", current_policy_hash=digest("policy"))


def test_owner_stages_cannot_be_reused():
    approval = build_owner_approval(
        approval_type="POLICY_DESIGN", proposal_hash=digest("proposal"), owner_identity="owner-1", owner_role="owner",
        policy_change_proposal_id="pc-1", from_policy_revision="v1", candidate_policy_revision="v2",
        auditor_attestation_hash=digest("attestation"), risk_assessment_hash=digest("risk"), callback_id="cb-1",
    )
    with pytest.raises(ContractError, match="STALE_OR_WRONG_STAGE"):
        validate_owner_approval(approval, expected_type="POLICY_ACTIVATION", proposal_hash=digest("proposal"), owner_identity="owner-1", prior_state="ACTIVATION_READY")


def test_revalidation_then_restart_preserves_lineage_and_is_bounded():
    p = proposal(); a = attestation(p)
    permit = build_permit(proposal=p, attestation=a, policy_revision="policy:v1", policy_hash=digest("policy"))
    revalidation = build_revalidation(
        repair_case_id="case-1", old_policy_revision="policy:v0", current_policy_revision="policy:v1",
        old_proposal_hash=p["proposal_hash"], checks={"failure": True, "root_cause": True, "attestation": True, "tests": True, "rollback": True, "authority": True},
        disposition="READY_FOR_NEW_PERMIT", owner="repairman", next_action_id="", evidence_needed=[], recheck_preconditions=[],
    )
    validate_revalidation(revalidation, current_policy_revision="policy:v1")
    restart = build_restart_record(
        repair_case_id="case-1", original_repair_id="repair-1", original_failure_id="failure-1",
        canonical_repair_identity="failure-1|repair|" + p["source_hash"], revalidation=revalidation, permit=permit,
        proposal=p, attestation=a, current_policy_revision="policy:v1", source_hash=p["source_hash"],
        queue_target="existing-queue", requested_by="logi", authorized_by="poli", previous_attempt_count=1,
        bounded_new_attempt_budget=1,
    )
    validate_restart_record(restart, current_policy_revision="policy:v1")
    assert restart["lineage_parent"] == "repair-1"
    assert restart["bounded_new_attempt_budget"] == 1
