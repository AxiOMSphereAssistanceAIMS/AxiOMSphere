"""Short-Term Action Plan — extended StrategicPlannedAction schema and registry.

StrategicPlannedAction extends the base PlannedAction with strategic context,
Dubai-timezone scheduling, safety/resource/retry policies, and evidence tracking.

All actions go through Logi's process orchestrator — this module only defines
the schema and the disk-backed registry. Execution is handled by planned_action_runner.py.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEDULED_ACTIONS_ROOT = ROOT / "aims_workspace/strategic_planning/scheduled_actions"

DUBAI_TZ = timezone(timedelta(hours=4))


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dubai_iso(year: int, month: int, day: int, hour: int, minute: int = 0) -> str:
    dt = datetime(year, month, day, hour, minute, tzinfo=DUBAI_TZ)
    return dt.isoformat()


# ── Extended schema ────────────────────────────────────────────────────────────

@dataclass
class RetryPolicy:
    max_attempts: int = 2
    backoff_minutes: int = 30
    on_fail: str = "log_and_skip"      # log_and_skip | alert_argus | escalate_human

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SafetyPolicy:
    no_production_writes: bool = True
    no_model_promotion: bool = True
    no_concurrent_heavy_models: bool = True   # enforces DGX VRAM rule
    no_secrets_in_output: bool = True
    require_poli_approval: bool = False
    abort_if_argus_critical: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResourcePolicy:
    max_vram_gb: int = 10              # 0 = no GPU needed
    allowed_model_slots: list[str] = field(default_factory=list)
    forbidden_concurrent_slots: list[str] = field(default_factory=list)
    max_wall_time_minutes: int = 60
    cpu_only_ok: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TelegramSummaryPolicy:
    enabled: bool = True
    on_pass: bool = True
    on_fail: bool = True
    on_skip: bool = False
    summary_template: str = "{action_id} {status}: {one_line_result}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategicPlannedAction:
    """A fully-specified planned action with strategic context and policies."""

    # Identity
    action_id: str = field(default_factory=lambda: f"PA-{uuid.uuid4().hex[:6].upper()}")
    title: str = ""
    description: str = ""

    # Strategic linkage
    strategic_goal_id: str = ""        # references StrategicObjective.objective_id
    short_term_goal_id: str = ""       # references ShortTermObjective.objective_id

    # Scheduling (Dubai UTC+4 preferred window)
    timezone: str = "Asia/Dubai"       # informational; code always uses DUBAI_TZ constant
    preferred_window_start: str = ""   # ISO-8601 with +04:00 offset
    preferred_window_end: str = ""     # ISO-8601 with +04:00 offset
    schedule_type: str = "one_time"    # one_time | recurring | conditional
    recurrence_cron: str = ""          # only for recurring; cron expression (UTC)

    # Ownership
    owner_agent: str = "logi"
    supporting_agents: list[str] = field(default_factory=list)

    # Execution
    execution_handler: str = "logi_subprocess"   # logi_subprocess | logi_tool | logi_http
    command_or_callable: str = ""                # shell command or tool identifier
    command_args: list[str] = field(default_factory=list)
    working_dir: str = ""                        # defaults to aims-workspace root

    # Evidence
    expected_artifacts: list[str] = field(default_factory=list)
    evidence_dir: str = ""             # relative to aims_workspace/

    # Acceptance
    acceptance_criteria: list[str] = field(default_factory=list)
    validation_plan: str = ""
    rollback_plan: str = ""

    # Policies
    retry_policy: dict = field(default_factory=lambda: RetryPolicy().to_dict())
    safety_policy: dict = field(default_factory=lambda: SafetyPolicy().to_dict())
    resource_policy: dict = field(default_factory=lambda: ResourcePolicy().to_dict())
    telegram_summary_policy: dict = field(default_factory=lambda: TelegramSummaryPolicy().to_dict())

    # Learning
    lessons_learned_plan: str = ""

    # State
    status: str = "PENDING"           # PENDING | RUNNING | PASS | FAIL | SKIP | SIMULATED
    created_by: str = "logi"
    created_at: str = field(default_factory=_now_utc)
    started_at: str = ""
    completed_at: str = ""
    execution_result: dict = field(default_factory=dict)
    attempt_count: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "StrategicPlannedAction":
        known = {f.name for f in StrategicPlannedAction.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return StrategicPlannedAction(**{k: v for k, v in d.items() if k in known})

    def save(self) -> Path:
        SCHEDULED_ACTIONS_ROOT.mkdir(parents=True, exist_ok=True)
        path = SCHEDULED_ACTIONS_ROOT / f"{self.action_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def to_markdown(self) -> str:
        lines = [
            f"## {self.action_id}: {self.title}",
            "",
            f"**Status:** {self.status}  ",
            f"**Owner:** {self.owner_agent}  ",
            f"**Supporting:** {', '.join(self.supporting_agents) or 'none'}  ",
            f"**Window:** {self.preferred_window_start} → {self.preferred_window_end}  ",
            f"**Handler:** {self.execution_handler}  ",
            f"**Command:** `{self.command_or_callable}`  ",
            "",
            f"**Strategic goal:** {self.strategic_goal_id}  ",
            f"**Short-term goal:** {self.short_term_goal_id}  ",
            "",
            "**Acceptance criteria:**",
        ]
        for c in self.acceptance_criteria:
            lines.append(f"  - {c}")
        lines += [
            "",
            f"**Retry policy:** max_attempts={self.retry_policy.get('max_attempts', 2)} "
            f"on_fail={self.retry_policy.get('on_fail', '?')}  ",
            f"**Safety:** no_auto_promote={self.safety_policy.get('no_model_promotion', True)} "
            f"abort_if_argus_critical={self.safety_policy.get('abort_if_argus_critical', True)}  ",
            f"**Max VRAM:** {self.resource_policy.get('max_vram_gb', 0)} GB  ",
            f"**Max wall time:** {self.resource_policy.get('max_wall_time_minutes', 60)} min  ",
            "",
            f"**Lessons learned plan:** {self.lessons_learned_plan}  ",
            f"**Evidence dir:** `{self.evidence_dir}`  ",
        ]
        return "\n".join(lines)


# ── Registry ───────────────────────────────────────────────────────────────────

class StrategicPlannedActionsRegistry:
    """Disk-backed registry of all StrategicPlannedActions."""

    def __init__(self) -> None:
        SCHEDULED_ACTIONS_ROOT.mkdir(parents=True, exist_ok=True)

    def register(self, action: StrategicPlannedAction) -> Path:
        return action.save()

    def load(self, action_id: str) -> StrategicPlannedAction | None:
        path = SCHEDULED_ACTIONS_ROOT / f"{action_id}.json"
        if not path.exists():
            return None
        return StrategicPlannedAction.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def load_all(self) -> list[StrategicPlannedAction]:
        actions = []
        for p in sorted(SCHEDULED_ACTIONS_ROOT.glob("*.json")):
            try:
                actions.append(StrategicPlannedAction.from_dict(
                    json.loads(p.read_text(encoding="utf-8"))
                ))
            except Exception:
                pass
        return actions

    def update_status(self, action_id: str, status: str, result: dict | None = None) -> bool:
        action = self.load(action_id)
        if action is None:
            return False
        action.status = status
        if result is not None:
            action.execution_result = result
        if status in ("START_REQUESTED", "RUNNING") and not action.started_at:
            action.started_at = _now_utc()
        if status in ("PASS", "FAIL", "SKIP", "SIMULATED", "CLOSED_PASS", "CLOSED_FAIL"):
            action.completed_at = _now_utc()
        action.save()
        return True

    def to_markdown(self) -> str:
        actions = self.load_all()
        lines = ["# AIMS Strategic Planned Actions Registry", "", f"**Total:** {len(actions)}", ""]
        for a in actions:
            lines.append(a.to_markdown())
            lines.append("")
        return "\n".join(lines)


# ── Factory — PA-001 through PA-007 ───────────────────────────────────────────

def build_initial_planned_actions() -> list[StrategicPlannedAction]:
    """Build the 7 scheduled activities for the May 14-20 2026 plan."""

    actions = [
        StrategicPlannedAction(
            action_id="PA-001",
            title="Logi Nightly Process Integrity Run",
            description=(
                "Logi runs a full process integrity cycle: plan → dispatch → collect → "
                "compare → correct → report. Covers all active process goals."
            ),
            strategic_goal_id="SO-001",
            short_term_goal_id="STO-001",
            preferred_window_start=_dubai_iso(2026, 5, 14, 22, 30),
            preferred_window_end=_dubai_iso(2026, 5, 15, 2, 0),
            schedule_type="recurring",
            recurrence_cron="30 22 * * *",
            owner_agent="logi",
            supporting_agents=["argus", "traini", "knomi"],
            execution_handler="logi_subprocess",
            command_or_callable="python3 ops/logi/process_integrity_orchestrator.py",
            command_args=["--mode", "nightly"],
            expected_artifacts=[
                "aims_workspace/logi_process_integrity/runs/*/ledger.jsonl",
                "aims_workspace/logi_process_integrity/runs/*/report.md",
            ],
            evidence_dir="logi_process_integrity",
            acceptance_criteria=[
                "ProcessGoal reaches PASS or PARTIAL status",
                "Ledger entries written for every step",
                "Report generated in aims_workspace/logi_process_integrity/runs/",
                "No CRITICAL Argus events during run",
            ],
            validation_plan="Check ledger.jsonl contains iteration_end with decision=PASS|PARTIAL",
            rollback_plan="No rollback needed — read-only diagnostics only",
            retry_policy=RetryPolicy(max_attempts=2, backoff_minutes=60, on_fail="alert_argus").to_dict(),
            safety_policy=SafetyPolicy(no_production_writes=True).to_dict(),
            resource_policy=ResourcePolicy(max_vram_gb=0, cpu_only_ok=True, max_wall_time_minutes=90).to_dict(),
            lessons_learned_plan="Append failure modes and recovery steps to repairman_memory/lessons.jsonl",
        ),

        StrategicPlannedAction(
            action_id="PA-002",
            title="Control Plane Regression Audit",
            description=(
                "Run the autonomy control plane certification to verify all safety gates, "
                "approval chains, and overrides are wired correctly after any code change."
            ),
            strategic_goal_id="SO-001",
            short_term_goal_id="STO-001",
            preferred_window_start=_dubai_iso(2026, 5, 15, 1, 0),
            preferred_window_end=_dubai_iso(2026, 5, 15, 3, 0),
            schedule_type="one_time",
            owner_agent="argus",
            supporting_agents=["logi", "poli"],
            execution_handler="logi_subprocess",
            command_or_callable="python3 ops/evals/autonomy_control_plane_certification.py",
            expected_artifacts=[
                "aims_workspace/control_plane_certifications/",
            ],
            evidence_dir="control_plane_certifications",
            acceptance_criteria=[
                "Certification exits with status PASS or PARTIAL",
                "Result JSON written to aims_workspace/control_plane_certifications/",
                "No CRITICAL gates left unverified",
            ],
            validation_plan="python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get(\"overall_status\") in (\"PASS\",\"PARTIAL\") else 1)'",
            rollback_plan="None — read-only audit",
            retry_policy=RetryPolicy(max_attempts=1, on_fail="log_and_skip").to_dict(),
            safety_policy=SafetyPolicy().to_dict(),
            resource_policy=ResourcePolicy(max_vram_gb=0, max_wall_time_minutes=30).to_dict(),
            lessons_learned_plan="Record any failing gates in repairman_memory/rules_learned.md",
        ),

        StrategicPlannedAction(
            action_id="PA-003",
            title="Knomi RAG Freshness Check",
            description=(
                "Verify Qdrant vector store has fresh embeddings for all documents in "
                "aims_registry.db. Flag stale or missing embeddings for Knomi re-ingestion."
            ),
            strategic_goal_id="SO-002",
            short_term_goal_id="STO-002",
            preferred_window_start=_dubai_iso(2026, 5, 15, 23, 0),
            preferred_window_end=_dubai_iso(2026, 5, 16, 1, 30),
            schedule_type="recurring",
            recurrence_cron="0 23 * * *",
            owner_agent="knomi",
            supporting_agents=["logi", "omi"],
            execution_handler="logi_subprocess",
            command_or_callable="python3 ops/evals/knomi_runtime_skill_smoke.py",
            expected_artifacts=[
                "aims_workspace/strategic_planning/scheduled_actions/evidence/PA-003/",
            ],
            evidence_dir="strategic_planning/scheduled_actions/evidence/PA-003",
            acceptance_criteria=[
                "knomi_runtime_skill_smoke exits 0",
                "Qdrant health check PASS",
                "No documents flagged as missing embeddings (or count logged)",
            ],
            validation_plan="Check exit code of knomi_runtime_skill_smoke.py",
            rollback_plan="None — read-only check",
            retry_policy=RetryPolicy(max_attempts=2, backoff_minutes=20).to_dict(),
            safety_policy=SafetyPolicy().to_dict(),
            resource_policy=ResourcePolicy(max_vram_gb=0, max_wall_time_minutes=15).to_dict(),
            lessons_learned_plan="Log any stale-document counts to Knomi agent memory",
        ),

        StrategicPlannedAction(
            action_id="PA-004",
            title="Traini Dry-Run Readiness Check",
            description=(
                "Run Traini in dry-run mode to verify the full training pipeline is intact: "
                "dataset builder, validator, training script wiring, eval loader, report generator."
            ),
            strategic_goal_id="SO-003",
            short_term_goal_id="STO-003",
            preferred_window_start=_dubai_iso(2026, 5, 16, 0, 30),
            preferred_window_end=_dubai_iso(2026, 5, 16, 2, 0),
            schedule_type="one_time",
            owner_agent="traini",
            supporting_agents=["argus", "logi"],
            execution_handler="logi_subprocess",
            command_or_callable="python3 ops/ft/traini/traini_cycle.py",
            command_args=["--dry-run", "--code", "14"],
            expected_artifacts=[
                "aims_workspace/traini_reports/traini_report_*.json",
                "aims_workspace/traini_reports/traini_report_*.md",
            ],
            evidence_dir="traini_reports",
            acceptance_criteria=[
                "traini_cycle.py exits 0",
                "overall_status is DRY_RUN",
                "Report files written to aims_workspace/traini_reports/",
            ],
            validation_plan="Check exit code and overall_status in cycle result JSON",
            rollback_plan="None — dry-run, no model changes",
            retry_policy=RetryPolicy(max_attempts=1, on_fail="alert_argus").to_dict(),
            safety_policy=SafetyPolicy(no_model_promotion=True).to_dict(),
            resource_policy=ResourcePolicy(
                max_vram_gb=0, cpu_only_ok=True, max_wall_time_minutes=20,
                allowed_model_slots=[], forbidden_concurrent_slots=["slot120"]
            ).to_dict(),
            lessons_learned_plan="Record any dataset gaps in traini cycle report",
        ),

        StrategicPlannedAction(
            action_id="PA-005",
            title="Argus Self-Healing Stability Audit",
            description=(
                "Run the post-restart service stability audit to confirm all self-healing "
                "agents (RepairmanAPI, Watchdog, Architect, Security, QA, Release, Docs) "
                "are reachable and healthy."
            ),
            strategic_goal_id="SO-001",
            short_term_goal_id="STO-001",
            preferred_window_start=_dubai_iso(2026, 5, 15, 22, 30),
            preferred_window_end=_dubai_iso(2026, 5, 15, 23, 0),
            schedule_type="recurring",
            recurrence_cron="30 22 * * *",
            owner_agent="argus",
            supporting_agents=["logi"],
            execution_handler="logi_subprocess",
            command_or_callable="python3 ops/evals/post_restart_service_stability_audit.py",
            expected_artifacts=[
                "aims_workspace/strategic_planning/scheduled_actions/evidence/PA-005/stability_audit.json",
            ],
            evidence_dir="strategic_planning/scheduled_actions/evidence/PA-005",
            acceptance_criteria=[
                "post_restart_service_stability_audit exits 0",
                "All self-healing agents reachable (8010–8016)",
                "No CRITICAL events pending in Argus queue",
            ],
            validation_plan="Check exit code and service_status in audit JSON",
            rollback_plan="If agents unreachable, run: docker compose --profile self-healing up -d",
            retry_policy=RetryPolicy(max_attempts=2, backoff_minutes=5, on_fail="alert_argus").to_dict(),
            safety_policy=SafetyPolicy().to_dict(),
            resource_policy=ResourcePolicy(max_vram_gb=0, max_wall_time_minutes=10).to_dict(),
            lessons_learned_plan="Log any unreachable agents to Argus memory",
        ),

        StrategicPlannedAction(
            action_id="PA-006",
            title="DGX Model Concurrency Policy Smoke",
            description=(
                "Verify DGX model slot concurrency rules are enforced: slot14+slot32 safe, "
                "slot32+slot120 forbidden. Run the dedicated smoke test."
            ),
            strategic_goal_id="SO-001",
            short_term_goal_id="STO-001",
            preferred_window_start=_dubai_iso(2026, 5, 16, 23, 0),
            preferred_window_end=_dubai_iso(2026, 5, 16, 23, 30),
            schedule_type="one_time",
            owner_agent="argus",
            supporting_agents=["logi"],
            execution_handler="logi_subprocess",
            command_or_callable="python3 ops/evals/dgx_model_concurrency_policy_smoke.py",
            command_args=["--run-id", "strategic_planned_actions_v1_PA006"],
            expected_artifacts=[
                "aims_workspace/strategic_planning/scheduled_actions/evidence/PA-006/",
            ],
            evidence_dir="strategic_planning/scheduled_actions/evidence/PA-006",
            acceptance_criteria=[
                "dgx_model_concurrency_policy_smoke exits 0",
                "No forbidden concurrent model slot violations detected",
            ],
            validation_plan="Check exit code of dgx_model_concurrency_policy_smoke.py",
            rollback_plan="None — read-only policy check",
            retry_policy=RetryPolicy(max_attempts=1, on_fail="log_and_skip").to_dict(),
            safety_policy=SafetyPolicy(no_concurrent_heavy_models=True).to_dict(),
            resource_policy=ResourcePolicy(max_vram_gb=0, max_wall_time_minutes=5).to_dict(),
            lessons_learned_plan="Record policy violations in repairman_memory/rules_learned.md",
        ),

        StrategicPlannedAction(
            action_id="PA-007",
            title="Omi OCR and Registry Sync Audit",
            description=(
                "Verify Omi agent can reach aims_registry.db and that the OCR pipeline "
                "sync is current. Run omi_runtime_skill_smoke to confirm readiness."
            ),
            strategic_goal_id="SO-004",
            short_term_goal_id="STO-004",
            preferred_window_start=_dubai_iso(2026, 5, 17, 1, 0),
            preferred_window_end=_dubai_iso(2026, 5, 17, 2, 0),
            schedule_type="one_time",
            owner_agent="omi",
            supporting_agents=["logi", "knomi"],
            execution_handler="logi_subprocess",
            command_or_callable="python3 ops/evals/omi_runtime_skill_smoke.py",
            expected_artifacts=[
                "aims_workspace/strategic_planning/scheduled_actions/evidence/PA-007/",
            ],
            evidence_dir="strategic_planning/scheduled_actions/evidence/PA-007",
            acceptance_criteria=[
                "omi_runtime_skill_smoke exits 0",
                "aims_registry.db reachable with ≥1 document",
                "OCR pipeline module imports cleanly",
            ],
            validation_plan="Check exit code of omi_runtime_skill_smoke.py",
            rollback_plan="None — read-only audit",
            retry_policy=RetryPolicy(max_attempts=2, backoff_minutes=10).to_dict(),
            safety_policy=SafetyPolicy().to_dict(),
            resource_policy=ResourcePolicy(max_vram_gb=0, max_wall_time_minutes=10).to_dict(),
            lessons_learned_plan="Log OCR pipeline gaps to Omi agent memory",
        ),
    ]

    return actions
