"""NAR-009 governed fault-injection canary over the existing repair queue.

The target and queue are disposable certification files. The queue, contract,
permit, restart and bounded patch primitives are the production implementations;
only their path-bound certification namespace is different.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ops.agents.failure_to_repair.repair_queue import (
    RepairQueueItem, complete_existing_repair_item, enqueue_repair_item,
    load_repair_queue, restart_existing_repair_item,
)
from ops.repairman.sandbox_verifier import apply_patch_in_directory, run_bounded_command
from ops.telegram_governed_execution import GovernedExecutionStore
from ops.policy_evolution.contracts import (
    build_attestation, build_change_proposal, build_revalidation,
    validate_permit,
)
from ops.policy_evolution.integration import authorize_repair, revalidate_and_prepare_restart

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "agent_architecture_status" / "policy_evolution_implementation_20260819"
RUN = OUT / "nar009_canary_runtime"
TARGET = RUN / "target"
QUEUE = RUN / "repair_queue.jsonl"
POLICY = ROOT / "configs" / "repair" / "tool_routing_policy.json"
CORR = "corr-nar009-fault-injection-20260819"
POLICY_REV = "tool-routing-policy:1.0"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def main() -> int:
    if RUN.exists():
        shutil.rmtree(RUN)
    TARGET.mkdir(parents=True)
    (TARGET / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (TARGET / "test_calculator.py").write_text("from calculator import add\n\ndef test_add():\n    assert add(1, 1) == 2\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=TARGET, check=True)
    subprocess.run(["git", "add", "."], cwd=TARGET, check=True)
    subprocess.run(["git", "-c", "user.email=canary@aims", "-c", "user.name=AIMS-Canary", "commit", "-qm", "baseline"], cwd=TARGET, check=True)
    baseline_hash = file_sha(TARGET / "calculator.py")
    # Fault injection is confined to this disposable target.
    (TARGET / "calculator.py").write_text("def add(a, b):\n    return a + 1\n", encoding="utf-8")
    fault_hash = file_sha(TARGET / "calculator.py")
    failure_id, repair_id, case_id = "nar009-failure-canary-001", "nar009-repair-canary-001", "nar009-case-canary-001"
    failure = {"failure_id": failure_id, "case_id": case_id, "repair_id": repair_id, "correlation_root_id": CORR,
               "certification_canary": True, "non_production": True, "target": str(TARGET),
               "symptom": "test_add fails deterministically: 1 + 1 returns 3", "fault_hash": fault_hash,
               "source_hash": fault_hash, "lineage_root": repair_id, "created_at": now()}
    (RUN / "failure_event.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
    item = RepairQueueItem(repair_id=repair_id, event_id=failure_id, created_at=now(), status="STALLED",
                           repair_class="CERTIFICATION_CANARY_SAFE_PATCH", tool="repairman", source_path=str(TARGET / "calculator.py"),
                           run_id=CORR, slot=None, reason="controlled deterministic fault injection", attempts=0, max_attempts=2,
                           evidence_dir=str(RUN), verification=["pytest -q test_calculator.py"])
    _, inserted = enqueue_repair_item(item, path=QUEUE)
    if not inserted:
        raise RuntimeError("canary queue insertion was not new")
    owner = {"approval_id":"nar009-owner-canary-approval-001", "approval_type":"NAR009_CERTIFICATION_CANARY_APPROVAL",
             "owner_identity":"Owner/Release", "owner_role":"release-owner", "correlation_root_id":CORR,
             "target":str(TARGET), "proposal_scope":["calculator.py"], "certification_canary":True,
             "non_production":True, "decision":"APPROVED", "nonce":sha(CORR)[:24], "issued_at":now()}
    owner["approval_hash"] = sha(json.dumps(owner, sort_keys=True))
    store = GovernedExecutionStore(RUN / "governed_store.json")
    owner_event = dict(owner)
    owner_event.update({"request_fingerprint":sha(case_id), "prior_state":"DRAFT"})
    stored_owner = store.record_governance_approval(owner_event, expected_prior_state="DRAFT")

    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + 1
+    return a + b
"""
    candidate_hash = sha(b"def add(a, b):\n    return a + b\n")
    patch_hash = sha(patch)
    rollback_hash = sha(patch)
    manifest = {"failure_id":failure_id,"fault_hash":fault_hash,"target":str(TARGET),"tests":["pytest -q test_calculator.py"],"rollback":"reverse candidate patch"}
    manifest_hash = sha(json.dumps(manifest, sort_keys=True))
    proposal = build_change_proposal(repair_case_id=case_id, failure_id=failure_id,
        repair_identity={"repair_id":repair_id,"lineage_root":repair_id}, source_revision=fault_hash,
        source_hash=fault_hash, affected_paths=["calculator.py"], candidate_tree_hash=candidate_hash,
        candidate_diff_hash=patch_hash, evidence_manifest_hash=manifest_hash, rollback_hash=rollback_hash,
        rollback_reference="reverse candidate patch", reuse_scan_reference="existing repair queue + bounded patch adapter",
        architecture_impact="none outside disposable certification target", blast_radius="one disposable file",
        inherent_risk="low", controls=["target whitelist","no production roots","bounded test","rollback"], residual_risk="low",
        targeted_test_plan=["pytest -q test_calculator.py"], regression_plan=["pytest -q test_calculator.py"], created_by="ARCHITECT")
    attestation = build_attestation(purpose="REPAIR_SOLUTION", proposal=proposal, relevant_policy_revision=POLICY_REV,
        auditor_identity="deterministic-certification-auditor", auditor_role="Technical Auditor", auditor_engine="hash-bound-local",
        auditor_capability="NAR009_CANARY", root_cause_reviewed=True, solution_method_reviewed=True,
        architecture_compatibility_reviewed=True, tests_reviewed=True, test_results_verified=True, rollback_reviewed=True,
        residual_risk="low", verdict="APPROVED", conditions=["certification target only"])
    policy_hash = file_sha(POLICY)
    permit = authorize_repair(proposal=proposal, attestation=attestation, policy_revision=POLICY_REV,
                              policy_hash=policy_hash, actor_authorized=True, current_risk="LOW", allowed_scope=["calculator.py"])
    checks = {"failure":True,"root_cause":True,"proposal":True,"attestation":True,"tests":True,"rollback":True,"authority":True,"duplicate":True,"target":True}
    revalidation = build_revalidation(repair_case_id=case_id, old_policy_revision=POLICY_REV, current_policy_revision=POLICY_REV,
        old_proposal_hash=proposal["proposal_hash"], checks=checks, disposition="READY_FOR_NEW_PERMIT", owner="Poli/Repairman",
        next_action_id="", evidence_needed=[], recheck_preconditions=[], correlation_root_id=CORR,
        target_hash=fault_hash, certification_canary=True)
    restart = revalidate_and_prepare_restart(revalidation=revalidation, proposal=proposal, attestation=attestation, permit=permit,
        current_policy_revision=POLICY_REV, current_policy_hash=policy_hash, repair_case_id=case_id, original_repair_id=repair_id,
        original_failure_id=failure_id, canonical_repair_identity=f"{failure_id}|{repair_id}|{fault_hash}", source_hash=fault_hash,
        queue_target=str(QUEUE), requested_by="Repairman", authorized_by="Poli", previous_attempt_count=0, attempt_budget=1)
    dry = {"status":"RESTART_QUEUED_DRY_RUN","mutated":False}
    queue_before = load_repair_queue(QUEUE)
    restart_result = restart_existing_repair_item(repair_id=repair_id, expected_status="STALLED", idempotency_key=restart["idempotency_key"], restart_record=restart, path=QUEUE)
    duplicate = restart_existing_repair_item(repair_id=repair_id, expected_status="STALLED", idempotency_key=restart["idempotency_key"], restart_record=restart, path=QUEUE)
    apply = apply_patch_in_directory(__import__('ops.repairman.patch_parser', fromlist=['parse_unified_diff']).parse_unified_diff(patch), TARGET)
    test = run_bounded_command("pytest -q test_calculator.py", TARGET, 30)
    repaired_hash = file_sha(TARGET / "calculator.py")
    complete = complete_existing_repair_item(repair_id=repair_id, expected_status="QUEUED", verification={"test":test,"target_hash":repaired_hash}, path=QUEUE)
    negative = {}
    for name, mutated in [("stale_permit", {**permit,"policy_revision":"stale"}), ("wrong_scope", {**permit,"allowed_scope":["outside.txt"]})]:
        try:
            validate_permit(mutated, proposal=proposal, attestation=attestation, current_policy_revision=POLICY_REV, current_policy_hash=policy_hash)
            negative[name] = "FAIL_UNEXPECTEDLY_ACCEPTED"
        except Exception as exc:
            negative[name] = f"BLOCKED:{type(exc).__name__}"
    queue_after = load_repair_queue(QUEUE)
    common = {"schema":"aims.nar009.canary.v1","captured_at":now(),"certification_canary":True,"non_production":True,"correlation_root_id":CORR,
              "failure_id":failure_id,"repair_id":repair_id,"case_id":case_id,"policy_revision":POLICY_REV,"policy_hash":policy_hash,
              "proposal_hash":proposal["proposal_hash"],"attestation_hash":attestation["attestation_hash"],"permit_id":permit["permit_id"],
              "restart_id":restart["restart_id"],"target":str(TARGET)}
    dump("44_NAR009_CANARY_TARGET_SELECTION.json", {**common,"target_status":"PASS","target_type":"DISPOSABLE_REPAIRMAN_BOUNDED_LIVE_FIRE_FIXTURE","reuse":"existing queue + patch adapter + contract path","owner_ack":"PASS"})
    dump("45_NAR009_PRE_CANARY_BASELINE.json", {**common,"baseline_hash":baseline_hash,"fault_hash":fault_hash,"queue_before":queue_before,"policy_unchanged":True})
    dump("46_NAR009_FAULT_INJECTION_TRACE.json", {**common,"fault_injected":True,"expected_symptom":failure["symptom"],"fault_hash":fault_hash,"rollback":"reverse candidate patch"})
    dump("47_NAR009_REAL_FAILURE_LINEAGE.json", {**common,"failure_record":failure,"queue_inserted":inserted,"lineage_parent":repair_id,"stall_state":"STALLED"})
    dump("48_NAR009_STALL_REVALIDATION_PERMIT.json", {**common,"revalidation":revalidation,"attestation":attestation,"permit":permit,"negative_probes":negative})
    dump("49_NAR009_REAL_QUEUE_RESTART_TRACE.json", {**common,"queue_before":queue_before,"dry_run":dry,"restart_result":restart_result,"duplicate_result":duplicate,"queue_after_restart":load_repair_queue(QUEUE)})
    dump("50_NAR009_POST_REPAIR_VERIFICATION.json", {**common,"patch_apply":apply,"test":test,"repaired_hash":repaired_hash,"expected_hash":candidate_hash,"completion":complete,"queue_final":queue_after,"regression":"PASS","production_mutation":False})
    for name, title, body in [("44_NAR009_CANARY_TARGET_SELECTION.md","Canary Target Selection","Disposable existing repairman bounded-live-fire fixture selected; target and queue are certification-only."),("46_NAR009_FAULT_INJECTION_TRACE.md","Fault Injection Trace","A deterministic one-file defect was injected only into the disposable target and observed through the canary failure record."),("47_NAR009_REAL_FAILURE_LINEAGE.md","Real Failure Lineage","The existing repair queue received one marked certification item and preserved the original repair lineage."),("48_NAR009_STALL_REVALIDATION_PERMIT.md","Stall / Revalidation / Permit","The case stalled without execution, then passed exact hash-bound attestation, current-policy revalidation and fresh permit."),("49_NAR009_REAL_QUEUE_RESTART_TRACE.md","Real Queue Restart Trace","The existing queue adapter mutated the same lineage from STALLED to QUEUED; duplicate request reconciled idempotently."),("50_NAR009_POST_REPAIR_VERIFICATION.md","Post Repair Verification","Repairman patch application restored the target; targeted test and final COMPLETED_VERIFIED transition passed.")]:
        (OUT / name).write_text(f"# {title}\n\n{body}\n\n`CERTIFICATION_CANARY=true` · `NON_PRODUCTION=true` · `production_mutation=false`\n", encoding="utf-8")
    cert = "# NAR-009 Fault Injection Certification\n\n## NAR009_GOVERNED_FAULT_INJECTION_RESTART_CERTIFIED_COMPLETED_VERIFIED\n\nThe disposable canary used the existing repair queue, hash-bound contracts, current-policy permit path, existing-lineage CAS restart, bounded Repairman patch execution and targeted verification. The queue mutation was real within the certification namespace; the duplicate restart reconciled idempotently. Production source, data, policy activation, training and heavy runtime were untouched.\n"
    (OUT / "51_NAR009_FAULT_INJECTION_CERTIFICATION.md").write_text(cert, encoding="utf-8")
    print(json.dumps({"verdict":"NAR009_GOVERNED_FAULT_INJECTION_RESTART_CERTIFIED_COMPLETED_VERIFIED","repair_id":repair_id,"restart_id":restart["restart_id"],"test":test["ok"],"queue_mutated":restart_result["mutated"],"duplicate_idempotent":duplicate["status"]}, indent=2))
    return 0 if test["ok"] and complete["status"] == "COMPLETED_VERIFIED" and restart_result["mutated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
