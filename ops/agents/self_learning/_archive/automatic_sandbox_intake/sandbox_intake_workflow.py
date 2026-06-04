#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .sandbox_plan_materializer import materialize_plan
    from .sandbox_intake_queue_writer import build_intake_queue
    from .sandbox_intake_evidence_writer import build_evidence_pack
    from .sandbox_intake_validator import validate_materialized, verify_phase21_acceptance
except ImportError:
    from agents.self_learning.automatic_sandbox_intake.sandbox_plan_materializer import materialize_plan  # type: ignore
    from agents.self_learning.automatic_sandbox_intake.sandbox_intake_queue_writer import build_intake_queue  # type: ignore
    from agents.self_learning.automatic_sandbox_intake.sandbox_intake_evidence_writer import build_evidence_pack  # type: ignore
    from agents.self_learning.automatic_sandbox_intake.sandbox_intake_validator import validate_materialized, verify_phase21_acceptance  # type: ignore


def run_workflow(skill_packs_path: Path, candidates_path: Path, stubs_path: Path, cycle_queue_path: Path, out_dir: Path) -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    ok21, errs21 = verify_phase21_acceptance(repo_root)
    if not ok21:
        raise RuntimeError(f"Phase21 acceptance failed: {errs21}")

    out_dir.mkdir(parents=True, exist_ok=True)

    skill_packs = json.loads(skill_packs_path.read_text(encoding="utf-8")).get("skill_packs", [])
    candidates = json.loads(candidates_path.read_text(encoding="utf-8")).get("candidate_skills", [])
    stubs = json.loads(stubs_path.read_text(encoding="utf-8")).get("sandbox_plan_stubs", [])
    cycle_queue = json.loads(cycle_queue_path.read_text(encoding="utf-8"))

    by_cand = {c["candidate_skill_id"]: c for c in candidates}
    by_stub = {s["candidate_skill_id"]: s for s in stubs}

    plans = []
    rejected = 0

    if cycle_queue.get("execution_allowed") is not False:
        raise RuntimeError("Phase21 queue execution_allowed must be false")

    for sp in skill_packs:
        if sp.get("lifecycle_state") != "CANDIDATE_SKILL":
            rejected += 1
            continue
        if sp.get("status") != "GENERATED_PENDING_SANDBOX_PLAN":
            rejected += 1
            continue
        if sp.get("runtime_activation_allowed") is not False or sp.get("self_approval_allowed") is not False:
            rejected += 1
            continue

        cand = None
        for c in candidates:
            if c.get("source_skill_pack_id") == sp.get("skill_pack_id") and c.get("status") == "READY_FOR_SANDBOX_PLAN_GENERATION":
                cand = c
                break
        if not cand:
            rejected += 1
            continue

        stub = by_stub.get(cand["candidate_skill_id"])
        if not stub:
            rejected += 1
            continue

        plans.append(materialize_plan(sp, cand, stub))

    queue = build_intake_queue(plans)
    evidence = build_evidence_pack(
        source_phase21_artifacts=[
            str(skill_packs_path),
            str(candidates_path),
            str(stubs_path),
            str(cycle_queue_path),
        ],
        skill_packs_loaded=len(skill_packs),
        candidate_skills_loaded=len(candidates),
        stubs_loaded=len(stubs),
        plans_materialized=len(plans),
        plans_rejected=rejected,
    )

    val = validate_materialized(plans, queue)

    (out_dir / "materialized_sandbox_test_plans.json").write_text(json.dumps({"plans": plans}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sandbox_test_intake_queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sandbox_intake_evidence_pack.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    report = {
        "phase": "22",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "skill_packs_loaded": len(skill_packs),
        "candidate_skills_loaded": len(candidates),
        "stubs_loaded": len(stubs),
        "plans_materialized": len(plans),
        "plans_rejected": rejected,
        "intake_queue_items": len(queue.get("queued_plans", [])),
        "sandbox_tests_executed": val["sandbox_tests_executed"],
        "runtime_activation_count": val["runtime_activation_count"],
        "model_endpoint_calls": val["model_endpoint_calls"],
        "training_launch_count": val["training_launch_count"],
        "model_load_unload_count": val["model_load_unload_count"],
        "service_restart_count": val["service_restart_count"],
        "safety_status": "PASS" if val["ok"] else "FAIL",
        "next_action": "AUTOMATIC_SANDBOX_EXECUTION_AFTER_INTAKE",
        "validator": val,
    }

    (out_dir / "sandbox_intake_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sandbox_intake_report.md").write_text("\n".join([
        "# AIMS Phase 22 — Automatic Sandbox Intake",
        "",
        f"- skill_packs_loaded: {report['skill_packs_loaded']}",
        f"- candidate_skills_loaded: {report['candidate_skills_loaded']}",
        f"- stubs_loaded: {report['stubs_loaded']}",
        f"- plans_materialized: {report['plans_materialized']}",
        f"- plans_rejected: {report['plans_rejected']}",
        f"- intake_queue_items: {report['intake_queue_items']}",
        f"- sandbox_tests_executed: {report['sandbox_tests_executed']}",
        f"- runtime_activation_count: {report['runtime_activation_count']}",
        f"- model_endpoint_calls: {report['model_endpoint_calls']}",
        f"- training_launch_count: {report['training_launch_count']}",
        f"- model_load_unload_count: {report['model_load_unload_count']}",
        f"- service_restart_count: {report['service_restart_count']}",
        f"- safety_status: {report['safety_status']}",
        f"- next_action: {report['next_action']}",
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="AIMS Phase 22 automatic sandbox intake workflow")
    ap.add_argument("--skill-packs", required=True, type=Path)
    ap.add_argument("--candidate-skills", required=True, type=Path)
    ap.add_argument("--stubs", required=True, type=Path)
    ap.add_argument("--cycle-queue", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    r = run_workflow(args.skill_packs, args.candidate_skills, args.stubs, args.cycle_queue, args.out)
    print(f"skill_packs_loaded            : {r['skill_packs_loaded']}")
    print(f"candidate_skills_loaded       : {r['candidate_skills_loaded']}")
    print(f"stubs_loaded                  : {r['stubs_loaded']}")
    print(f"plans_materialized            : {r['plans_materialized']}")
    print(f"plans_rejected                : {r['plans_rejected']}")
    print(f"intake_queue_items            : {r['intake_queue_items']}")
    print(f"sandbox_tests_executed        : {r['sandbox_tests_executed']}")
    print(f"runtime_activation_count      : {r['runtime_activation_count']}")
    print(f"model_endpoint_calls          : {r['model_endpoint_calls']}")
    print(f"training_launch_count         : {r['training_launch_count']}")
    print(f"model_load_unload_count       : {r['model_load_unload_count']}")
    print(f"service_restart_count         : {r['service_restart_count']}")
    print(f"safety_status                 : {r['safety_status']}")
    print(f"next_action                   : {r['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
