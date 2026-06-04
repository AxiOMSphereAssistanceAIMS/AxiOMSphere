"""Process Goal schema for Logi Process Integrity Orchestrator v1.

Defines the structured goal model that Logi uses to track project-level
integrity objectives from PLANNED through PASS/PARTIAL/FAIL.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ProcessStatus = Literal["PLANNED", "RUNNING", "PASS", "PARTIAL", "FAIL"]

ROOT = Path(__file__).resolve().parents[2]
GOALS_ROOT = ROOT / "aims_workspace/logi_process_integrity/runs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SuccessCriterion:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str = ""
    check_fn: str = ""
    required: bool = True
    status: str = "PENDING"   # PENDING | PASS | FAIL | WARN | SKIP | GAP
    result: str = ""
    evidence: dict = field(default_factory=dict)
    # Normalized contract fields (v2)
    owner_agent_or_tool: str = ""
    expected_evidence: str = ""
    observed_evidence: str = ""
    blocking: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CorrectiveAction:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    reason: str = ""
    responsible_agent: str = ""
    action_taken: str = ""
    artifacts_changed: list[str] = field(default_factory=list)
    validation_result: str = ""
    status: str = "PENDING"   # PENDING | PASS | FAIL | SKIPPED | SIMULATED
    created_at: str = field(default_factory=_now)
    completed_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProcessGoal:
    goal_id: str = field(default_factory=lambda: f"pg_{uuid.uuid4().hex[:12]}")
    title: str = ""
    created_at: str = field(default_factory=_now)
    requested_by: str = "logi_orchestrator"
    target_state: str = ""
    success_criteria: list[SuccessCriterion] = field(default_factory=list)
    agent_chain: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    corrective_actions: list[CorrectiveAction] = field(default_factory=list)
    max_iterations: int = 5
    current_iteration: int = 0
    status: ProcessStatus = "PLANNED"
    final_summary: str = ""
    task_ledger_refs: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ProcessGoal":
        d2 = dict(d)
        criteria = [SuccessCriterion(**c) for c in d2.pop("success_criteria", [])]
        actions = [CorrectiveAction(**a) for a in d2.pop("corrective_actions", [])]
        g = ProcessGoal(**d2)
        g.success_criteria = criteria
        g.corrective_actions = actions
        return g

    def save(self, path: Path | None = None) -> Path:
        if path is None:
            GOALS_ROOT.mkdir(parents=True, exist_ok=True)
            path = GOALS_ROOT / f"{self.goal_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def load(goal_id: str) -> "ProcessGoal | None":
        path = GOALS_ROOT / f"{goal_id}.json"
        if not path.exists():
            return None
        return ProcessGoal.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def criteria_summary(self) -> dict:
        total = len(self.success_criteria)
        by_status: dict[str, int] = {}
        for c in self.success_criteria:
            by_status[c.status] = by_status.get(c.status, 0) + 1
        # GAP on a required criterion is treated as a failure (tool unregistered / service down)
        failed_required = [
            c for c in self.success_criteria
            if c.required and c.status in ("FAIL", "GAP")
        ]
        return {
            "total": total,
            "by_status": by_status,
            "failed_required": [c.description for c in failed_required],
            "all_required_pass": len(failed_required) == 0,
        }


def build_default_integrity_goal(requested_by: str = "logi_certification") -> ProcessGoal:
    """Build the default AIMS process integrity goal with standard success criteria."""
    goal = ProcessGoal(
        title="AIMS Process Integrity — Full Check",
        requested_by=requested_by,
        target_state=(
            "All required AIMS agents reachable and capable; "
            "Control Plane operational; "
            "DGX model policy compliant; "
            "Stability audit OK or WARN historical-only; "
            "No active lifecycle blockers; "
            "Cloud LLM route usable; "
            "Final delivery record produced."
        ),
        agent_chain=[
            "argus/watchdog",
            "knomi",
            "doci/docagent",
            "poli",
            "repairman/mainy",
            "control_plane",
        ],
        checks=[
            "gstack_agent_integration_audit",
            "post_restart_service_stability_audit",
            "dgx_model_concurrency_policy_smoke",
            "agent_status_all",
            "docker_ps",
            "cloud_teacher_route_check",
        ],
        max_iterations=5,
    )
    goal.success_criteria = [
        SuccessCriterion(
            description="All required self-healing agents reachable or correctly lifecycle-classified",
            check_fn="agent_status_all",           # corrected: runtime reachability, not code integration
            required=True,
            owner_agent_or_tool="watchdog_agent",
            expected_evidence="≥7/8 agents up",
            blocking=True,
        ),
        SuccessCriterion(
            description="Control Plane smoke / current Autonomy Control Plane v1 check",
            check_fn="control_plane_smoke",
            required=True,
            owner_agent_or_tool="logi",
            expected_evidence="Latest control_plane_v1 certification PASS + ledger write/read smoke PASS",
            blocking=True,
        ),
        SuccessCriterion(
            description="Gstack integration audit PASS",
            check_fn="gstack_agent_integration_audit",
            required=True,
            owner_agent_or_tool="argus",
            expected_evidence="All 14 agents integrated",
            blocking=True,
        ),
        SuccessCriterion(
            description="DGX model concurrency policy PASS — no slot32/slot120 conflict",
            check_fn="dgx_model_concurrency_policy_smoke",
            required=True,
            owner_agent_or_tool="argus",
            expected_evidence="No VRAM slot conflict detected",
            blocking=True,
        ),
        SuccessCriterion(
            description="Stability audit OK or WARN historical-only, no active blockers",
            check_fn="post_restart_service_stability_audit",
            required=True,
            owner_agent_or_tool="argus",
            expected_evidence="PASS or WARN-historical-only",
            blocking=True,
        ),
        SuccessCriterion(
            # Aliased to stability audit result — lifecycle policy is a sub-aspect of stability
            description="No active lifecycle blockers (alert_on_exit=false respected)",
            check_fn="service_lifecycle_audit",
            required=False,                        # non-blocking: covered by stability audit above
            owner_agent_or_tool="argus",
            expected_evidence="alert_on_exit=false respected",
            blocking=False,
        ),
        SuccessCriterion(
            description="Cloud LLM / cloud_teacher route check PASS",
            check_fn="cloud_teacher_route_check",
            required=False,
            owner_agent_or_tool="doci",
            expected_evidence="OmniRoute HTTP 200",
            blocking=False,
        ),
        SuccessCriterion(
            description="Telegram summary or certified delivery record produced",
            check_fn="telegram_delivery",
            required=False,
            owner_agent_or_tool="logi",
            expected_evidence="Delivery event PASS or GAP fallback",
            blocking=False,
        ),
        SuccessCriterion(
            description="All corrective actions validated",
            check_fn="corrective_validation",
            required=False,
            owner_agent_or_tool="logi",
            expected_evidence="All corrective actions PASS or SIMULATED",
            blocking=False,
        ),
        SuccessCriterion(
            description="Final report produced",
            check_fn="final_report",
            required=True,
            owner_agent_or_tool="logi",
            expected_evidence="final_report.json artifact written",
            blocking=True,
        ),
    ]
    return goal
