#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .skill_version_delta_builder import build_delta
    from .skill_scope_delta_validator import validate_scope_delta
    from .skill_regression_test_runner import run_regression_tests
    from .active_skill_version_updater import update_active_skill_entry
    from .owner_binding_version_updater import update_owner_binding
    from .skill_improvement_evidence_writer import build_evidence_pack
    from .within_scope_skill_improvement_validator import verify_phase26_acceptance, validate_result
except ImportError:
    from agents.self_learning.within_scope_skill_improvement.skill_version_delta_builder import build_delta  # type: ignore
    from agents.self_learning.within_scope_skill_improvement.skill_scope_delta_validator import validate_scope_delta  # type: ignore
    from agents.self_learning.within_scope_skill_improvement.skill_regression_test_runner import run_regression_tests  # type: ignore
    from agents.self_learning.within_scope_skill_improvement.active_skill_version_updater import update_active_skill_entry  # type: ignore
    from agents.self_learning.within_scope_skill_improvement.owner_binding_version_updater import update_owner_binding  # type: ignore
    from agents.self_learning.within_scope_skill_improvement.skill_improvement_evidence_writer import build_evidence_pack  # type: ignore
    from agents.self_learning.within_scope_skill_improvement.within_scope_skill_improvement_validator import verify_phase26_acceptance, validate_result  # type: ignore


def _load_json(path: Path, key: str | None = None):
    data = json.loads(path.read_text(encoding="utf-8"))
    if key is None:
        return data
    return data.get(key, []) if isinstance(data, dict) else []


def run_workflow(activation_dir: Path, monitoring_dir: Path, out_dir: Path) -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    ok26, errs26 = verify_phase26_acceptance(repo_root)
    if not ok26:
        raise RuntimeError(f"Phase26 acceptance failed: {errs26}")

    out_dir.mkdir(parents=True, exist_ok=True)

    active_entries = _load_json(activation_dir / "active_skill_registry.json", "active_skill_registry_entries")
    bindings = _load_json(activation_dir / "owner_agent_skill_bindings.json", "owner_agent_bindings")
    rollback = _load_json(activation_dir / "rollback_manifest.json", "rollback_entries")
    _ = _load_json(activation_dir / "activation_evidence_pack.json")

    events = _load_json(monitoring_dir / "active_skill_monitoring_events.json", "events")
    assessments = _load_json(monitoring_dir / "active_skill_performance_assessment.json", "assessments")
    plans = _load_json(monitoring_dir / "skill_improvement_plan.json", "improvement_plans")
    _ = _load_json(monitoring_dir / "skill_feedback_evidence_pack.json")
    feedback_queue = _load_json(monitoring_dir / "next_self_learning_feedback_queue.json")

    queue_items = feedback_queue.get("queued_items", [])

    eligible = [
        i for i in queue_items
        if i.get("next_processor") == "WITHIN_SCOPE_SKILL_IMPROVEMENT_PIPELINE"
        and i.get("execution_allowed") is True
    ]

    deltas = []
    validations = []
    regressions = []
    updated_active = []
    updated_bindings = []
    skipped = 0
    new_approval_requests = 0

    for item in eligible:
        aid = item.get("active_skill_id")
        ae = next((x for x in active_entries if x.get("active_skill_id") == aid), None)
        if not ae:
            skipped += 1
            continue
        ass = next((x for x in assessments if x.get("active_skill_id") == aid), None)
        plan = next((x for x in plans if x.get("active_skill_id") == aid), None)
        if not ass or not plan:
            skipped += 1
            continue

        if plan.get("new_approval_required") or plan.get("scope_expansion_required"):
            new_approval_requests += 1
            continue

        ev_ids = [e.get("event_id") for e in events if e.get("active_skill_id") == aid]
        delta = build_delta(ae, ass, plan, ev_ids)
        deltas.append(delta)

        sv = validate_scope_delta(delta, ae)
        validations.append(sv)

        reg = run_regression_tests(delta, sv)
        regressions.append(reg)

        if sv.get("validation_status") in {"PASS_WITHIN_SCOPE", "WARN_WITHIN_SCOPE"} and reg.get("result_status") in {"REGRESSION_PASS", "REGRESSION_WARN_PASS"}:
            upd = update_active_skill_entry(ae, delta, sv, reg)
            updated_active.append(upd)

            b = next((x for x in bindings if x.get("active_skill_id") == aid), None)
            if b:
                updated_bindings.append(update_owner_binding(b, delta, upd))
        else:
            if sv.get("new_approval_required"):
                new_approval_requests += 1

    next_queue = {
        "queue_id": f"NMQ-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "queued_items": [
            {
                "active_skill_id": u.get("active_skill_id"),
                "version": u.get("version"),
                "status": "READY_FOR_NEXT_MONITORING",
            }
            for u in updated_active
        ],
        "next_processor": "ACTIVE_SKILL_MONITORING_LOOP",
        "execution_allowed": True,
        "reason": "Within-scope skill improvement completed; updated skill remains active and must continue to be monitored.",
    }

    report = {
        "active_skills_loaded": len(active_entries),
        "monitoring_queue_items_loaded": len(queue_items),
        "within_scope_items_consumed": len(eligible),
        "deltas_created": len(deltas),
        "scope_validations_passed": sum(1 for v in validations if v.get("validation_status") in {"PASS_WITHIN_SCOPE", "WARN_WITHIN_SCOPE"}),
        "scope_validations_blocked": sum(1 for v in validations if v.get("validation_status") not in {"PASS_WITHIN_SCOPE", "WARN_WITHIN_SCOPE"}),
        "regression_tests_run": len(regressions),
        "regression_pass": sum(1 for r in regressions if r.get("result_status") == "REGRESSION_PASS"),
        "regression_warn_pass": sum(1 for r in regressions if r.get("result_status") == "REGRESSION_WARN_PASS"),
        "regression_fail": sum(1 for r in regressions if r.get("result_status") == "REGRESSION_FAIL"),
        "active_skill_versions_updated": len(updated_active),
        "owner_bindings_updated": len(updated_bindings),
        "new_approval_requests_created": new_approval_requests,
        "next_monitoring_items_queued": len(next_queue.get("queued_items", [])),
        "safety_status": "PASS" if new_approval_requests == 0 else "PASS_WITH_NEW_APPROVAL_REQUIRED",
        "next_action": "CONTINUE_ACTIVE_SKILL_MONITORING_LOOP" if new_approval_requests == 0 else "CREATE_NEW_SCOPE_APPROVAL_REQUEST",
    }

    val = validate_result(report)
    if not val.get("ok"):
        report["safety_status"] = "FAIL"
        report["validator_errors"] = val.get("errors", [])

    (out_dir / "skill_version_delta.json").write_text(json.dumps({"deltas": deltas}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "scope_delta_validation.json").write_text(json.dumps({"scope_validations": validations}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "regression_test_results.json").write_text(json.dumps({"regression_results": regressions}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "updated_active_skill_registry.json").write_text(json.dumps({"active_skill_registry_entries": updated_active}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "updated_owner_agent_skill_bindings.json").write_text(json.dumps({"owner_agent_bindings": updated_bindings}, indent=2, ensure_ascii=False), encoding="utf-8")

    evidence = build_evidence_pack(
        {
            "source_phase25_artifacts": [str(activation_dir)],
            "source_phase26_artifacts": [str(monitoring_dir)],
            "deltas_created": len(deltas),
            "scope_validations_passed": report["scope_validations_passed"],
            "scope_validations_blocked": report["scope_validations_blocked"],
            "regression_tests_run": len(regressions),
            "regression_tests_passed": report["regression_pass"] + report["regression_warn_pass"],
            "active_skill_versions_updated": len(updated_active),
            "owner_bindings_updated": len(updated_bindings),
            "new_approval_requests_created": new_approval_requests,
            "skipped_items": skipped,
        }
    )
    (out_dir / "skill_improvement_evidence_pack.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    (out_dir / "next_monitoring_cycle_queue.json").write_text(json.dumps(next_queue, indent=2, ensure_ascii=False), encoding="utf-8")

    (out_dir / "within_scope_skill_improvement_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "within_scope_skill_improvement_report.md").write_text("\n".join([
        "# AIMS Phase 27 — Within Scope Skill Improvement",
        "",
        *[f"- {k}: {v}" for k, v in report.items() if k != "validator_errors"],
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="AIMS Phase 27 within-scope skill improvement workflow")
    ap.add_argument("--activation-dir", required=True, type=Path)
    ap.add_argument("--monitoring-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    r = run_workflow(args.activation_dir, args.monitoring_dir, args.out)
    for k in [
        "active_skills_loaded","monitoring_queue_items_loaded","within_scope_items_consumed",
        "deltas_created","scope_validations_passed","scope_validations_blocked","regression_tests_run",
        "regression_pass","regression_warn_pass","regression_fail","active_skill_versions_updated",
        "owner_bindings_updated","new_approval_requests_created","next_monitoring_items_queued",
        "safety_status","next_action"
    ]:
        print(f"{k:32}: {r[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
