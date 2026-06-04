"""Self-test plan generator for AIMS."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dubai_night_slots(start_utc: datetime, days: int = 3) -> list[dict[str, str]]:
    # Dubai is UTC+4 (fixed, no DST).
    slots: list[dict[str, str]] = []
    for d in range(days):
        day = (start_utc + timedelta(days=d)).date()
        # 22:30 Dubai = 18:30 UTC
        t1 = datetime(day.year, day.month, day.day, 18, 30, tzinfo=timezone.utc)
        # 02:30 Dubai next day = 22:30 UTC
        t2 = t1 + timedelta(hours=4)
        # 05:30 Dubai next day = 01:30 UTC (+1 day)
        t3 = t1 + timedelta(hours=7)
        slots.append({"slot": "night_start", "due_time_utc": t1.isoformat(), "timezone": "Asia/Dubai"})
        slots.append({"slot": "night_mid", "due_time_utc": t2.isoformat(), "timezone": "Asia/Dubai"})
        slots.append({"slot": "night_end", "due_time_utc": t3.isoformat(), "timezone": "Asia/Dubai"})
    return slots


def generate_self_test_plan(catalog: list[dict[str, Any]], strategic_goal: str, horizon_days: int = 3) -> dict[str, Any]:
    now = _now_utc()
    plan_id = f"stp_{now.strftime('%Y%m%d_%H%M%S')}"
    horizon_end = now + timedelta(days=horizon_days)
    test_matrix = [
        {
            "test_id": item["test_id"],
            "owner_agent": item["owner_agent"],
            "severity_if_fail": item["severity_if_fail"],
            "can_run_in_nightly": item["can_run_in_nightly"],
            "preferred_window": item["preferred_window"],
        }
        for item in catalog
    ]
    night_slots = _dubai_night_slots(now, days=horizon_days)
    scheduled_runs: list[dict[str, Any]] = []
    nightly_tests = [t for t in catalog if t.get("can_run_in_nightly")]
    # Keep critical repair-loop certification in nightly queue even when catalog grows.
    nightly_tests.sort(
        key=lambda t: (
            0 if t.get("test_id") == "T014_repairman_auto_repair_loop" else 1,
            t.get("severity_if_fail", "WARN"),
            t.get("test_id", ""),
        )
    )
    for idx, t in enumerate(nightly_tests[: max(7, min(12, len(nightly_tests)))]):
        slot = night_slots[idx % len(night_slots)]
        scheduled_runs.append(
            {
                "test_id": t["test_id"],
                "owner_agent": t["owner_agent"],
                "due_time_utc": slot["due_time_utc"],
                "timezone": "Asia/Dubai",
                "execution_handler": "planned_action_runner",
                "supporting_agents": ["logi", "argus", "qa"],
                "validation_plan": t["pass_criteria"],
                "expected_artifacts": t["expected_artifacts"],
                "problem_classification_rules": "Use self_test_problem_manager classification v1.",
                "retry_policy": {"max_retries": 5, "safe_mode_default": True},
                "safety_policy": "No destructive actions, no secret exposure.",
                "resource_policy": t["resource_policy"],
                "lessons_learned_plan": "Append closure lesson to aims_workspace/repairman_memory/lessons.jsonl",
            }
        )
    return {
        "plan_id": plan_id,
        "created_at": now.isoformat(),
        "planning_horizon_start": now.isoformat(),
        "planning_horizon_end": horizon_end.isoformat(),
        "strategic_goal": strategic_goal,
        "test_matrix": test_matrix,
        "scheduled_test_runs": scheduled_runs,
        "dependencies": [
            "logi process integrity orchestrator",
            "autonomy control plane smoke path",
            "argus stability/gstack/dgx audits",
            "planned action runner",
        ],
        "resource_constraints": [
            "No slot32+slot120 concurrency.",
            "No forced slot120 load.",
            "No heavy training auto-run.",
        ],
        "risk_classification": {
            "critical": ["secret exposure", "slot32_slot120_conflict"],
            "blocker": ["required test fail", "active lifecycle blocker"],
            "warn": ["optional test gap", "telegram fallback path"],
            "info": ["historical redis only warning"],
        },
        "expected_evidence": [
            "catalog json",
            "scheduled self tests json",
            "problem records json",
            "corrective actions json",
            "validation results json",
            "evaluation comparison",
        ],
        "problem_handling_rules": "Every WARN/PARTIAL/FAIL/GAP creates problem record with owner and next action.",
        "corrective_action_policy": "Route via Logi planning; unsafe fixes require Poli approval; validation mandatory before closure.",
        "lessons_learned_policy": "Append lesson per closed/deferred issue to repairman_memory/lessons.jsonl.",
        "next_planning_review_time": (now + timedelta(hours=12)).isoformat(),
    }
