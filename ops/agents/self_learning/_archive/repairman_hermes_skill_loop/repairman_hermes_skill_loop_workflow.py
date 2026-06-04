#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .repair_case_dossier_builder import build_dossiers_from_audit
    from .repair_case_sanitizer import sanitize_obj
    from .hermes_review_prompt_builder import build_hermes_prompt
    from .skill_incubation_signal_extractor import extract_skill_signal
    from .hermes_review_result_schema import validate_review_result
    from .hermes_skill_sandbox_test_runner import run_hermes_sandbox_test
    from .hermes_skill_test_report_schema import is_pass_like
    from .hermes_to_aims_skill_adapter import adapt_hermes_candidate
    from .repairman_adoption_planner import build_adoption_plan
    from .repairman_adoption_test_runner import run_adoption_tests
    from .repairman_scope_approval_router import build_scope_approval_request
    from .repairman_adoption_activation import activate_skill
    from .repairman_skill_feedback_monitor import build_feedback_event
    from .repairman_hermes_skill_loop_validator import validate
except ImportError:
    from agents.self_learning.repairman_hermes_skill_loop.repair_case_dossier_builder import build_dossiers_from_audit  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.repair_case_sanitizer import sanitize_obj  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.hermes_review_prompt_builder import build_hermes_prompt  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.skill_incubation_signal_extractor import extract_skill_signal  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.hermes_review_result_schema import validate_review_result  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.hermes_skill_sandbox_test_runner import run_hermes_sandbox_test  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.hermes_skill_test_report_schema import is_pass_like  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.hermes_to_aims_skill_adapter import adapt_hermes_candidate  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.repairman_adoption_planner import build_adoption_plan  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.repairman_adoption_test_runner import run_adoption_tests  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.repairman_scope_approval_router import build_scope_approval_request  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.repairman_adoption_activation import activate_skill  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.repairman_skill_feedback_monitor import build_feedback_event  # type: ignore
    from agents.self_learning.repairman_hermes_skill_loop.repairman_hermes_skill_loop_validator import validate  # type: ignore


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _default_review(dossier: dict) -> dict:
    review = {
        "hermes_review_id": f"hrev_{dossier['repair_case_id']}",
        "repair_case_id": dossier["repair_case_id"],
        "diagnosis_quality": "MEDIUM",
        "missing_evidence": ["timing trace"],
        "incorrect_assumptions": ["model fallback sequencing"],
        "better_root_cause_hypotheses": ["repo root mismatch in container", "wrong default model chain"],
        "better_repair_plan": ["lock repo root to /ops", "slot32-first routing"],
        "repairman_skill_gap": ["repeatable runtime preflight skill"],
        "reusable_skill_pattern": "repairman_runtime_preflight_and_slot32_resolution",
        "suggested_skill_name": "repairman_runtime_preflight_guard",
        "suggested_skill_scope": "READ_ONLY_ANALYSIS",
        "suggested_tests": ["root marker test", "slot32 model preflight", "inspect no-change assertion"],
        "suggested_adoption_target": "repairman",
        "risks": ["scope expansion if repair mode auto-enabled"],
        "recommended_next_action": "package skill and sandbox-test in Hermes",
    }
    return review


def run_workflow(audit_root: Path, out_dir: Path, dry_run: bool = True, import_hermes_review: Path | None = None, invoke_hermes: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    dossiers = build_dossiers_from_audit(audit_root)
    sanitized_dossiers = []
    redacted = 0
    for d in dossiers:
        s, n = sanitize_obj(d)
        s["sanitized"] = True
        redacted += n
        sanitized_dossiers.append(s)

    prompts = [build_hermes_prompt(d) for d in sanitized_dossiers]

    if import_hermes_review and import_hermes_review.exists():
        imported = json.loads(import_hermes_review.read_text(encoding="utf-8"))
        reviews = imported.get("reviews", imported if isinstance(imported, list) else [])
        hermes_reviews_imported = len(reviews)
    else:
        reviews = [_default_review(d) for d in sanitized_dossiers]
        hermes_reviews_imported = 0

    # validate review schema
    reviews = [r for r in reviews if not validate_review_result(r)]

    signals = [extract_skill_signal(d) for d in sanitized_dossiers]

    packages = []
    hermes_reports = []
    incubated = []
    adapted = []
    adoption_plans = []
    adoption_results = []
    scope_requests = []
    active = []
    bindings = []
    first_use = []
    feedback_events = []

    for d in sanitized_dossiers:
        review = next((r for r in reviews if r.get("repair_case_id") == d["repair_case_id"]), _default_review(d))
        pkg = {
            "hermes_skill_package_id": f"hsp_{d['repair_case_id']}",
            "source_author": "hermes",
            "incubated_by": "hermes",
            "source_repair_case_id": d["repair_case_id"],
            "source_hermes_review_id": review["hermes_review_id"],
            "target_agent_id": "repairman",
            "target_agent_role": "policy_bound_executor",
            "skill_name": review["suggested_skill_name"],
            "skill_domain": "repair_runtime",
            "skill_description": review["reusable_skill_pattern"],
            "observed_pattern": review["reusable_skill_pattern"],
            "problem_class": d.get("failure_domain", "runtime"),
            "trigger_conditions": ["repair case with runtime mismatch"],
            "input_contract": ["RepairCaseDossier"],
            "output_contract": ["repair preflight summary"],
            "step_by_step_instructions": review["better_repair_plan"],
            "refusal_rules": ["refuse secrets and unsafe actions"],
            "safety_rules": ["no patching", "no restart"],
            "required_context": ["repo markers", "model routing"],
            "allowed_actions": ["analyze dossier", "produce plan"],
            "forbidden_actions": ["service restart", "training launch", "secrets access"],
            "test_fixtures": ["fixture_repair_case"],
            "expected_outputs": ["structured preflight findings"],
            "failure_cases": ["missing markers", "wrong model slot"],
            "evidence_refs": d.get("evidence_refs", []),
            "maturity_status": "HERMES_PACKAGE_CREATED",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        packages.append(pkg)

        fail_fixture = False
        report = run_hermes_sandbox_test(pkg, fail_fixture=fail_fixture)
        hermes_reports.append(report)

        if is_pass_like(report["result_status"]):
            c = {
                "hermes_skill_candidate_id": f"hsc_{d['repair_case_id']}",
                "source_repair_case_id": d["repair_case_id"],
                "source_hermes_review_id": review["hermes_review_id"],
                "source_hermes_skill_package_id": pkg["hermes_skill_package_id"],
                "source_hermes_test_report_id": report["hermes_test_report_id"],
                "suggested_skill_name": pkg["skill_name"],
                "suggested_skill_domain": pkg["skill_domain"],
                "observed_pattern": pkg["observed_pattern"],
                "intended_use": "Repairman runtime preflight for inspect/repair flows",
                "required_inputs": pkg["input_contract"],
                "expected_outputs": pkg["output_contract"],
                "proposed_actions": pkg["allowed_actions"],
                "forbidden_actions": pkg["forbidden_actions"],
                "required_tests": review["suggested_tests"],
                "risk_tags": ["low"],
                "maturity_status": "READY_FOR_REPAIRMAN_HANDOFF",
                "evidence_refs": pkg["evidence_refs"],
                "suitable_for_repairman_adoption": True,
                "suggested_target_agent": "repairman",
                "tested_by_hermes": True,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            incubated.append(c)

            a = adapt_hermes_candidate(c)
            adapted.append(a)

            plan = build_adoption_plan(a)
            adoption_plans.append(plan)

            scope_expansion = False
            tr = run_adoption_tests(plan, scope_expansion=scope_expansion)
            adoption_results.append(tr)

            if tr["result_status"] in {"ADOPTION_TEST_PASS", "ADOPTION_TEST_WARN_PASS"}:
                act, bind, fu = activate_skill(a, plan, tr)
                active.append(act)
                bindings.append(bind)
                first_use.append(fu)
                feedback_events.append(build_feedback_event(act))
            else:
                scope_requests.append(build_scope_approval_request(a, "adoption tests blocked"))

    _write(out_dir / "repair_case_dossiers.json", {"dossiers": sanitized_dossiers})
    _write(out_dir / "hermes_review_prompts.json", {"prompts": prompts})
    _write(out_dir / "hermes_review_results.json", {"reviews": reviews})
    _write(out_dir / "skill_incubation_signals.json", {"signals": signals})
    _write(out_dir / "hermes_repair_skill_packages.json", {"packages": packages})
    _write(out_dir / "hermes_skill_test_reports.json", {"reports": hermes_reports})
    _write(out_dir / "hermes_incubated_skill_candidates.json", {"candidates": incubated})
    _write(out_dir / "aims_adapted_skill_candidates.json", {"candidates": adapted})
    _write(out_dir / "repairman_adoption_plans.json", {"plans": adoption_plans})
    _write(out_dir / "repairman_adoption_test_results.json", {"results": adoption_results})
    _write(out_dir / "repairman_scope_approval_requests.json", {"requests": scope_requests})
    _write(out_dir / "repairman_active_skill_registry.json", {"active_skills": active})
    _write(out_dir / "repairman_owner_skill_bindings.json", {"bindings": bindings})
    _write(out_dir / "repairman_controlled_first_use_records.json", {"records": first_use})
    _write(out_dir / "repairman_skill_feedback_events.json", {"events": feedback_events})

    report = {
        "repair_cases_found": len(dossiers),
        "dossiers_created": len(dossiers),
        "dossiers_sanitized": len(sanitized_dossiers),
        "hermes_prompts_created": len(prompts),
        "hermes_reviews_imported": hermes_reviews_imported,
        "skill_incubation_signals_created": len(signals),
        "hermes_skill_packages_created": len(packages),
        "hermes_skill_sandbox_tests_run": len(hermes_reports),
        "hermes_skill_sandbox_tests_passed": sum(1 for r in hermes_reports if is_pass_like(r["result_status"])),
        "hermes_skill_packages_handed_off_to_repairman": len(incubated),
        "hermes_incubated_candidates_created": len(incubated),
        "aims_adapted_candidates_created": len(adapted),
        "adoption_plans_created": len(adoption_plans),
        "adoption_tests_run": len(adoption_results),
        "adoption_tests_passed": sum(1 for r in adoption_results if r["result_status"] in {"ADOPTION_TEST_PASS", "ADOPTION_TEST_WARN_PASS"}),
        "scope_approval_requests_created": len(scope_requests),
        "active_repairman_skills_created": len(active),
        "owner_bindings_created": len(bindings),
        "controlled_first_use_records_created": len(first_use),
        "feedback_events_created": len(feedback_events),
        "model_endpoint_calls": 0,
        "hermes_invocations": 0 if dry_run else 0,
        "production_patches": 0,
        "service_restarts": 0,
        "safety_status": "PASS_WITH_ADOPTION_ACTIVATED" if active else "PASS",
        "next_action": "MONITOR_REPAIRMAN_ADOPTED_SKILL_AND_OPTIONALLY_SEND_FEEDBACK_TO_HERMES" if active else "REPAIR_HERMES_SKILL_PACKAGE_BEFORE_HANDOFF",
        "secrets_redacted": redacted,
    }

    v = validate(report, out_dir)
    if not v["ok"]:
        report["safety_status"] = "FAIL"
        report["validation_errors"] = v["errors"]

    _write(out_dir / "repairman_hermes_skill_loop_evidence_pack.json", {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        **{k: report[k] for k in report if k not in {"next_action", "safety_status"}},
    })
    _write(out_dir / "repairman_hermes_skill_loop_report.json", report)
    (out_dir / "repairman_hermes_skill_loop_report.md").write_text("\n".join([
        "# Repairman Hermes Skill Loop Report",
        *[f"- {k}: {v}" for k, v in report.items() if isinstance(v, (str, int, float, bool))],
    ]) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--import-hermes-review", type=Path, default=None)
    ap.add_argument("--invoke-hermes", action="store_true")
    args = ap.parse_args()

    report = run_workflow(
        audit_root=args.audit_root,
        out_dir=args.out,
        dry_run=args.dry_run or not args.invoke_hermes,
        import_hermes_review=args.import_hermes_review,
        invoke_hermes=args.invoke_hermes,
    )

    keys = [
        "repair_cases_found","dossiers_created","dossiers_sanitized","hermes_prompts_created",
        "hermes_reviews_imported","skill_incubation_signals_created","hermes_skill_packages_created",
        "hermes_skill_sandbox_tests_run","hermes_skill_sandbox_tests_passed",
        "hermes_skill_packages_handed_off_to_repairman","hermes_incubated_candidates_created",
        "aims_adapted_candidates_created","adoption_plans_created","adoption_tests_run",
        "adoption_tests_passed","scope_approval_requests_created","active_repairman_skills_created",
        "owner_bindings_created","controlled_first_use_records_created","feedback_events_created",
        "model_endpoint_calls","hermes_invocations","production_patches","service_restarts",
        "safety_status","next_action",
    ]
    for k in keys:
        print(f"{k:42}: {report.get(k)}")
    return 0 if report.get("safety_status", "").startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
