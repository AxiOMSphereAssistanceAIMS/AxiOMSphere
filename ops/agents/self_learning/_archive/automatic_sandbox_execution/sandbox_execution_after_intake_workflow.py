#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .sandbox_execution_policy import policy_allows_plan, policy_snapshot
    from .synthetic_fixture_builder import build_and_write_fixtures
    from .sandbox_execution_runner import run_deterministic_sandbox
    from .sandbox_certification_intake_queue_writer import build_certification_intake_queue
    from .sandbox_execution_evidence_writer import build_evidence_pack
    from .sandbox_execution_result_validator import verify_phase22_acceptance, validate_fixtures, validate_results
except ImportError:
    from agents.self_learning.automatic_sandbox_execution.sandbox_execution_policy import policy_allows_plan, policy_snapshot  # type: ignore
    from agents.self_learning.automatic_sandbox_execution.synthetic_fixture_builder import build_and_write_fixtures  # type: ignore
    from agents.self_learning.automatic_sandbox_execution.sandbox_execution_runner import run_deterministic_sandbox  # type: ignore
    from agents.self_learning.automatic_sandbox_execution.sandbox_certification_intake_queue_writer import build_certification_intake_queue  # type: ignore
    from agents.self_learning.automatic_sandbox_execution.sandbox_execution_evidence_writer import build_evidence_pack  # type: ignore
    from agents.self_learning.automatic_sandbox_execution.sandbox_execution_result_validator import verify_phase22_acceptance, validate_fixtures, validate_results  # type: ignore


def run_workflow(plans_path: Path, intake_queue_path: Path, out_dir: Path) -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    ok22, errs22 = verify_phase22_acceptance(repo_root)
    if not ok22:
        raise RuntimeError(f"Phase22 acceptance failed: {errs22}")

    out_dir.mkdir(parents=True, exist_ok=True)
    fixtures_root = out_dir / "synthetic_fixtures"
    fixtures_root.mkdir(parents=True, exist_ok=True)

    plans = json.loads(plans_path.read_text(encoding="utf-8")).get("plans", [])
    intake = json.loads(intake_queue_path.read_text(encoding="utf-8"))
    if intake.get("execution_allowed") is not False:
        raise RuntimeError("Phase22 intake queue execution_allowed must be false")

    eligible = [p for p in plans if policy_allows_plan(p)]

    executions = []
    fixture_count = 0
    for p in eligible:
        fx = build_and_write_fixtures(p, fixtures_root)
        fixture_count += len(fx)
        executions.append(run_deterministic_sandbox(p, fx))

    cert_queue = build_certification_intake_queue(executions)
    evidence = build_evidence_pack(
        source_phase22_artifacts=[str(plans_path), str(intake_queue_path)],
        plans_loaded=len(plans),
        fixtures_created=fixture_count,
        executions=executions,
        certification_intake_queue_path=str(out_dir / "certification_intake_queue.json"),
    )

    fx_ok, fx_errs = validate_fixtures(fixtures_root)
    val = validate_results(executions, cert_queue)
    if not fx_ok:
        val["ok"] = False
        val.setdefault("errors", []).extend(fx_errs)

    (out_dir / "sandbox_execution_results.json").write_text(json.dumps({"executions": executions}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "certification_intake_queue.json").write_text(json.dumps(cert_queue, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sandbox_execution_evidence_pack.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    pass_n = sum(1 for e in executions if e.get("result_status") == "SANDBOX_PASS")
    warn_n = sum(1 for e in executions if e.get("result_status") == "SANDBOX_WARN")
    fail_n = sum(1 for e in executions if e.get("result_status") == "SANDBOX_FAIL")
    rej_n = sum(1 for e in executions if e.get("result_status") == "REJECTED_UNSAFE")

    report = {
        "phase": "23",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "plans_loaded": len(plans),
        "eligible_plans": len(eligible),
        "synthetic_fixtures_created": fixture_count,
        "sandbox_executions_run": len(executions),
        "sandbox_pass": pass_n,
        "sandbox_warn": warn_n,
        "sandbox_fail": fail_n,
        "rejected_unsafe": rej_n,
        "certification_queue_items": len(cert_queue.get("queued_items", [])),
        "runtime_activation_count": val["runtime_activation_count"],
        "model_endpoint_calls": val["model_endpoint_calls"],
        "training_launch_count": val["training_launch_count"],
        "model_load_unload_count": val["model_load_unload_count"],
        "service_restart_count": val["service_restart_count"],
        "active_registry_modification_count": val["active_registry_modification_count"],
        "safety_status": "PASS" if val.get("ok") else "FAIL",
        "next_action": "AUTOMATIC_CERTIFICATION_INTAKE_AFTER_SANDBOX_EXECUTION",
        "policy": policy_snapshot(out_dir),
        "validator": val,
    }

    (out_dir / "sandbox_execution_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sandbox_execution_report.md").write_text("\n".join([
        "# AIMS Phase 23 — Automatic Sandbox Execution",
        "",
        f"- plans_loaded: {report['plans_loaded']}",
        f"- eligible_plans: {report['eligible_plans']}",
        f"- synthetic_fixtures_created: {report['synthetic_fixtures_created']}",
        f"- sandbox_executions_run: {report['sandbox_executions_run']}",
        f"- sandbox_pass: {report['sandbox_pass']}",
        f"- sandbox_warn: {report['sandbox_warn']}",
        f"- sandbox_fail: {report['sandbox_fail']}",
        f"- rejected_unsafe: {report['rejected_unsafe']}",
        f"- certification_queue_items: {report['certification_queue_items']}",
        f"- runtime_activation_count: {report['runtime_activation_count']}",
        f"- model_endpoint_calls: {report['model_endpoint_calls']}",
        f"- training_launch_count: {report['training_launch_count']}",
        f"- model_load_unload_count: {report['model_load_unload_count']}",
        f"- service_restart_count: {report['service_restart_count']}",
        f"- active_registry_modification_count: {report['active_registry_modification_count']}",
        f"- safety_status: {report['safety_status']}",
        f"- next_action: {report['next_action']}",
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="AIMS Phase 23 automatic sandbox execution workflow")
    ap.add_argument("--plans", required=True, type=Path)
    ap.add_argument("--intake-queue", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    r = run_workflow(args.plans, args.intake_queue, args.out)
    print(f"plans_loaded                  : {r['plans_loaded']}")
    print(f"eligible_plans               : {r['eligible_plans']}")
    print(f"synthetic_fixtures_created   : {r['synthetic_fixtures_created']}")
    print(f"sandbox_executions_run       : {r['sandbox_executions_run']}")
    print(f"sandbox_pass                 : {r['sandbox_pass']}")
    print(f"sandbox_warn                 : {r['sandbox_warn']}")
    print(f"sandbox_fail                 : {r['sandbox_fail']}")
    print(f"rejected_unsafe              : {r['rejected_unsafe']}")
    print(f"certification_queue_items    : {r['certification_queue_items']}")
    print(f"runtime_activation_count     : {r['runtime_activation_count']}")
    print(f"model_endpoint_calls         : {r['model_endpoint_calls']}")
    print(f"training_launch_count        : {r['training_launch_count']}")
    print(f"model_load_unload_count      : {r['model_load_unload_count']}")
    print(f"service_restart_count        : {r['service_restart_count']}")
    print(f"active_registry_modification_count: {r['active_registry_modification_count']}")
    print(f"safety_status                : {r['safety_status']}")
    print(f"next_action                  : {r['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
