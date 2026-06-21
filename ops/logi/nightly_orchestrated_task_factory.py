from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - container path differs between bots
    from ops.logi.short_term_action_plan import StrategicPlannedAction
except ModuleNotFoundError:  # pragma: no cover
    from logi.short_term_action_plan import StrategicPlannedAction

DUBAI = timezone(timedelta(hours=4))


def next_night_window_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    dubai = now.astimezone(DUBAI)
    # target 22:30 Asia/Dubai
    target = dubai.replace(hour=22, minute=30, second=0, microsecond=0)
    if dubai >= target:
        target = target + timedelta(days=1)
    return target.astimezone(timezone.utc)


def build_nightly_self_repair_action(*, created_by: str = "logi", active_long_run_context: dict[str, Any] | None = None) -> StrategicPlannedAction:
    start_utc = next_night_window_start()
    end_utc = start_utc + timedelta(minutes=20)
    action = StrategicPlannedAction(
        action_id="PA-NIGHTLY-SELF-REPAIR-SMOKE-V1",
        title="Nightly Self-Repair Execution Smoke",
        owner_agent="repairman",
        supporting_agents=["argus", "qa", "traini", "control_plane", "scheduler", "watchdog", "poli"],
        description=(
            "Nightly orchestrated self-repair smoke with scheduler discovery, "
            "watchdog heartbeat, repair retry loop, and validation closure."
        ),
        strategic_goal_id="SO-NIGHTLY-SELF-REPAIR-V1",
        short_term_goal_id="STO-NIGHTLY-SELF-REPAIR-SMOKE-V1",
        timezone="Asia/Dubai",
        preferred_window_start=start_utc.isoformat(),
        preferred_window_end=end_utc.isoformat(),
        schedule_type="one_time",
        command_or_callable="PYTHONPATH=ops python3 ops/evals/nightly_orchestrated_self_repair_certification.py --mode planned-action-smoke",
        command_args=[],
        execution_handler="logi_subprocess",
        working_dir=str(Path(__file__).resolve().parents[2]),
        expected_artifacts=[
            "aims_workspace/nightly_orchestration/certifications/*/nightly_self_repair_execution_result.json",
            "aims_workspace/nightly_orchestration/certifications/*/heartbeat.json",
            "aims_workspace/nightly_orchestration/certifications/*/final_validation.json",
        ],
        evidence_dir="nightly_orchestration",
        safety_policy={
            "no_destructive_actions": True,
            "no_sudo": True,
            "no_rm_rf": True,
            "no_secrets_exposure": True,
            "no_model_promotion": True,
            "no_heavy_training": True,
            "no_forced_slot120_load": True,
            "no_slot32_slot120_conflict": True,
            "protected_service_restart_requires_policy_or_poli": True,
            "abort_or_queue_if_active_long_running_conflict": True,
        },
        resource_policy={
            "max_vram_gb": 0,
            "cpu_only_ok": True,
            "allowed_model_slots": [],
            "forbidden_concurrent_slots": ["slot120"],
            "max_wall_time_minutes": 20,
        },
        acceptance_criteria=[
            "planned action is reloadable",
            "scheduler discovers action",
            "runner launches safe smoke",
            "watchdog records start/heartbeat/close",
            "controlled failure repaired and retried",
            "retry limit fixture stops at 5",
            "repair training pair written",
            "lesson learned written",
            "argus and qa validation pass",
            "final report written",
            "no active blockers",
            "no secrets exposed",
        ],
        validation_plan="Validate watchdog states, repair retries, and closure report artifacts.",
        rollback_plan="Queue/reschedule when conflicts exist; no destructive actions.",
        retry_policy={
            "max_attempts": 5,
            "backoff_minutes": 5,
            "on_fail": "alert_argus",
        },
        telegram_summary_policy={
            "enabled": True,
            "on_pass": True,
            "on_fail": True,
            "on_skip": True,
            "summary_template": "{action_id} {status}: nightly self-repair smoke",
        },
        lessons_learned_plan="Write repair pairs and lessons to repairman_memory for Traini ingest.",
        created_by=created_by,
        notes="coordinating_agent=logi; supporting_agents=argus,qa,traini,control_plane,scheduler,watchdog,poli",
    )
    if active_long_run_context:
        action.notes += f" | active_long_run_context={active_long_run_context}"
    return action


def action_to_dict(action: StrategicPlannedAction) -> dict[str, Any]:
    return asdict(action)
