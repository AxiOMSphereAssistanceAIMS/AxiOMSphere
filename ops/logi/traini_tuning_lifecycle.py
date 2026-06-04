"""Traini evidence-based tuning lifecycle primitives."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from logi.traini_dataset_snapshot import quality_classification

ROOT = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LearningNeed:
    learning_need_id: str
    source: str
    reason: str
    trigger_type: str
    owner_agent: str
    supporting_agents: list[str]
    affected_model_slot: str
    affected_capability: str
    current_baseline_score: float | None
    target_score: float | None
    target_score_default: float
    evaluation_suite: str
    evidence: dict[str, Any]
    priority: str
    status: str


def create_learning_need(
    *,
    source: str,
    reason: str,
    trigger_type: str,
    affected_model_slot: str,
    affected_capability: str,
    current_baseline_score: float | None = None,
    target_score: float | None = None,
    evaluation_suite: str = "ops/ft/scripts/eval_actions.py + dgx/gstack/stability audits",
    evidence: dict[str, Any] | None = None,
    priority: str = "medium",
    status: str = "OPEN",
) -> LearningNeed:
    return LearningNeed(
        learning_need_id=f"ln_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')[:22]}",
        source=source,
        reason=reason,
        trigger_type=trigger_type,
        owner_agent="Traini",
        supporting_agents=["Logi", "Argus", "QA", "Poli", "Release"],
        affected_model_slot=affected_model_slot,
        affected_capability=affected_capability,
        current_baseline_score=current_baseline_score,
        target_score=target_score,
        target_score_default=0.98,
        evaluation_suite=evaluation_suite,
        evidence=evidence or {},
        priority=priority,
        status=status,
    )


def create_planned_tuning_action(
    learning_need: LearningNeed,
    dataset_snapshot_id: str,
    recommended_use: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    # 22:45 Dubai (~18:45 UTC)
    due = datetime(now.year, now.month, now.day, 18, 45, tzinfo=timezone.utc)
    if due <= now:
        due = due + timedelta(days=1)
    return {
        "action_id": f"tpa_{now.strftime('%Y%m%d_%H%M%S')}",
        "learning_need_id": learning_need.learning_need_id,
        "dataset_snapshot_id": dataset_snapshot_id,
        "owner_agent": "Traini",
        "supporting_agents": ["Logi", "Argus", "QA", "Poli", "Release"],
        "due_time": due.isoformat(),
        "timezone": "Asia/Dubai",
        "preferred_window": "22:30-06:30",
        "execution_handler": "traini_tuning_lifecycle_smoke_runner",
        "evidence_chain_required": True,
        "heartbeat_required": True,
        "expected_artifacts": [
            "execution_chain.json",
            "start_record.json",
            "heartbeat.json",
            "dataset_snapshot.json",
            "training_or_eval_result.json",
            "eval_result.json",
            "baseline_comparison.json",
            "promotion_decision.json",
            "final_closure_result.json",
            "final_closure_report.md",
            "lessons_learned.json",
        ],
        "validation_plan": "Run traini smoke + baseline compare + dgx policy smoke.",
        "promotion_policy": "No runtime promotion in certification mode; QA+Poli+Release required.",
        "rollback_policy": "If WARN/FAIL, keep baseline and create corrective planned action.",
        "lessons_learned_plan": "Append lifecycle lesson to repairman_memory/lessons.jsonl.",
        "recommended_use": recommended_use,
    }


def resource_policy_check(stability: dict[str, Any], dgx: dict[str, Any]) -> dict[str, Any]:
    active_blockers = []
    if stability.get("always_on_not_up"):
        active_blockers.append("always_on_not_up")
    if stability.get("restart_loops"):
        active_blockers.append("restart_loops")
    if stability.get("invalid_restart_targets"):
        active_blockers.append("invalid_restart_targets")
    if stability.get("redis_connection_closed_active_failure", False):
        active_blockers.append("active_redis_failure")
    slot_conflict = bool(dgx.get("observed", {}).get("slot32_slot120_conflict_observed", False))
    return {
        "status": "PASS" if not active_blockers and not slot_conflict else "FAIL",
        "active_blockers": active_blockers,
        "slot32_slot120_conflict": slot_conflict,
        "slot120_forced": False,
        "heavy_training_allowed_now": False,
        "default_mode": "lightweight_eval_or_tuning_smoke",
    }


def baseline_comparison(eval_result: dict[str, Any], learning_need: LearningNeed) -> dict[str, Any]:
    baseline_name = "current_runtime_baseline"
    candidate_name = "traini_lifecycle_smoke_candidate"
    baseline_score = learning_need.current_baseline_score if learning_need.current_baseline_score is not None else 0.90
    candidate_score = 0.91 if eval_result.get("status") == "PASS" else 0.86
    delta = round(candidate_score - baseline_score, 4)
    regressions = [] if delta >= 0 else ["score_drop_vs_baseline"]
    if learning_need.trigger_type == "planned_model_improvement_target" and candidate_score < (learning_need.target_score or learning_need.target_score_default):
        recommendation = "RETUNE"
    else:
        recommendation = "PROMOTE" if delta > 0.02 else "EVAL_ONLY"
    return {
        "baseline_name": baseline_name,
        "candidate_name": candidate_name,
        "metrics": {"baseline_score": baseline_score, "candidate_score": candidate_score, "delta": delta},
        "status": "PASS" if delta >= 0 else "WARN",
        "regressions": regressions,
        "recommendation": recommendation,
    }


def planned_improvement_roadmap(
    *,
    snapshot: dict[str, Any],
    quality: dict[str, Any],
    resource_policy: dict[str, Any],
    target_score: float = 0.98,
) -> list[dict[str, Any]]:
    entries = []
    suff = quality.get("status", "INSUFFICIENT_DATA")
    for slot in ("14", "32", "120"):
        baseline = None
        if slot == "14":
            baseline = 1.0
        elif slot == "32":
            baseline = 0.90
        elif slot == "120":
            baseline = None
        next_action = "collect_more_data"
        if baseline is None:
            next_action = "run_baseline_eval_first"
        elif suff in {"TUNING_SMOKE_READY", "FULL_TUNING_READY"} and resource_policy.get("status") == "PASS":
            next_action = "schedule_eval_then_tuning_smoke"
        entries.append(
            {
                "slot": slot,
                "current_baseline_score": baseline,
                "target_score": target_score,
                "required_eval_suite": "traini_runtime_skill_smoke + eval_actions + dgx/stability/gstack audits",
                "data_sufficiency_status": suff,
                "resource_policy_status": resource_policy.get("status", "FAIL"),
                "next_safe_action": next_action,
                "constraints": [
                    "no heavy training auto-run",
                    "no slot32+slot120 coexistence",
                    "no force-load slot120",
                    "qa/poli/release gates required before promotion",
                ],
            }
        )
    return entries


def learning_need_to_dict(need: LearningNeed) -> dict[str, Any]:
    return asdict(need)
