from __future__ import annotations

import hashlib

import pytest

from ops.policy_evolution.contracts import build_attestation, build_change_proposal, build_owner_approval, build_revalidation
from ops.policy_evolution.integration import (authorize_repair, capture_policy_gap, classify_stalled_case, persist_owner_test_event, project_legacy,
                                               queue_restart_dry_run, revalidate_and_prepare_restart)
from ops.repairman.controlled_patch_pipeline import run_controlled_patch_pipeline
from ops.policy_evolution.policy_lifecycle import PolicyLifecycle, shadow_compare
from ops.telegram_governed_execution import GovernedExecutionStore


def h(x): return hashlib.sha256(x.encode()).hexdigest()


def bundle():
    p = build_change_proposal(repair_case_id="c", failure_id="f", source_hash=h("s"), candidate_tree_hash=h("t"), candidate_diff_hash=h("d"), evidence_manifest_hash=h("e"), rollback_hash=h("r"), reuse_scan_reference="scan", created_by="repairman", affected_paths=["ops/x.py"], residual_risk="LOW")
    a = build_attestation(purpose="REPAIR_SOLUTION", proposal=p, relevant_policy_revision="p1", auditor_identity="a", auditor_role="auditor", auditor_engine="test", auditor_capability="repair", root_cause_reviewed=True, solution_method_reviewed=True, architecture_compatibility_reviewed=True, tests_reviewed=True, test_results_verified=True, rollback_reviewed=True, residual_risk="LOW", verdict="APPROVED")
    return p, a


def test_repairman_permit_preflight_and_legacy_rejection():
    p, a = bundle()
    permit = authorize_repair(proposal=p, attestation=a, policy_revision="p1", policy_hash=h("policy"), actor_authorized=True)
    assert permit["execution_state"] == "AUTHORIZED"
    with pytest.raises(Exception):
        authorize_repair(proposal=p, attestation={"verdict":"pass"}, policy_revision="p1", policy_hash=h("policy"), actor_authorized=True)
    assert project_legacy({"decision":"ALLOW"}, kind="policy_decision")["execution_authority"] == "NONE"


def test_repairman_execution_boundary_rejects_unbound_governance_preflight():
    with pytest.raises(PermissionError, match="EXECUTION_NOT_AUTHORIZED"):
        run_controlled_patch_pipeline(request=object(), phase1_result={}, governance_preflight={"execution_state":"NOT_AUTHORIZED", "next_action_id":"REVALIDATE_REPAIR"})


def test_live_execution_boundary_rejects_missing_governance_preflight():
    from ops.policy_evolution.integration import require_governed_execution
    with pytest.raises(PermissionError, match="EXECUTION_GOVERNANCE_REQUIRED"):
        require_governed_execution(None, action_type="repair")


def test_repairman_agent_execute_path_rejects_missing_governance_preflight():
    from ops.repairman.agent_repair_client import submit_failure_repair_task
    with pytest.raises(PermissionError, match="EXECUTION_GOVERNANCE_REQUIRED"):
        submit_failure_repair_task(source_agent="LOGI", source_pipeline="safe_probe", failure_origin="test", failure_summary="safe probe", repair_scope="repair", dispatch_mode="execute")


def test_owner_approval_is_persisted_in_existing_governed_store(tmp_path):
    p, a = bundle()
    approval = build_owner_approval(approval_type="POLICY_DESIGN", proposal_hash=p["proposal_hash"], owner_identity="owner", owner_role="owner", policy_change_proposal_id="pc", from_policy_revision="p1", candidate_policy_revision="p2", auditor_attestation_hash=a["attestation_hash"], risk_assessment_hash=h("risk"), callback_id="cb")
    store = GovernedExecutionStore(tmp_path / "state.json")
    stored = store.record_governance_approval(approval, expected_prior_state="DRAFT")
    assert stored["approval_id"] == approval["approval_id"]
    assert any(event["event"] == "OWNER_APPROVAL_RECORDED" for event in store.events)


def test_owner_test_event_is_correlated_non_activating_and_idempotent(tmp_path):
    store = GovernedExecutionStore(tmp_path / "state.json")
    event = {"approval_id":"test-owner-event", "approval_type":"TEST_ONLY_OWNER_GOVERNANCE_EVENT", "owner_identity":"owner", "correlation_root_id":"root-1", "request_fingerprint":h("request"), "nonce":"nonce-1", "prior_state":"DRAFT"}
    first = persist_owner_test_event(store, event, expected_correlation_root="root-1", expected_owner_identity="owner")
    second = persist_owner_test_event(store, event, expected_correlation_root="root-1", expected_owner_identity="owner")
    assert first == second
    with pytest.raises(Exception, match="CORRELATION_MISMATCH"):
        persist_owner_test_event(store, event, expected_correlation_root="wrong", expected_owner_identity="owner")
    with pytest.raises(Exception, match="REPLAY_MISMATCH"):
        persist_owner_test_event(store, {**event, "request_fingerprint": h("mutated")}, expected_correlation_root="root-1", expected_owner_identity="owner")
    with pytest.raises(Exception, match="ACTIVATION_FORBIDDEN"):
        persist_owner_test_event(store, {**event, "approval_id":"activation", "approval_type":"POLICY_ACTIVATION"}, expected_correlation_root="root-1", expected_owner_identity="owner")


def test_logi_classifier_requires_second_pass_for_genuine_gap():
    chain = {"failure":1,"root_cause":1,"proposal":1,"candidate":1,"tests":1,"rollback":1,"policy_decision":1,"policy_rule_too_coarse":True}
    assert classify_stalled_case(chain, second_pass={"cause":"POLICY_RULE_TOO_COARSE"})["genuine_policy_gap"]
    assert not classify_stalled_case(chain, second_pass={"cause":"PIPELINE_IMPLEMENTATION_DEFECT"})["genuine_policy_gap"]


def test_policy_gap_capture_suppresses_missing_attestation_and_is_idempotent():
    result = capture_policy_gap(case_id="c", correlation_root_id="root", chain={"failure":1,"root_cause":1,"proposal":1,"candidate":1,"tests":1,"rollback":1,"policy_decision":1,"attestation_missing":True})
    assert result["genuine_policy_gap"] is False
    assert result["candidate_disposition"] == "ROUTE_TO_EVIDENCE_OR_REPAIR_REVIEW"
    assert result["mutations"]["policy"] is False
    again = capture_policy_gap(case_id="c", correlation_root_id="root", chain={"failure":1,"root_cause":1,"proposal":1,"candidate":1,"tests":1,"rollback":1,"policy_decision":1,"attestation_missing":True})
    assert again["idempotency_key"] == result["idempotency_key"]


def test_shadow_preserves_hard_boundary_and_lifecycle():
    result = shadow_compare(lambda c: "DENY", lambda c: "ALLOW", [{"case_id":"hard","hard_boundary":True}])
    assert result["status"] == "FAIL"
    state = PolicyLifecycle().transition("DESIGN_APPROVED").transition("CANDIDATE_IMPLEMENTED")
    assert state.state == "CANDIDATE_IMPLEMENTED"


def test_revalidation_restart_adapter_dry_run_preserves_lineage():
    p, a = bundle()
    permit = authorize_repair(proposal=p, attestation=a, policy_revision="p1", policy_hash=h("policy"), actor_authorized=True)
    rev = build_revalidation(repair_case_id="c", old_policy_revision="p0", current_policy_revision="p1", old_proposal_hash=p["proposal_hash"], checks={"failure":True,"root_cause":True,"attestation":True,"tests":True,"rollback":True,"authority":True}, disposition="READY_FOR_NEW_PERMIT", owner="logi", next_action_id="", evidence_needed=[], recheck_preconditions=[])
    restart = revalidate_and_prepare_restart(revalidation=rev, proposal=p, attestation=a, permit=permit, current_policy_revision="p1", current_policy_hash=h("policy"), repair_case_id="c", original_repair_id="r1", original_failure_id="f", canonical_repair_identity="f|r|"+p["source_hash"], source_hash=p["source_hash"], queue_target="existing", requested_by="logi", authorized_by="poli", previous_attempt_count=0, attempt_budget=1)
    assert queue_restart_dry_run(restart, existing_lineage={"r1"})["mutated"] is False
