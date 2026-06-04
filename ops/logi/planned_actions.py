"""Planned Actions — future-scheduled AIMS process integrity actions.

PlannedAction records an intent to run an integrity check or corrective task
at a scheduled time. Actions are stored per-run and referenced from ProcessGoal.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLANNED_ACTIONS_ROOT = ROOT / "aims_workspace/logi_process_integrity/planned_actions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PlannedAction:
    action_id: str = field(default_factory=lambda: f"pa_{uuid.uuid4().hex[:10]}")
    title: str = ""
    goal_id: str = ""
    # one_time | recurring | conditional
    schedule_type: str = "one_time"
    due_time: str = ""          # ISO-8601 UTC or empty = ASAP
    agent_chain: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    validation_plan: str = ""
    rollback_or_safe_stop_plan: str = ""
    # PENDING | RUNNING | PASS | FAIL | SKIPPED | SIMULATED
    status: str = "PENDING"
    created_by: str = "logi"
    created_at: str = field(default_factory=_now)
    started_at: str = ""
    completed_at: str = ""
    execution_result: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "PlannedAction":
        return PlannedAction(**d)

    def save(self, run_dir: Path | None = None) -> Path:
        if run_dir is None:
            action_dir = PLANNED_ACTIONS_ROOT / self.action_id
        else:
            action_dir = run_dir / "planned_actions" / self.action_id
        action_dir.mkdir(parents=True, exist_ok=True)
        path = action_dir / "action.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def load(action_id: str, run_dir: Path | None = None) -> "PlannedAction | None":
        if run_dir is None:
            path = PLANNED_ACTIONS_ROOT / action_id / "action.json"
        else:
            path = run_dir / "planned_actions" / action_id / "action.json"
        if not path.exists():
            return None
        return PlannedAction.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def to_markdown(self) -> str:
        lines = [
            f"# Planned Action: {self.title}",
            f"",
            f"**Action ID:** `{self.action_id}`  ",
            f"**Goal ID:** `{self.goal_id}`  ",
            f"**Status:** {self.status}  ",
            f"**Schedule:** {self.schedule_type} — due: {self.due_time or 'ASAP'}  ",
            f"**Created by:** {self.created_by} at {self.created_at}",
            "",
            "## Agent Chain",
            "",
        ]
        for agent in self.agent_chain:
            lines.append(f"- {agent}")
        lines += [
            "",
            "## Acceptance Criteria",
            "",
        ]
        for i, c in enumerate(self.acceptance_criteria, 1):
            lines.append(f"{i}. {c}")
        lines += [
            "",
            f"## Validation Plan",
            "",
            self.validation_plan or "_none specified_",
            "",
            f"## Rollback / Safe-Stop Plan",
            "",
            self.rollback_or_safe_stop_plan or "_none specified_",
        ]
        if self.execution_result:
            lines += ["", "## Execution Result", "", f"```json", json.dumps(self.execution_result, indent=2), "```"]
        return "\n".join(lines)


class PlannedActionsRegistry:
    """In-memory + disk registry of planned actions for one integrity run."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._actions: dict[str, PlannedAction] = {}
        self._index_path = run_dir / "planned_actions_index.json"

    def add(self, action: PlannedAction) -> PlannedAction:
        self._actions[action.action_id] = action
        action.save(self.run_dir)
        self._write_index()
        return action

    def get(self, action_id: str) -> PlannedAction | None:
        return self._actions.get(action_id)

    def all_actions(self) -> list[PlannedAction]:
        return list(self._actions.values())

    def pending(self) -> list[PlannedAction]:
        return [a for a in self._actions.values() if a.status == "PENDING"]

    def update_status(self, action_id: str, status: str, result: dict | None = None) -> None:
        action = self._actions.get(action_id)
        if action is None:
            return
        action.status = status
        if result is not None:
            action.execution_result = result
        if status in ("PASS", "FAIL", "SKIPPED", "SIMULATED"):
            action.completed_at = _now()
        elif status == "RUNNING":
            action.started_at = _now()
        action.save(self.run_dir)
        self._write_index()

    def _write_index(self) -> None:
        index = [
            {
                "action_id": a.action_id,
                "title": a.title,
                "status": a.status,
                "schedule_type": a.schedule_type,
                "due_time": a.due_time,
                "created_at": a.created_at,
            }
            for a in self._actions.values()
        ]
        self._index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for a in self._actions.values():
            by_status[a.status] = by_status.get(a.status, 0) + 1
        return {
            "total": len(self._actions),
            "by_status": by_status,
            "actions": [{"id": a.action_id, "title": a.title, "status": a.status} for a in self._actions.values()],
        }


def build_sample_planned_action(goal_id: str) -> PlannedAction:
    """Create a sample planned action for certification evidence."""
    return PlannedAction(
        title="Scheduled integrity re-check after corrective actions",
        goal_id=goal_id,
        schedule_type="one_time",
        due_time="",
        agent_chain=["argus/watchdog", "knomi", "logi"],
        acceptance_criteria=[
            "All required agents reachable (gstack audit PASS)",
            "DGX model concurrency policy PASS — no slot32/slot120 conflict",
            "Post-corrective stability audit OK or WARN historical-only",
            "Final report produced and stored",
        ],
        validation_plan=(
            "1. Re-run gstack_agent_integration_audit\n"
            "2. Re-run dgx_model_concurrency_policy_smoke\n"
            "3. Re-run post_restart_service_stability_audit\n"
            "4. Verify ledger continuity"
        ),
        rollback_or_safe_stop_plan=(
            "If re-check fails: record PARTIAL, escalate to human operator via Telegram.\n"
            "No destructive actions. No service restarts without PoliAgent approval."
        ),
        created_by="logi",
        notes="Auto-generated by Logi Process Integrity Orchestrator v1",
    )
