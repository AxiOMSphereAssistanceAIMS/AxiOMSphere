#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

try:
    from .axi_skill_request_aggregator import write_axi_pending_markdown
    from .skill_request_approval_policy import evaluate_request_policy
    from .skill_request_downstream_planner import build_downstream_plan
    from .skill_request_registry import SkillRequestRegistry
    from .skill_request_validator import validate_post_workflow
except ImportError:
    from agents.self_learning.skill_request_approval.axi_skill_request_aggregator import (  # type: ignore
        write_axi_pending_markdown,
    )
    from agents.self_learning.skill_request_approval.skill_request_approval_policy import (  # type: ignore
        evaluate_request_policy,
    )
    from agents.self_learning.skill_request_approval.skill_request_downstream_planner import (  # type: ignore
        build_downstream_plan,
    )
    from agents.self_learning.skill_request_approval.skill_request_registry import (  # type: ignore
        SkillRequestRegistry,
    )
    from agents.self_learning.skill_request_approval.skill_request_validator import (  # type: ignore
        validate_post_workflow,
    )


def _apply_decisions(
    requests: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {r["request_id"]: r for r in requests}
    decision_records: list[dict[str, Any]] = []
    downstream: list[dict[str, Any]] = []

    for d in decisions:
        rid = d.get("request_id")
        req = by_id.get(rid)
        if not req:
            decision_records.append({**d, "status": "IGNORED_UNKNOWN_REQUEST"})
            continue

        if req.get("approval_status") == "BLOCKED_UNSAFE":
            decision_records.append({**d, "status": "IGNORED_BLOCKED_UNSAFE"})
            continue

        decision = d.get("decision")
        decided_by = d.get("decided_by", "user")
        reason = d.get("reason", "")

        if decision == "APPROVE":
            req["approval_status"] = "APPROVED"
            req["approved_by"] = decided_by
            req["approved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            req["rejection_reason"] = None
            plan = build_downstream_plan(req)
            req["downstream_status"] = "READY_FOR_AUTOMATIC_SKILL_CREATION_PLAN"
            req["downstream_plan_id"] = plan["downstream_plan_id"]
            downstream.append(plan)
            decision_records.append({**d, "status": "APPLIED_APPROVED"})
        elif decision == "REJECT":
            req["approval_status"] = "REJECTED"
            req["approved_by"] = decided_by
            req["approved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            req["rejection_reason"] = reason or "rejected"
            req["downstream_status"] = "REJECTED_NO_PLAN"
            req["downstream_plan_id"] = None
            decision_records.append({**d, "status": "APPLIED_REJECTED"})
        else:
            decision_records.append({**d, "status": "IGNORED_INVALID_DECISION"})

    return list(by_id.values()), decision_records + [
        {
            "request_id": r["request_id"],
            "decision": "NONE",
            "decided_by": None,
            "reason": "no explicit decision",
            "status": "PENDING_UNCHANGED",
        }
        for r in by_id.values()
        if r.get("approval_status") == "PENDING_APPROVAL"
    ]


def run_workflow(requests_path: Path, decisions_path: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    registry = SkillRequestRegistry(out_dir)

    requests = registry.load_requests_from_file(requests_path)
    for req in requests:
        req.setdefault("approval_status", "PENDING_APPROVAL")
        req.setdefault("approval_required", True)
        req.setdefault("downstream_status", "WAITING_FOR_APPROVAL")
        req.setdefault("downstream_plan_id", None)
        req.setdefault("approved_by", None)
        req.setdefault("approved_at", None)
        req.setdefault("rejection_reason", None)
        req.setdefault("audit_refs", [])
        pe = evaluate_request_policy(req)
        req["policy_eval"] = pe
        if not pe["allowed_for_approval"]:
            req["approval_status"] = "BLOCKED_UNSAFE"
            req["downstream_status"] = "BLOCKED_UNSAFE"

    decisions_data = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions = list(decisions_data.get("decisions", [])) if isinstance(decisions_data, dict) else []

    requests, decision_records = _apply_decisions(requests, decisions)

    downstream_plans = [build_downstream_plan(r) for r in requests if r.get("approval_status") == "APPROVED"]
    # de-dup by plan id
    uniq = {}
    for p in downstream_plans:
        uniq[p["downstream_plan_id"]] = p
    downstream_plans = list(uniq.values())

    registry.save_pending(requests)
    registry.save_decisions(decision_records)

    axi_md = out_dir / "axi_pending_skill_requests.md"
    write_axi_pending_markdown(requests, axi_md)

    downstream_path = out_dir / "downstream_auto_plan.json"
    downstream_path.write_text(
        json.dumps({"plans": downstream_plans}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    val = validate_post_workflow(requests, downstream_plans)

    approved = sum(1 for r in requests if r.get("approval_status") == "APPROVED")
    rejected = sum(1 for r in requests if r.get("approval_status") == "REJECTED")
    blocked = sum(1 for r in requests if r.get("approval_status") == "BLOCKED_UNSAFE")
    pending = sum(1 for r in requests if r.get("approval_status") == "PENDING_APPROVAL")

    phase19_files = {
        "autonomy_failure_audit_report.json": list((Path(__file__).resolve().parents[3] / "aims_workspace").rglob("autonomy_failure_audit_report.json")),
        "self_learning_gap_by_agent.json": list((Path(__file__).resolve().parents[3] / "aims_workspace").rglob("self_learning_gap_by_agent.json")),
        "revival_action_plan.md": list((Path(__file__).resolve().parents[3] / "aims_workspace").rglob("revival_action_plan.md")),
    }
    phase19_status = (
        "AVAILABLE"
        if all(phase19_files[k] for k in phase19_files)
        else "NOT_AVAILABLE"
    )

    report = {
        "phase": "20",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "phase19_status": phase19_status,
        "requests_loaded": len(requests),
        "pending_requests": pending,
        "approved_requests": approved,
        "rejected_requests": rejected,
        "blocked_unsafe_requests": blocked,
        "downstream_plans_created": len(downstream_plans),
        "axi_aggregator_written": True,
        "runtime_activation_count": val["runtime_activation_count"],
        "training_launch_count": val["training_launch_count"],
        "model_load_unload_count": val["model_load_unload_count"],
        "safety_status": "PASS" if val["ok"] and not val["errors"] else "FAIL",
        "next_action": "IMPLEMENT_AUTOMATIC_SKILL_CREATOR_AFTER_APPROVAL",
        "validator": val,
        "report_paths": {
            "pending": str(registry.pending_path),
            "decisions": str(registry.decisions_path),
            "axi_md": str(axi_md),
            "downstream": str(downstream_path),
        },
    }

    report_json = out_dir / "skill_request_approval_report.json"
    report_md = out_dir / "skill_request_approval_report.md"
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        "# AIMS Phase 20 — Skill Request Approval Gate",
        "",
        f"- requests_loaded: {report['requests_loaded']}",
        f"- pending_requests: {report['pending_requests']}",
        f"- approved_requests: {report['approved_requests']}",
        f"- rejected_requests: {report['rejected_requests']}",
        f"- blocked_unsafe_requests: {report['blocked_unsafe_requests']}",
        f"- downstream_plans_created: {report['downstream_plans_created']}",
        f"- axi_aggregator_written: {report['axi_aggregator_written']}",
        f"- runtime_activation_count: {report['runtime_activation_count']}",
        f"- training_launch_count: {report['training_launch_count']}",
        f"- model_load_unload_count: {report['model_load_unload_count']}",
        f"- safety_status: {report['safety_status']}",
        f"- next_action: {report['next_action']}",
    ]
    report_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    report["report_json"] = str(report_json)
    report["report_md"] = str(report_md)
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="AIMS Phase 20 skill request approval gate workflow")
    p.add_argument("--requests", required=True, type=Path)
    p.add_argument("--decisions", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    r = run_workflow(args.requests, args.decisions, args.out)
    print(f"requests_loaded              : {r['requests_loaded']}")
    print(f"pending_requests             : {r['pending_requests']}")
    print(f"approved_requests            : {r['approved_requests']}")
    print(f"rejected_requests            : {r['rejected_requests']}")
    print(f"blocked_unsafe_requests      : {r['blocked_unsafe_requests']}")
    print(f"downstream_plans_created     : {r['downstream_plans_created']}")
    print(f"axi_aggregator_written       : {r['axi_aggregator_written']}")
    print(f"runtime_activation_count     : {r['runtime_activation_count']}")
    print(f"training_launch_count        : {r['training_launch_count']}")
    print(f"model_load_unload_count      : {r['model_load_unload_count']}")
    print(f"safety_status                : {r['safety_status']}")
    print(f"next_action                  : {r['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
