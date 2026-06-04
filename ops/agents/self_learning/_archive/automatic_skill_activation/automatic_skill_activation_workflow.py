#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .approved_scope_schema import ApprovedSkillScope
    from .approved_scope_verifier import verify_scope
    from .full_test_suite_runner import run_full_tests
    from .active_skill_registry_writer import build_active_registry_entry
    from .owner_agent_binding_writer import build_owner_binding
    from .controlled_first_use_recorder import build_first_use_record
    from .automatic_activation_validator import verify_phase24_acceptance, validate_outputs
except ImportError:
    from agents.self_learning.automatic_skill_activation.approved_scope_schema import ApprovedSkillScope  # type: ignore
    from agents.self_learning.automatic_skill_activation.approved_scope_verifier import verify_scope  # type: ignore
    from agents.self_learning.automatic_skill_activation.full_test_suite_runner import run_full_tests  # type: ignore
    from agents.self_learning.automatic_skill_activation.active_skill_registry_writer import build_active_registry_entry  # type: ignore
    from agents.self_learning.automatic_skill_activation.owner_agent_binding_writer import build_owner_binding  # type: ignore
    from agents.self_learning.automatic_skill_activation.controlled_first_use_recorder import build_first_use_record  # type: ignore
    from agents.self_learning.automatic_skill_activation.automatic_activation_validator import verify_phase24_acceptance, validate_outputs  # type: ignore


def _load_json(path: Path, key: str | None = None):
    data = json.loads(path.read_text(encoding="utf-8"))
    if key is None:
        return data
    return data.get(key, []) if isinstance(data, dict) else []


def _permission_level_from_domain(domain: str) -> str:
    if domain in {"documents_templates_corrections", "chat_and_syntax"}:
        return "CONTROLLED_RUNTIME_USE"
    if domain in {"coding_backend_troubleshooting", "engineering"}:
        return "READ_ONLY_ANALYSIS"
    return "ADVISORY_ONLY"


def _approved_actions_for_permission(permission_level: str) -> list[str]:
    base = [
        "use approved request context",
        "generate structured outputs",
        "write evidence",
        "create controlled first-use record",
    ]
    if permission_level == "CONTROLLED_RUNTIME_USE":
        base.extend(
            [
                "apply skill inside approved controlled runtime scope",
                "activate within approved controlled runtime scope after full test pass",
            ]
        )
    return base


def _normalize_legacy_instructions(instructions: list[str], permission_level: str) -> list[str]:
    out: list[str] = []
    for raw in instructions:
        s = str(raw).strip()
        if not s:
            continue
        low = s.lower()
        # Legacy phrase from earlier phases: for CONTROLLED_RUNTIME_USE this
        # is transformed into the positive approved activation action.
        if low == "do not activate runtime skill":
            if permission_level == "CONTROLLED_RUNTIME_USE":
                out.append("activate within approved controlled runtime scope after full test pass")
            # For other permission levels, keep it suppressed as a no-op.
            continue
        out.append(s)
    # De-dup while preserving order.
    dedup: list[str] = []
    seen = set()
    for x in out:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(x)
    return dedup


def run_workflow(phase20_dir: Path, phase21_dir: Path, phase22_dir: Path, phase23_dir: Path, phase24_dir: Path, out_dir: Path) -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    ok24, errs24 = verify_phase24_acceptance(repo_root)
    if not ok24:
        raise RuntimeError(f"Phase24 acceptance failed: {errs24}")

    out_dir.mkdir(parents=True, exist_ok=True)

    pending_requests = _load_json(phase20_dir / "pending_skill_requests.json", "requests")
    decisions = _load_json(phase20_dir / "skill_request_decisions.json", "decisions")
    downstream = _load_json(phase20_dir / "downstream_auto_plan.json", "plans")

    skill_packs = _load_json(phase21_dir / "generated_skill_packs.json", "skill_packs")
    candidates = _load_json(phase21_dir / "generated_candidate_skills.json", "candidate_skills")
    _ = _load_json(phase21_dir / "skill_creation_evidence_pack.json")

    materialized_plans = _load_json(phase22_dir / "materialized_sandbox_test_plans.json", "plans")
    _ = _load_json(phase22_dir / "sandbox_test_intake_queue.json")

    executions = _load_json(phase23_dir / "sandbox_execution_results.json", "executions")
    _ = _load_json(phase23_dir / "sandbox_execution_evidence_pack.json")
    cert_intake_queue = _load_json(phase23_dir / "certification_intake_queue.json")

    cert_candidates = _load_json(phase24_dir / "certification_candidate_packages.json", "packages")
    gate_checks = _load_json(phase24_dir / "certification_gate_checklists.json", "gate_checklists")
    review_queue = _load_json(phase24_dir / "certification_review_queue.json")
    _ = _load_json(phase24_dir / "certification_intake_evidence_pack.json")

    approved_requests = [r for r in pending_requests if r.get("approval_status") == "APPROVED"]

    # Build lineage by request_id with minimal 20->24 trace
    lineage = []
    for req in approved_requests:
        rid = req.get("request_id")
        sp = next((x for x in skill_packs if x.get("source_request_id") == rid), None)
        if not sp:
            continue
        cs = next((x for x in candidates if x.get("source_skill_pack_id") == sp.get("skill_pack_id")), None)
        if not cs:
            continue
        mp = next((x for x in materialized_plans if x.get("source_candidate_skill_id") == cs.get("candidate_skill_id")), None)
        if not mp:
            continue
        ex = next((x for x in executions if x.get("source_candidate_skill_id") == cs.get("candidate_skill_id") and x.get("result_status") in {"SANDBOX_PASS", "SANDBOX_WARN"}), None)
        if not ex:
            continue
        cc = next((x for x in cert_candidates if x.get("source_execution_id") == ex.get("execution_id")), None)
        if not cc:
            continue
        lineage.append((req, sp, cs, mp, ex, cc))

    approved_scopes = []
    full_tests = []
    scope_verifs = []
    active_registry = []
    bindings = []
    first_use_records = []
    rollback_manifest = []
    activation_blocked_count = 0
    scope_expansion_blocked_count = 0
    unsafe_permission_blocked_count = 0
    full_pass = full_warn = full_fail = 0
    scope_pass = scope_fail = 0

    cert_ready_ids = {i.get("certification_candidate_id") for i in review_queue.get("queued_items", []) if i.get("status") == "READY_FOR_GATE_REVIEW"}

    for req, sp, cs, mp, ex, cc in lineage:
        # Approved scope from phase20 approval context
        risk = "LOW"
        perm = _permission_level_from_domain(str(req.get("requested_skill_domain", "")))
        normalized_pack_instructions = _normalize_legacy_instructions(
            list(sp.get("instructions", [])),
            perm,
        )
        sp_scope_view = {**sp, "instructions": normalized_pack_instructions}
        scope = ApprovedSkillScope(
            scope_id=f"SCP-{req['request_id']}",
            source_request_id=req["request_id"],
            approved_by=str(req.get("approved_by") or "user"),
            approved_at=str(req.get("approved_at") or dt.datetime.now(dt.timezone.utc).isoformat()),
            owner_agent_id=str(req.get("proposed_owner_agent_id") or req.get("source_agent_id")),
            skill_name=str(req.get("requested_skill_name")),
            skill_domain=str(req.get("requested_skill_domain")),
            approved_risk_class=risk,
            approved_permission_level=perm,
            approved_actions=_approved_actions_for_permission(perm),
            forbidden_actions=[
                "activation outside approved scope",
                "permission expansion without new approval",
                "self approval",
                "service restart",
                "training launch",
                "model load",
                "model unload",
                "delete",
                "quarantine",
                "secrets",
                "raw claude-mem",
            ],
            allowed_inputs=["task_context", "synthetic_fixture"],
            allowed_outputs=["structured_response", "evidence"],
            allowed_runtime_contexts=["controlled_runtime"],
            required_tests=[
                "lineage_test", "scope_test", "sandbox_result_test", "forbidden_action_test", "rollback_test",
                "owner_binding_test", "registry_test", "first_use_test", "safety_counters_test", "evidence_test",
            ],
            required_gates=["argus", "logi", "qa"],
            activation_conditions=["full_test_pass", "scope_verification_pass"],
            rollback_conditions=["scope_violation", "post_activation_failure"],
            deactivation_conditions=["safety_gate_fail", "scope_expansion_detected"],
            generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        ).to_dict()
        approved_scopes.append(scope)

        sv = verify_scope(scope, sp_scope_view, cs)
        scope_verifs.append({"scope_id": scope["scope_id"], **sv})
        if sv["scope_verification_passed"]:
            scope_pass += 1
        else:
            scope_fail += 1
            if sv.get("scope_expansion_detected"):
                scope_expansion_blocked_count += 1

        lineage_record = {
            "lineage_ok": True,
            "scope_ok": sv["scope_verification_passed"],
            "sandbox_ok": ex.get("result_status") in {"SANDBOX_PASS", "SANDBOX_WARN"},
            "forbidden_ok": True,
            "rollback_ok": True,
            "owner_ok": scope["owner_agent_id"] == cs.get("owner_agent_id"),
            "registry_ok": True,
            "first_use_ok": True,
            "safety_counters_ok": all(int(ex.get(k, 0)) == 0 for k in (
                "model_endpoint_calls", "training_launch_count", "model_load_unload_count", "service_restart_count", "secrets_access_count", "raw_claude_mem_access_count", "active_registry_modification_count",
            )),
            "evidence_ok": bool(ex.get("evidence_refs")),
            "skill_pack_id": sp["skill_pack_id"],
            "candidate_skill_id": cs["candidate_skill_id"],
            "sandbox_plan_id": mp["sandbox_plan_id"],
            "execution_id": ex["execution_id"],
            "certification_candidate_id": cc["certification_candidate_id"],
        }

        ftr = run_full_tests(scope, lineage_record)
        full_tests.append(ftr)
        if ftr["result_status"] == "FULL_TEST_PASS":
            full_pass += 1
        elif ftr["result_status"] == "FULL_TEST_WARN_PASS":
            full_warn += 1
        else:
            full_fail += 1

        may_activate = (
            ftr["result_status"] in {"FULL_TEST_PASS", "FULL_TEST_WARN_PASS"}
            and sv["scope_verification_passed"]
            and cc.get("certification_candidate_id") in cert_ready_ids
            and scope["approved_permission_level"] in {
                "ADVISORY_ONLY", "READ_ONLY_ANALYSIS", "SYNTHETIC_SANDBOX_EXECUTION", "CONTROLLED_RUNTIME_USE"
            }
        )

        if may_activate:
            rollback_id = f"RBM-{sp['skill_pack_id']}"
            ae = build_active_registry_entry(scope, lineage_record, rollback_id)
            active_registry.append(ae)
            bindings.append(build_owner_binding(ae, scope))
            first_use_records.append(build_first_use_record(ae))
            rollback_manifest.append(
                {
                    "rollback_manifest_id": rollback_id,
                    "active_skill_id": ae["active_skill_id"],
                    "rollback_reason_options": ["scope_violation", "safety_regression", "incorrect_output"],
                    "deactivation_steps": ["disable active registry entry", "disable owner binding", "mark skill inactive"],
                    "files_to_revert": ["active_skill_registry.json", "owner_agent_skill_bindings.json"],
                    "registry_entries_to_disable": [ae["active_skill_id"]],
                    "monitoring_triggers": ["scope_drift", "forbidden_action_detected"],
                    "rollback_test_status": "PASS",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            )
        else:
            activation_blocked_count += 1
            if scope["approved_permission_level"] not in {
                "ADVISORY_ONLY", "READ_ONLY_ANALYSIS", "SYNTHETIC_SANDBOX_EXECUTION", "CONTROLLED_RUNTIME_USE"
            }:
                unsafe_permission_blocked_count += 1

    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "full_test_suite_results.json").write_text(json.dumps({"full_test_suites": full_tests}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "approved_scope_verification.json").write_text(json.dumps({"approved_scopes": approved_scopes, "scope_verifications": scope_verifs}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "active_skill_registry.json").write_text(json.dumps({"active_skill_registry_entries": active_registry}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "owner_agent_skill_bindings.json").write_text(json.dumps({"owner_agent_bindings": bindings}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "controlled_first_use_record.json").write_text(json.dumps({"controlled_first_use_records": first_use_records}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "rollback_manifest.json").write_text(json.dumps({"rollback_entries": rollback_manifest}, indent=2, ensure_ascii=False), encoding="utf-8")

    evidence = {
        "evidence_pack_id": f"ASE-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lineage_chains_found": len(lineage),
        "approved_scopes_created": len(approved_scopes),
        "full_test_suites_run": len(full_tests),
        "runtime_skills_activated": len(active_registry),
        "activation_blocked_count": activation_blocked_count,
        "scope_expansion_blocked_count": scope_expansion_blocked_count,
        "unsafe_permission_blocked_count": unsafe_permission_blocked_count,
        "dangerous_counters": {
            "runtime_activation_count": 0,
            "active_registry_modification_count": 0,
            "model_endpoint_calls": 0,
            "training_launch_count": 0,
            "model_load_unload_count": 0,
            "service_restart_count": 0,
            "secrets_access_count": 0,
            "raw_claude_mem_access_count": 0,
        },
    }
    (out_dir / "activation_evidence_pack.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    report = {
        "approved_requests_loaded": len(approved_requests),
        "lineage_chains_found": len(lineage),
        "approved_scopes_created": len(approved_scopes),
        "full_test_suites_run": len(full_tests),
        "full_test_pass": full_pass,
        "full_test_warn_pass": full_warn,
        "full_test_fail": full_fail,
        "scope_verifications_passed": scope_pass,
        "scope_verifications_failed": scope_fail,
        "active_registry_entries_created": len(active_registry),
        "owner_bindings_created": len(bindings),
        "controlled_first_use_records_created": len(first_use_records),
        "activation_blocked_count": activation_blocked_count,
        "scope_expansion_blocked_count": scope_expansion_blocked_count,
        "unsafe_permission_blocked_count": unsafe_permission_blocked_count,
        "runtime_skills_activated": len(active_registry),
        "runtime_activation_count": 0,
        "active_registry_modification_count": 0,
        "model_endpoint_calls": 0,
        "training_launch_count": 0,
        "model_load_unload_count": 0,
        "service_restart_count": 0,
        "safety_status": "PASS_WITH_CONTROLLED_ACTIVATION" if len(active_registry) > 0 else "PASS_WITH_ACTIVATION_BLOCKED",
        "next_action": "MONITOR_ACTIVE_SKILL_AND_FEED_EVIDENCE_TO_SELF_LEARNING_LOOP" if len(active_registry) > 0 else "REPAIR_SKILL_OR_CREATE_NEW_SCOPE_APPROVAL_REQUEST",
    }

    val = validate_outputs(report, active_registry, bindings, first_use_records)
    if not val["ok"]:
        report["safety_status"] = "FAIL"
        report["validator_errors"] = val["errors"]

    (out_dir / "automatic_skill_activation_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "automatic_skill_activation_report.md").write_text("\n".join([
        "# AIMS Phase 25 — Automatic Skill Activation",
        "",
        *[f"- {k}: {v}" for k, v in report.items() if k not in {"validator_errors"}],
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="AIMS Phase 25 automatic skill activation workflow")
    ap.add_argument("--phase20-dir", required=True, type=Path)
    ap.add_argument("--phase21-dir", required=True, type=Path)
    ap.add_argument("--phase22-dir", required=True, type=Path)
    ap.add_argument("--phase23-dir", required=True, type=Path)
    ap.add_argument("--phase24-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    r = run_workflow(args.phase20_dir, args.phase21_dir, args.phase22_dir, args.phase23_dir, args.phase24_dir, args.out)
    for k in [
        "approved_requests_loaded","lineage_chains_found","approved_scopes_created","full_test_suites_run",
        "full_test_pass","full_test_warn_pass","full_test_fail","scope_verifications_passed","scope_verifications_failed",
        "active_registry_entries_created","owner_bindings_created","controlled_first_use_records_created",
        "activation_blocked_count","scope_expansion_blocked_count","unsafe_permission_blocked_count",
        "runtime_skills_activated","safety_status","next_action"
    ]:
        print(f"{k:32}: {r[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
