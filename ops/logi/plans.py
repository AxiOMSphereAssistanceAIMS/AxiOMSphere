"""Plan storage for LogiAgent — JSON files per user."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

PLANS_ROOT = Path("/home/axi_omi_sphere/aims-workspace/aims_workspace/plans")


StepStatus = Literal["pending", "running", "done", "failed"]
PlanStatus = Literal["draft", "active", "done", "failed"]


@dataclass
class Step:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    agent: str = ""          # e.g. "knomi", "doci", "poli", "omi", "traini", "cloud"
    payload: dict = field(default_factory=dict)
    status: StepStatus = "pending"
    result: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: str = ""


@dataclass
class Plan:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: int = 0
    title: str = ""
    goal: str = ""
    status: PlanStatus = "draft"
    steps: list[Step] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Plan":
        steps = [Step(**s) for s in d.pop("steps", [])]
        p = Plan(**d)
        p.steps = steps
        return p

    def touch(self) -> None:
        self.updated_at = datetime.utcnow().isoformat()

    def summary(self) -> str:
        lines = [f"Plan: {self.title} [{self.status}]", f"Goal: {self.goal}"]
        for i, s in enumerate(self.steps, 1):
            icon = {"pending": "○", "running": "⟳", "done": "✓", "failed": "✗"}.get(s.status, "?")
            lines.append(f"  {i}. {icon} [{s.agent}] {s.title}")
        return "\n".join(lines)


def _user_dir(user_id: int) -> Path:
    d = PLANS_ROOT / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_plan(plan: Plan) -> None:
    path = _user_dir(plan.user_id) / f"{plan.id}.json"
    plan.touch()
    path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_plan(user_id: int, plan_id: str) -> Plan | None:
    path = _user_dir(user_id) / f"{plan_id}.json"
    if not path.exists():
        return None
    return Plan.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_plans(user_id: int) -> list[Plan]:
    d = _user_dir(user_id)
    plans = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            plans.append(Plan.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            pass
    return plans


def latest_active_plan(user_id: int) -> Plan | None:
    for plan in list_plans(user_id):
        if plan.status in ("draft", "active"):
            return plan
    return None
