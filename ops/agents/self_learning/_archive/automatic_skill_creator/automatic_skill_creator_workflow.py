#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

try:
    from .automatic_skill_pack_builder import build_skill_pack
    from .automatic_candidate_skill_writer import build_candidate_skill
    from .automatic_sandbox_plan_stub_builder import build_sandbox_stub
    from .automatic_skill_evidence_writer import build_evidence_pack
    from .automatic_skill_pack_validator import validate_generated, verify_phase20_acceptance
except ImportError:
    from agents.self_learning.automatic_skill_creator.automatic_skill_pack_builder import build_skill_pack  # type: ignore
    from agents.self_learning.automatic_skill_creator.automatic_candidate_skill_writer import build_candidate_skill  # type: ignore
    from agents.self_learning.automatic_skill_creator.automatic_sandbox_plan_stub_builder import build_sandbox_stub  # type: ignore
    from agents.self_learning.automatic_skill_creator.automatic_skill_evidence_writer import build_evidence_pack  # type: ignore
    from agents.self_learning.automatic_skill_creator.automatic_skill_pack_validator import validate_generated, verify_phase20_acceptance  # type: ignore


def run_workflow(downstream_plan_path: Path, out_dir: Path) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    ok20, errs20 = verify_phase20_acceptance(repo_root)
    if not ok20:
        raise RuntimeError(f"Phase20 acceptance failed: {errs20}")

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(downstream_plan_path.read_text(encoding="utf-8"))
    plans = list(payload.get("plans", [])) if isinstance(payload, dict) else []

    approved_plans = [
        p for p in plans
        if p.get("current_status") == "READY_FOR_AUTOMATIC_SKILL_CREATION_PLAN"
        and "generate_skill_pack" in p.get("automatic_steps", [])
    ]

    skill_packs: list[dict[str, Any]] = []
    candidate_skills: list[dict[str, Any]] = []
    sandbox_stubs: list[dict[str, Any]] = []

    for p in approved_plans:
        sp = build_skill_pack(p)
        cs = build_candidate_skill(sp)
        ss = build_sandbox_stub(sp, cs)
        sp["sandbox_test_stub"] = {"sandbox_plan_stub_id": ss["sandbox_plan_stub_id"], "status": ss["status"]}
        skill_packs.append(sp)
        candidate_skills.append(cs)
        sandbox_stubs.append(ss)

    queue = {
        "queue_id": f"Q-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "queued_items": [
            {
                "request_id": p.get("request_id"),
                "skill_pack_id": sp.get("skill_pack_id"),
                "candidate_skill_id": cs.get("candidate_skill_id"),
                "sandbox_plan_stub_id": ss.get("sandbox_plan_stub_id"),
            }
            for p, sp, cs, ss in zip(approved_plans, skill_packs, candidate_skills, sandbox_stubs)
        ],
        "next_processor": "AIMS_SELF_LEARNING_CYCLE_MANAGER",
        "required_phase": "PHASE_8_SANDBOX_PLAN_TEST",
        "execution_allowed": False,
        "reason": "Queued for next automatic self-learning cycle, but execution remains disabled until sandbox plan/test phase.",
    }

    (out_dir / "generated_skill_packs.json").write_text(json.dumps({"skill_packs": skill_packs}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "generated_candidate_skills.json").write_text(json.dumps({"candidate_skills": candidate_skills}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "generated_sandbox_plan_stubs.json").write_text(json.dumps({"sandbox_plan_stubs": sandbox_stubs}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "next_self_learning_cycle_queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")

    evidence = build_evidence_pack(
        approved_requests=[p.get("request_id", "") for p in approved_plans],
        skill_packs=skill_packs,
        candidate_skills=candidate_skills,
        sandbox_stubs=sandbox_stubs,
        queue_path=str(out_dir / "next_self_learning_cycle_queue.json"),
    )
    (out_dir / "skill_creation_evidence_pack.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    val = validate_generated(skill_packs, candidate_skills, sandbox_stubs, queue)

    report = {
        "phase": "21",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "downstream_plans_loaded": len(plans),
        "approved_plans_consumed": len(approved_plans),
        "skill_packs_generated": len(skill_packs),
        "candidate_skills_generated": len(candidate_skills),
        "sandbox_plan_stubs_generated": len(sandbox_stubs),
        "evidence_pack_written": True,
        "next_cycle_items_queued": len(queue.get("queued_items", [])),
        "runtime_activation_count": val["runtime_activation_count"],
        "training_launch_count": val["training_launch_count"],
        "model_load_unload_count": val["model_load_unload_count"],
        "service_restart_count": val["service_restart_count"],
        "safety_status": "PASS" if val["ok"] else "FAIL",
        "next_action": "CONVERT_SKILL_PACKS_TO_SANDBOX_TEST_PLANS",
        "validator": val,
    }

    report_json = out_dir / "automatic_skill_creator_report.json"
    report_md = out_dir / "automatic_skill_creator_report.md"
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report_md.write_text("\n".join([
        "# AIMS Phase 21 — Automatic Skill Creator",
        "",
        f"- downstream_plans_loaded: {report['downstream_plans_loaded']}",
        f"- approved_plans_consumed: {report['approved_plans_consumed']}",
        f"- skill_packs_generated: {report['skill_packs_generated']}",
        f"- candidate_skills_generated: {report['candidate_skills_generated']}",
        f"- sandbox_plan_stubs_generated: {report['sandbox_plan_stubs_generated']}",
        f"- evidence_pack_written: {report['evidence_pack_written']}",
        f"- next_cycle_items_queued: {report['next_cycle_items_queued']}",
        f"- runtime_activation_count: {report['runtime_activation_count']}",
        f"- training_launch_count: {report['training_launch_count']}",
        f"- model_load_unload_count: {report['model_load_unload_count']}",
        f"- service_restart_count: {report['service_restart_count']}",
        f"- safety_status: {report['safety_status']}",
        f"- next_action: {report['next_action']}",
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="AIMS Phase 21 automatic skill creator workflow")
    ap.add_argument("--downstream-plan", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    r = run_workflow(args.downstream_plan, args.out)
    print(f"downstream_plans_loaded      : {r['downstream_plans_loaded']}")
    print(f"approved_plans_consumed      : {r['approved_plans_consumed']}")
    print(f"skill_packs_generated        : {r['skill_packs_generated']}")
    print(f"candidate_skills_generated   : {r['candidate_skills_generated']}")
    print(f"sandbox_plan_stubs_generated : {r['sandbox_plan_stubs_generated']}")
    print(f"evidence_pack_written        : {r['evidence_pack_written']}")
    print(f"next_cycle_items_queued      : {r['next_cycle_items_queued']}")
    print(f"runtime_activation_count     : {r['runtime_activation_count']}")
    print(f"training_launch_count        : {r['training_launch_count']}")
    print(f"model_load_unload_count      : {r['model_load_unload_count']}")
    print(f"service_restart_count        : {r['service_restart_count']}")
    print(f"safety_status                : {r['safety_status']}")
    print(f"next_action                  : {r['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
