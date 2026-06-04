#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .active_skill_event_collector import collect_events
    from .active_skill_performance_assessor import assess_skill
    from .active_skill_improvement_planner import build_improvement_plan
    from .active_skill_feedback_loop import build_feedback_queue
    from .active_skill_monitoring_validator import verify_phase25_acceptance, validate_outputs
except ImportError:
    from agents.self_learning.active_skill_monitoring.active_skill_event_collector import collect_events  # type: ignore
    from agents.self_learning.active_skill_monitoring.active_skill_performance_assessor import assess_skill  # type: ignore
    from agents.self_learning.active_skill_monitoring.active_skill_improvement_planner import build_improvement_plan  # type: ignore
    from agents.self_learning.active_skill_monitoring.active_skill_feedback_loop import build_feedback_queue  # type: ignore
    from agents.self_learning.active_skill_monitoring.active_skill_monitoring_validator import verify_phase25_acceptance, validate_outputs  # type: ignore


def _load_json(path: Path, key: str | None = None):
    data = json.loads(path.read_text(encoding="utf-8"))
    if key is None:
        return data
    return data.get(key, []) if isinstance(data, dict) else []


def run_workflow(activation_dir: Path, out_dir: Path) -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    ok25, errs25 = verify_phase25_acceptance(repo_root)
    if not ok25:
        raise RuntimeError(f"Phase25 acceptance failed: {errs25}")

    out_dir.mkdir(parents=True, exist_ok=True)

    active_entries = _load_json(activation_dir / "active_skill_registry.json", "active_skill_registry_entries")
    bindings = _load_json(activation_dir / "owner_agent_skill_bindings.json", "owner_agent_bindings")
    first_use_records = _load_json(activation_dir / "controlled_first_use_record.json", "controlled_first_use_records")
    rollback = _load_json(activation_dir / "rollback_manifest.json", "rollback_entries")
    _ = _load_json(activation_dir / "activation_evidence_pack.json")

    monitored = [
        e for e in active_entries
        if e.get("lifecycle_state") == "ACTIVE_RUNTIME_SKILL"
        and e.get("activation_status") == "ACTIVE_WITHIN_APPROVED_SCOPE"
        and e.get("runtime_use_mode") in {"CONTROLLED_SCOPE_ONLY", "ADVISORY_ONLY", "SHADOW_AND_CONTROLLED_USE"}
        and e.get("monitoring_required") is True
    ]

    events = []
    assessments = []
    plans = []

    for e in monitored:
        fur = next((f for f in first_use_records if f.get("active_skill_id") == e.get("active_skill_id")), None)
        if not fur:
            continue
        evs = collect_events(e, fur)
        events.extend(evs)
        ass = assess_skill(e, evs)
        assessments.append(ass)
        plans.append(build_improvement_plan(e, ass))

    queue = build_feedback_queue(plans)

    val = validate_outputs(events, assessments, plans, queue)

    (out_dir / "active_skill_monitoring_events.json").write_text(json.dumps({"events": events}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "active_skill_performance_assessment.json").write_text(json.dumps({"assessments": assessments}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "skill_improvement_plan.json").write_text(json.dumps({"improvement_plans": plans}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "next_self_learning_feedback_queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")

    evidence = {
        "evidence_pack_id": f"FSM-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "active_skills_loaded": len(active_entries),
        "events_created": len(events),
        "assessments_created": len(assessments),
        "improvement_plans_created": len(plans),
        "feedback_queue_items": len(queue.get("queued_items", [])),
        "safety_counters": {
            "production_skill_execution_count": 0,
            "service_restart_count": 0,
            "model_load_unload_count": 0,
            "training_launch_count": 0,
            "secrets_access_count": 0,
            "raw_claude_mem_access_count": 0,
        },
    }
    (out_dir / "skill_feedback_evidence_pack.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    healthy = sum(1 for a in assessments if a.get("assessment_status") in {"HEALTHY", "HEALTHY_WITH_IMPROVEMENT_OPPORTUNITY"})
    improvement_needed = sum(1 for a in assessments if a.get("improvement_needed"))
    new_approval_required = sum(1 for a in assessments if a.get("new_approval_required"))
    rollback_recommended = sum(1 for a in assessments if a.get("rollback_recommended"))

    report = {
        "active_skills_loaded": len(active_entries),
        "bindings_loaded": len(bindings),
        "first_use_records_loaded": len(first_use_records),
        "monitoring_events_created": len(events),
        "assessments_created": len(assessments),
        "healthy_skills": healthy,
        "improvement_needed": improvement_needed,
        "new_approval_required": new_approval_required,
        "rollback_recommended": rollback_recommended,
        "feedback_queue_items": len(queue.get("queued_items", [])),
        "automatic_within_scope_items": int(queue.get("automatic_within_scope_items", 0)),
        "manual_approval_items": int(queue.get("manual_approval_items", 0)),
        "safety_status": "PASS" if val.get("ok") else "FAIL",
        "next_action": "CONTINUE_SELF_LEARNING_FEEDBACK_LOOP",
    }

    if not val.get("ok"):
        report["validator_errors"] = val.get("errors", [])

    (out_dir / "active_skill_monitoring_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "active_skill_monitoring_report.md").write_text("\n".join([
        "# AIMS Phase 26 — Active Skill Monitoring",
        "",
        *[f"- {k}: {v}" for k, v in report.items() if k != "validator_errors"],
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="AIMS Phase 26 active skill monitoring workflow")
    ap.add_argument("--activation-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    r = run_workflow(args.activation_dir, args.out)
    for k in [
        "active_skills_loaded","bindings_loaded","first_use_records_loaded","monitoring_events_created",
        "assessments_created","healthy_skills","improvement_needed","new_approval_required",
        "rollback_recommended","feedback_queue_items","automatic_within_scope_items","manual_approval_items",
        "safety_status","next_action"
    ]:
        print(f"{k:32}: {r[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
