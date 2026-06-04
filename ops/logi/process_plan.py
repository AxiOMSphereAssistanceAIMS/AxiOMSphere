"""Process Plan — structured execution plan for a Logi process integrity goal.

Each plan is composed of PlanSteps dispatched to specific agents/tools.
The plan drives the Dispatch phase of the integrity loop.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PlanStep:
    step_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    agent: str = ""       # responsible agent (owner)
    tool: str = ""        # tool_registry key or audit name
    check_fn: str = ""    # callable name for comparison phase
    payload: dict = field(default_factory=dict)
    required: bool = True
    status: str = "PENDING"  # PENDING | RUNNING | PASS | FAIL | SKIP | WARN
    result: dict = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    owner_agent: str = ""  # explicit owner for delegation audit

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProcessPlan:
    plan_id: str = field(default_factory=lambda: f"pp_{uuid.uuid4().hex[:10]}")
    goal_id: str = ""
    title: str = ""
    created_at: str = field(default_factory=_now)
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "DRAFT"   # DRAFT | ACTIVE | DONE | FAILED | PARTIAL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ProcessPlan":
        d2 = dict(d)
        steps = [PlanStep(**s) for s in d2.pop("steps", [])]
        p = ProcessPlan(**d2)
        p.steps = steps
        return p

    def to_markdown(self) -> str:
        icons = {"PENDING": "○", "RUNNING": "⟳", "PASS": "✓", "FAIL": "✗", "SKIP": "—", "WARN": "⚠"}
        lines = [
            f"# Process Plan: {self.title}",
            f"",
            f"**Plan ID:** `{self.plan_id}`  ",
            f"**Goal ID:** `{self.goal_id}`  ",
            f"**Created:** {self.created_at}  ",
            f"**Status:** {self.status}",
            "",
            "## Steps",
            "",
        ]
        for i, s in enumerate(self.steps, 1):
            icon = icons.get(s.status, "?")
            req = "" if s.required else " _(optional)_"
            lines.append(f"{i}. {icon} **[{s.agent}]** {s.title}{req}")
            lines.append(f"   - Tool: `{s.tool}`  Owner: `{s.owner_agent or s.agent}`")
            if s.error:
                lines.append(f"   - Error: {s.error[:200]}")
            if s.result:
                summary = str(s.result.get("status") or s.result.get("summary") or "")[:120]
                if summary:
                    lines.append(f"   - Result: {summary}")
        return "\n".join(lines)

    def save(self, run_dir: Path) -> Path:
        json_path = run_dir / "process_plan.json"
        json_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        md_path = run_dir / "process_plan.md"
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        return json_path

    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == "PENDING"]

    def failed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == "FAIL"]

    def required_failed(self) -> list[PlanStep]:
        return [s for s in self.steps if s.required and s.status == "FAIL"]


def build_default_integrity_plan(goal_id: str) -> ProcessPlan:
    """Build the default AIMS process integrity check plan with all standard checks."""
    plan = ProcessPlan(
        goal_id=goal_id,
        title="AIMS Process Integrity — Default Check Plan",
    )
    plan.steps = [
        PlanStep(
            title="Agent health poll — self-healing suite (ports 8000–8016)",
            agent="argus/watchdog",
            tool="agent_status_all",
            check_fn="agent_status_all",
            owner_agent="watchdog_agent",
            required=True,
        ),
        PlanStep(
            title="Gstack integration audit — 14-agent integration check",
            agent="argus",
            tool="gstack_agent_integration_audit",
            check_fn="gstack_agent_integration_audit",
            owner_agent="argus",
            required=True,
        ),
        PlanStep(
            title="Service stability audit — lifecycle policy compliance",
            agent="argus",
            tool="post_restart_service_stability_audit",
            check_fn="post_restart_service_stability_audit",
            owner_agent="argus",
            required=True,
        ),
        PlanStep(
            title="DGX model concurrency policy smoke — no slot32/slot120 conflict",
            agent="argus",
            tool="dgx_model_concurrency_policy_smoke",
            check_fn="dgx_model_concurrency_policy_smoke",
            owner_agent="argus",
            required=True,
        ),
        PlanStep(
            title="Control Plane smoke — current Autonomy Control Plane v1",
            agent="logi",
            tool="control_plane_smoke",
            check_fn="control_plane_smoke",
            owner_agent="logi",
            required=True,
        ),
        PlanStep(
            title="Container infrastructure scan",
            agent="argus/watchdog",
            tool="docker_ps",
            check_fn="docker_ps",
            owner_agent="watchdog_agent",
            required=False,
        ),
        PlanStep(
            title="Knowledge base search — project context availability",
            agent="knomi",
            tool="knomi_search",
            check_fn="knomi_search",
            owner_agent="knomi",
            payload={"query": "AIMS process integrity operational status", "top_k": 3},
            required=False,
        ),
        PlanStep(
            title="Cloud LLM route reachability check",
            agent="doci/docagent",
            tool="cloud_teacher_route_check",
            check_fn="cloud_teacher_route_check",
            owner_agent="doci",
            required=False,
        ),
        PlanStep(
            title="Final report production",
            agent="logi",
            tool="write_report",
            check_fn="final_report",
            owner_agent="logi",
            required=True,
        ),
    ]
    return plan
