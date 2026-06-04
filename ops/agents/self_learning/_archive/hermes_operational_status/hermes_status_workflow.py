#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, UTC
from pathlib import Path

from agents.self_learning.hermes_operational_status.hermes_status_schema import HermesCurrentStatus, utc_now, new_id
from agents.self_learning.hermes_operational_status.hermes_status_ledger import append_event, tail_events
from agents.self_learning.hermes_operational_status.hermes_status_reporter import write_status, write_matrices
from agents.self_learning.hermes_operational_status.hermes_status_validator import validate
from agents.self_learning.hermes_operational_status.claim_verifier import verify_claims
from agents.self_learning.hermes_operational_status.claim_ledger import write_claim_ledger


DEFAULT_OUT = Path("aims_workspace/hermes/operational_status")
DEFAULT_ASSIST = Path("aims_workspace/runtime_bringup/repairman_hermes_live_stabilization")
DEFAULT_REJECTION_OUT = Path("aims_workspace/hermes/rejection_tracking")


def _load_requests(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(v, list):
            return v
    except Exception:
        pass
    return []


def _load_results(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(v, list):
            return v
    except Exception:
        pass
    return []


def build_status(assist_dir: Path) -> tuple[dict, list[dict]]:
    reqs = _load_requests(assist_dir / "hermes_assistance_requests.json")
    prompts = _load_requests(assist_dir / "hermes_assistance_prompts.json")
    results = _load_results(assist_dir / "hermes_assistance_results.json")
    latest_status_artifact = assist_dir / "latest_status_artifact.json"
    latest_runtime_status = {}
    if latest_status_artifact.exists():
        try:
            latest_runtime_status = json.loads(latest_status_artifact.read_text(encoding="utf-8"))
        except Exception:
            latest_runtime_status = {}

    s = HermesCurrentStatus().to_dict()
    s["source_confidence"] = "ARTIFACT_VERIFIED"
    s["artifact_based"] = True
    s["live_verified"] = False
    missing_evidence: list[str] = []

    if reqs:
        latest = reqs[-1]
        s.update(
            {
                "current_status": "REVIEWING_REPAIRMAN_FAILURE",
                "current_phase": "REPAIRMAN_HERMES_ASSISTANCE",
                "current_task_summary": "reviewing Repairman failure dossier",
                "active_target_agent": latest.get("target_agent", "repairman"),
                "active_repair_case_id": latest.get("repair_case_id"),
                "active_audit_id": latest.get("audit_id"),
                "active_issue_path": latest.get("issue_path"),
                "active_log_path": latest.get("log_path"),
                "active_status_artifact": latest.get("status_artifact_path"),
                "helping_agent": latest.get("target_agent", "repairman"),
                "help_type": "DEBUG_ADVICE",
                "latest_assistance_request_id": latest.get("assistance_id"),
                "latest_hermes_prompt_path": str(assist_dir / "hermes_assistance_prompts.json") if prompts else None,
                "latest_hermes_result_path": str(assist_dir / "hermes_assistance_results.json") if results else None,
                "requests_received": [x.get("assistance_id") for x in reqs if x.get("assistance_id")],
                "work_completed": ["ASSISTANCE_REQUEST_CREATED"],
                "work_in_progress": ["REVIEWING_REPAIRMAN_FAILURE"],
                "pending_actions": ["import Hermes result or run sandbox invocation"],
                "blockers": ["waiting for Hermes result import"] if not results else [],
                "next_action": "RUN_HERMES_REVIEW_OR_IMPORT_RESULT" if not results else "CREATE_SKILL_INCUBATION_SIGNAL_FROM_HERMES_RESULT",
            }
        )
        if prompts:
            s["work_completed"].append("REVIEW_PROMPT_CREATED")
        else:
            missing_evidence.append("hermes_assistance_prompts.json")

    if results:
        latest_r = results[-1]
        s["current_status"] = "GENERATING_ASSISTANCE"
        s["work_completed"].append("ASSISTANCE_RESULT_IMPORTED")
        s["active_skill_stage"] = "REVIEW_SUGGESTED"
        s["active_skill_name"] = latest_r.get("suggested_repairman_skill")
        s["current_task_summary"] = "Hermes result imported; preparing skill incubation signal"
        s["next_action"] = "CREATE_SKILL_INCUBATION_SIGNAL"

    if not reqs:
        s["current_status"] = "IDLE"
        s["next_action"] = "WAIT_FOR_REPAIRMAN_CASE_OR_USER_TASK"
        s["source_confidence"] = "UNVERIFIED"

    # If latest Repairman runtime case completed and no explicit adoption evidence exists,
    # Hermes should report post-repair monitoring state instead of any adoption-like status.
    runtime_status = latest_runtime_status.get("status")
    if runtime_status == "COMPLETED":
        s["current_status"] = "MONITORING_FOR_NEW_CASES"
        s["current_phase"] = "POST_REPAIR_MONITORING"
        s["current_task_summary"] = "latest Repairman case completed; monitoring for new failures"
        s["work_completed"] = list(dict.fromkeys(s.get("work_completed", []) + ["REPAIRMAN_FIX_COMPLETED"]))
        s["work_in_progress"] = ["MONITORING_FOR_NEW_CASES"]
        s["blockers"] = []
        s["next_action"] = "WAIT_FOR_REPAIRMAN_CASE_OR_USER_TASK"

    # Evidence discipline: never claim completion/adoption without explicit artifacts.
    if reqs and not results:
        missing_evidence.append("hermes_assistance_results.json")
    followup = assist_dir / "hermes_assistance_followup_report.json"
    if not followup.exists():
        missing_evidence.append("hermes_assistance_followup_report.json")

    adoption_artifacts = [
        assist_dir / "repairman_active_skill_registry.json",
        assist_dir / "repairman_owner_skill_bindings.json",
        assist_dir / "repairman_adoption_test_results.json",
    ]
    adoption_evidence = any(p.exists() for p in adoption_artifacts)
    if s.get("current_status") in {"MONITORING_ADOPTED_SKILL", "SKILL_ADOPTED_TO_PROJECT"} and not adoption_evidence:
        s["current_status"] = "MONITORING_FOR_NEW_CASES"
        s["work_completed"] = [x for x in s.get("work_completed", []) if x != "SKILL_ADOPTED_TO_PROJECT"]
    if not adoption_evidence:
        missing_evidence.append("adoption_artifacts")

    if missing_evidence:
        s["missing_evidence"] = sorted(set(missing_evidence))
        if s.get("source_confidence") == "ARTIFACT_VERIFIED":
            s["source_confidence"] = "ARTIFACT_PARTIAL"
        if s.get("current_status") == "COMPLETED" and not results:
            s["current_status"] = "UNVERIFIED_ARTIFACT_CLAIM"
            s["blockers"] = sorted(set(s.get("blockers", []) + ["missing evidence for completion claim"]))

    # Rejection tracking summary (REAL-only by default).
    rej_summary = _load_results(DEFAULT_REJECTION_OUT / "rejection_summary.json")
    if isinstance(rej_summary, dict):
        s["real_rejections"] = int(rej_summary.get("real_rejections", 0) or 0)
        s["mock_rejections_ignored"] = int(rej_summary.get("mock_rejections_ignored", 0) or 0)

    s["generated_at"] = utc_now()
    s["last_update_at"] = utc_now()
    return s, reqs


def _parse_iso8601_z(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _cached_confidence(status: dict, stale_after_sec: int = 3600) -> tuple[str, bool, bool]:
    last = _parse_iso8601_z(status.get("last_update_at") or status.get("generated_at"))
    if last is None:
        return "STALE_CACHE", True, False
    age = (datetime.now(UTC) - last).total_seconds()
    if age > stale_after_sec:
        return "STALE_CACHE", True, False
    return "CACHED_ARTIFACT", True, False


def write_event_for_status(out_dir: Path, status: dict) -> None:
    event = {
        "event_id": new_id("hermes_event"),
        "timestamp": utc_now(),
        "event_type": "ASSISTANCE_REQUEST_CREATED" if status.get("latest_assistance_request_id") else "COMPLETED",
        "hermes_agent_id": status.get("hermes_agent_id"),
        "target_agent": status.get("active_target_agent"),
        "repair_case_id": status.get("active_repair_case_id"),
        "audit_id": status.get("active_audit_id"),
        "skill_id": status.get("active_skill_id"),
        "skill_name": status.get("active_skill_name"),
        "skill_stage": status.get("active_skill_stage"),
        "request_id": status.get("latest_assistance_request_id"),
        "input_refs": status.get("input_artifacts", []),
        "output_refs": status.get("output_artifacts", []),
        "status": status.get("current_status"),
        "summary": status.get("current_task_summary"),
        "next_action": status.get("next_action"),
        "blockers": status.get("blockers", []),
        "safety_mode": status.get("project_access_mode"),
    }
    append_event(out_dir, event)


def print_human(status: dict) -> None:
    print("Hermes status:")
    print(f"- source_confidence: {status.get('source_confidence')}")
    print(f"- status: {status.get('current_status')}")
    print(f"- helping: {status.get('helping_agent')}")
    print(f"- audit_id: {status.get('active_audit_id')}")
    print(f"- current task: {status.get('current_task_summary')}")
    print(f"- active skill: {status.get('active_skill_name')}")
    print(f"- skill stage: {status.get('active_skill_stage')}")
    print(f"- latest request: {status.get('latest_assistance_request_id')}")
    print(f"- blockers: {', '.join(status.get('blockers', [])) if status.get('blockers') else '-'}")
    print(f"- next action: {status.get('next_action')}")
    if "supported_claims" in status or "unsupported_claims" in status:
        print(f"- supported_claims: {status.get('supported_claims', 0)}")
        print(f"- unsupported_claims: {status.get('unsupported_claims', 0)}")


def _candidate_claims(status: dict) -> list[dict]:
    claims: list[dict] = []
    claims.append(
        {
            "claim_text": "Repairman task has terminal status",
            "claim_type": "REPAIRMAN_COMPLETION",
            "subject": status.get("active_audit_id") or "",
            "expected_truth_value": True,
            "required_evidence": ["latest_status_artifact.json"],
            "verification_method": "artifact_status_check",
        }
    )
    claims.append(
        {
            "claim_text": "Hermes review exists and can be considered completed",
            "claim_type": "HERMES_REVIEW",
            "subject": status.get("latest_assistance_request_id") or "",
            "expected_truth_value": True,
            "required_evidence": ["hermes_assistance_results.json OR hermes_assistance_followup_report.json"],
            "verification_method": "artifact_presence_check",
        }
    )
    claims.append(
        {
            "claim_text": "Skill adoption is active",
            "claim_type": "SKILL_ADOPTION",
            "subject": status.get("active_skill_name") or "",
            "expected_truth_value": True,
            "required_evidence": ["repairman_active_skill_registry.json OR repairman_owner_skill_bindings.json"],
            "verification_method": "artifact_presence_check",
        }
    )
    claims.append(
        {
            "claim_text": "Container health is live-verified",
            "claim_type": "CONTAINER_HEALTH",
            "subject": "self-healing services",
            "expected_truth_value": True,
            "required_evidence": ["live health endpoint or docker ps live output"],
            "verification_method": "live_runtime_check",
        }
    )
    claims.append(
        {
            "claim_text": "There is at least one REAL Hermes rejection",
            "claim_type": "HERMES_REJECTION",
            "subject": "rejection_tracking",
            "expected_truth_value": True,
            "required_evidence": ["rejection_summary.json with real_rejections > 0"],
            "verification_method": "rejection_summary_filter_check",
        }
    )
    return claims


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--assist-dir", default=str(DEFAULT_ASSIST))
    p.add_argument("--status", action="store_true")
    p.add_argument("--status-json", action="store_true")
    p.add_argument("--cached", action="store_true")
    p.add_argument("--verify-claims", action="store_true")
    p.add_argument("--tail", type=int, default=0)
    args = p.parse_args()

    out_dir = Path(args.out)
    assist_dir = Path(args.assist_dir)
    reqs: list[dict]
    if args.cached:
        current = out_dir / "hermes_current_status.json"
        if current.exists():
            try:
                status = json.loads(current.read_text(encoding="utf-8"))
            except Exception:
                status, reqs = build_status(assist_dir)
            else:
                reqs = _load_requests(out_dir / "hermes_active_requests.json")
        else:
            status, reqs = build_status(assist_dir)
        confidence, artifact_based, live_verified = _cached_confidence(status)
        status["source_confidence"] = confidence
        status["artifact_based"] = artifact_based
        status["live_verified"] = live_verified
    else:
        status, reqs = build_status(assist_dir)
        # LIVE_VERIFIED is reserved/future until explicit --live mode is implemented.
        status["artifact_based"] = True
        status["live_verified"] = False

    if args.verify_claims:
        claims = _candidate_claims(status)
        verified = verify_claims(
            claims,
            out_dir=out_dir,
            assist_dir=assist_dir,
            rejection_dir=DEFAULT_REJECTION_OUT,
        )
        _, _, unsupported_path = write_claim_ledger(out_dir, verified)
        supported = [c for c in verified if c.get("result") == "SUPPORTED"]
        unsupported = [c for c in verified if c.get("result") != "SUPPORTED"]
        status["supported_claims"] = len(supported)
        status["unsupported_claims"] = len(unsupported)
        status["unsupported_claims_path"] = str(unsupported_path)
        missing: list[str] = []
        for c in unsupported:
            missing.extend(c.get("missing_evidence", []))
        if missing:
            status["missing_evidence"] = sorted(set(status.get("missing_evidence", []) + missing))

    write_status(out_dir, status)
    write_matrices(out_dir, status, reqs)
    write_event_for_status(out_dir, status)

    errors = validate(out_dir)
    if errors:
        print("validation_errors:", ",".join(errors))
        return 1

    if args.tail > 0:
        for ev in tail_events(out_dir, args.tail):
            print(json.dumps(ev, ensure_ascii=False))
        return 0

    if args.status_json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    if args.status:
        print_human(status)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
