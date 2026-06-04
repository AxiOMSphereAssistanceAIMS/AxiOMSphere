"""Self-test plan -> scheduled PlannedActions bridge."""
from __future__ import annotations

from typing import Any

from logi.planned_actions import PlannedAction


def build_scheduled_actions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    scheduled: list[dict[str, Any]] = []
    for idx, run in enumerate(plan.get("scheduled_test_runs", []), start=1):
        action_id = f"ST-{idx:03d}"
        pa = PlannedAction(
            action_id=action_id,
            title=f"Self-test {run['test_id']}",
            goal_id=plan["plan_id"],
            schedule_type="one_time",
            due_time=run["due_time_utc"],
            agent_chain=[run["owner_agent"]] + list(run.get("supporting_agents", [])),
            acceptance_criteria=[run["validation_plan"]],
            validation_plan=run["validation_plan"],
            rollback_or_safe_stop_plan="If failure: create problem record and corrective planned action. No destructive action.",
            status="PENDING",
            created_by="logi_self_test_scheduler",
            notes=(
                f"timezone={run.get('timezone','Asia/Dubai')}; "
                f"execution_handler={run.get('execution_handler','planned_action_runner')}; "
                f"resource_policy={run.get('resource_policy','')}"
            ),
        )
        scheduled.append(
            {
                "action_id": pa.action_id,
                "test_id": run["test_id"],
                "due_time": pa.due_time,
                "timezone": run.get("timezone", "Asia/Dubai"),
                "execution_handler": run.get("execution_handler", "planned_action_runner"),
                "owner_agent": run["owner_agent"],
                "supporting_agents": run.get("supporting_agents", []),
                "validation_plan": run["validation_plan"],
                "expected_artifacts": run.get("expected_artifacts", []),
                "problem_classification_rules": run.get("problem_classification_rules", ""),
                "retry_policy": run.get("retry_policy", {"max_retries": 5}),
                "safety_policy": run.get("safety_policy", ""),
                "resource_policy": run.get("resource_policy", ""),
                "lessons_learned_plan": run.get("lessons_learned_plan", ""),
                "planned_action": pa.to_dict(),
            }
        )
    return scheduled

