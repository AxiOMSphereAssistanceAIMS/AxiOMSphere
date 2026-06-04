from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logi.nightly_orchestrated_task_factory import build_nightly_self_repair_action
from logi.nightly_schedule_guard import evaluate_nightly_action
from logi.short_term_action_plan import StrategicPlannedActionsRegistry

ROOT = Path(__file__).resolve().parents[2]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NightlySelfRepairOrchestrator:
    """Creates and registers nightly self-repair planned action from Logi goal."""

    def __init__(self) -> None:
        self.registry = StrategicPlannedActionsRegistry()

    def create_goal(self) -> dict[str, Any]:
        return {
            "goal_id": f"goal_nightly_self_repair_{int(datetime.now(timezone.utc).timestamp())}",
            "title": "Nightly Orchestrated Self-Repair Execution Smoke",
            "created_at": now_iso(),
            "coordinating_agent": "logi",
            "owner_agent": "repairman",
            "supporting_agents": ["argus", "qa", "traini", "control_plane", "scheduler", "watchdog", "poli"],
            "objective": "Run nightly self-repair smoke with watchdog and validated retry loop.",
        }

    def create_and_register_action(self, goal: dict[str, Any]) -> dict[str, Any]:
        action = build_nightly_self_repair_action(created_by="logi", active_long_run_context={"source_goal_id": goal["goal_id"]})
        # upsert by id: preserve history if exists
        existing = self.registry.load(action.action_id)
        if existing:
            action.attempt_count = existing.attempt_count
            action.status = existing.status
        self.registry.register(action)

        decision = evaluate_nightly_action(
            action_id=action.action_id,
            preferred_window_start_iso=action.preferred_window_start,
            required_services=["axi-bot", "omi-bot"],
        )

        # apply scheduling decision to action metadata
        if decision.decision in {"QUEUE_AFTER_ACTIVE_RUN", "RESCHEDULE_TO_SAFE_WINDOW"}:
            action.preferred_window_start = decision.proposed_time
            self.registry.register(action)

        return {
            "goal": goal,
            "action": asdict(action),
            "schedule_decision": decision.to_dict(),
            "registered": True,
            "reloadable": self.registry.load(action.action_id) is not None,
        }
