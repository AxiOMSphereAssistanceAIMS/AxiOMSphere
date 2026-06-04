"""Strategic Planning for AIMS — multi-day horizon planning.

Manages strategic objectives (weeks/months horizon) and short-term objectives
(days horizon). Produces structured plans that Logi's planned-action system
can execute, evaluate, and compare against goals.

Architecture:
  Logi creates plans → assigns to agents → collects results →
  compares with success criteria → records in ledger → lessons learned.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLANS_ROOT = ROOT / "aims_workspace/strategic_planning/plans"

DUBAI_TZ = timezone(timedelta(hours=4))


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dubai_iso(year: int, month: int, day: int, hour: int, minute: int = 0) -> str:
    dt = datetime(year, month, day, hour, minute, tzinfo=DUBAI_TZ)
    return dt.isoformat()


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class StrategicObjective:
    objective_id: str = field(default_factory=lambda: f"so_{uuid.uuid4().hex[:8]}")
    title: str = ""
    horizon: str = "months"          # "months" | "weeks" | "days"
    description: str = ""
    success_metrics: list[str] = field(default_factory=list)
    owner_agent: str = "logi"
    status: str = "ACTIVE"           # ACTIVE | ACHIEVED | BLOCKED | DEFERRED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShortTermObjective:
    objective_id: str = field(default_factory=lambda: f"sto_{uuid.uuid4().hex[:8]}")
    title: str = ""
    due_by: str = ""                 # ISO date string
    strategic_objective_id: str = ""
    description: str = ""
    success_criteria: list[str] = field(default_factory=list)
    owner_agent: str = "logi"
    status: str = "ACTIVE"           # ACTIVE | ACHIEVED | BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DependencyLink:
    from_id: str = ""    # action_id or objective_id
    to_id: str = ""
    dep_type: str = "before"    # "before" | "after" | "parallel"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskItem:
    risk_id: str = field(default_factory=lambda: f"risk_{uuid.uuid4().hex[:6]}")
    description: str = ""
    probability: str = "medium"   # low | medium | high
    impact: str = "medium"
    mitigation: str = ""
    owner: str = "logi"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategicPlan:
    plan_id: str = field(default_factory=lambda: f"sp_{uuid.uuid4().hex[:10]}")
    title: str = ""
    planning_horizon_start: str = ""
    planning_horizon_end: str = ""
    timezone: str = "Asia/Dubai"
    created_at: str = field(default_factory=_now_utc)
    created_by: str = "logi"
    version: str = "1"
    strategic_objectives: list[StrategicObjective] = field(default_factory=list)
    short_term_objectives: list[ShortTermObjective] = field(default_factory=list)
    scheduled_activity_ids: list[str] = field(default_factory=list)
    dependencies: list[DependencyLink] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    resource_constraints: list[str] = field(default_factory=list)
    agent_ownership_map: dict[str, list[str]] = field(default_factory=dict)
    validation_method: str = ""
    result_evaluation_method: str = ""
    lessons_learned_method: str = ""
    next_planning_review_time: str = ""
    status: str = "ACTIVE"    # ACTIVE | COMPLETED | ARCHIVED

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "StrategicPlan":
        d = dict(d)
        d["strategic_objectives"] = [StrategicObjective(**o) for o in d.get("strategic_objectives", [])]
        d["short_term_objectives"] = [ShortTermObjective(**o) for o in d.get("short_term_objectives", [])]
        d["dependencies"] = [DependencyLink(**dep) for dep in d.get("dependencies", [])]
        d["risks"] = [RiskItem(**r) for r in d.get("risks", [])]
        return StrategicPlan(**d)


# ── Plan manager ──────────────────────────────────────────────────────────────

class StrategicPlanManager:
    """Saves and loads strategic plans from aims_workspace/strategic_planning/plans/."""

    def __init__(self, plans_root: Path = PLANS_ROOT) -> None:
        self.plans_root = plans_root
        self.plans_root.mkdir(parents=True, exist_ok=True)

    def save(self, plan: StrategicPlan) -> tuple[Path, Path]:
        """Persist plan as JSON + Markdown. Returns (json_path, md_path)."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_path = self.plans_root / f"strategic_plan_{ts}.json"
        md_path = self.plans_root / f"strategic_plan_{ts}.md"

        json_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._to_markdown(plan), encoding="utf-8")
        return json_path, md_path

    def load_latest(self) -> StrategicPlan | None:
        candidates = sorted(self.plans_root.glob("strategic_plan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        return StrategicPlan.from_dict(json.loads(candidates[0].read_text(encoding="utf-8")))

    def _to_markdown(self, plan: StrategicPlan) -> str:
        lines = [
            f"# {plan.title}",
            "",
            f"**Plan ID:** `{plan.plan_id}`  ",
            f"**Created:** {plan.created_at}  ",
            f"**Horizon:** {plan.planning_horizon_start} → {plan.planning_horizon_end}  ",
            f"**Timezone:** {plan.timezone}  ",
            f"**Status:** {plan.status}  ",
            f"**Next review:** {plan.next_planning_review_time}  ",
            "",
            "---",
            "",
            "## Strategic Objectives",
            "",
        ]
        for so in plan.strategic_objectives:
            lines += [
                f"### {so.objective_id}: {so.title}",
                f"**Horizon:** {so.horizon}  **Owner:** {so.owner_agent}  **Status:** {so.status}  ",
                f"{so.description}",
                "",
                "**Success metrics:**",
            ]
            for m in so.success_metrics:
                lines.append(f"- {m}")
            lines.append("")

        lines += ["---", "", "## Short-Term Objectives", ""]
        for sto in plan.short_term_objectives:
            lines += [
                f"### {sto.objective_id}: {sto.title}",
                f"**Due by:** {sto.due_by}  **Owner:** {sto.owner_agent}  **Status:** {sto.status}  ",
                f"**Linked to:** `{sto.strategic_objective_id}`  ",
                f"{sto.description}",
                "",
                "**Success criteria:**",
            ]
            for c in sto.success_criteria:
                lines.append(f"- {c}")
            lines.append("")

        lines += ["---", "", "## Scheduled Activity IDs", ""]
        for aid in plan.scheduled_activity_ids:
            lines.append(f"- `{aid}`")
        lines.append("")

        lines += ["---", "", "## Agent Ownership Map", ""]
        for agent, activities in plan.agent_ownership_map.items():
            lines.append(f"**{agent}:** " + ", ".join(f"`{a}`" for a in activities))
        lines.append("")

        lines += ["---", "", "## Risks", ""]
        for risk in plan.risks:
            lines += [
                f"- **{risk.risk_id}** [{risk.probability}/{risk.impact}]: {risk.description}",
                f"  Mitigation: {risk.mitigation}",
            ]
        lines.append("")

        lines += [
            "---",
            "",
            "## Validation Method",
            "",
            plan.validation_method,
            "",
            "## Result Evaluation Method",
            "",
            plan.result_evaluation_method,
            "",
            "## Lessons Learned Method",
            "",
            plan.lessons_learned_method,
            "",
            "---",
            "",
            "> **no_auto_promote = True** — Logi never promotes models or modifies production config; exception actions are blocked_out_of_policy unless separately pre-approved.",
        ]
        return "\n".join(lines)


# ── Factory ───────────────────────────────────────────────────────────────────

def build_aims_strategic_plan_v1() -> StrategicPlan:
    """Create the initial AIMS strategic plan v1 for May 14-20, 2026."""

    # Strategic objectives (multi-week/month horizon)
    strategic_objectives = [
        StrategicObjective(
            objective_id="SO-001",
            title="Fully Autonomous AIMS Document Management",
            horizon="months",
            description=(
                "All document types (maintenance reports, inspection records, ISO 55001 assets) "
                "are processed, classified, and registered without human intervention. "
                "Axi Bot orchestrates end-to-end from Telegram input to aims_registry.db."
            ),
            success_metrics=[
                "10 consecutive nightly DocBench passes without human correction",
                "omi-ft-14b model passes golden_v3 at >= 0.95 for 3 consecutive weeks",
                "Zero unhandled exceptions in Axi Bot for 7 consecutive days",
                "All 7 agents coordinated via Logi with no manual intervention",
            ],
            owner_agent="logi",
            status="ACTIVE",
        ),
        StrategicObjective(
            objective_id="SO-002",
            title="Continuous Self-Learning at Scale",
            horizon="weeks",
            description=(
                "Nightly Traini cycle consistently produces PASS_GATE candidates. "
                "Gold pairs accumulate at >= 20/day. Code-14 and Code-32 models "
                "improve monotonically across eval cycles."
            ),
            success_metrics=[
                "Traini dry-run PASS for 7 consecutive nights",
                "gold_pairs.jsonl >= 200 total records",
                "Code-14 eval >= 0.95 pass rate (up from 0.93 baseline)",
                "One validated PASS_GATE candidate produced and human-reviewed",
            ],
            owner_agent="traini",
            status="ACTIVE",
        ),
        StrategicObjective(
            objective_id="SO-003",
            title="Self-Healing Infrastructure MTTR < 5 min",
            horizon="weeks",
            description=(
                "All recoverable failures in the AIMS self-healing loop are "
                "diagnosed and resolved within 5 minutes. Argus monitors, "
                "RepairmanAPI applies approved repairs, Poli gates all changes."
            ),
            success_metrics=[
                "Long-running harness 24h certification PASS",
                "No critical failure escalates to human for > 5 min",
                "RepairmanAPI lessons.jsonl grows by >= 5 new entries/week",
                "Watchdog health score >= 0.85 consistently",
            ],
            owner_agent="argus",
            status="ACTIVE",
        ),
        StrategicObjective(
            objective_id="SO-004",
            title="Strategic Multi-Day Planning Operational",
            horizon="weeks",
            description=(
                "AIMS can plan, schedule, execute, evaluate, and learn from "
                "multi-day activity plans without Claude Code as operator. "
                "Logi is the universal process orchestrator for all planned actions."
            ),
            success_metrics=[
                "STRATEGIC_PLANNED_ACTIONS_V1_READY certified",
                "5+ scheduled nightly actions run without human trigger",
                "Logi produces lessons_learned for every completed action",
                "Next planning review auto-generated by Logi after each 7-day cycle",
            ],
            owner_agent="logi",
            status="ACTIVE",
        ),
    ]

    # Short-term objectives (1-week horizon, May 14-20, 2026)
    short_term_objectives = [
        ShortTermObjective(
            objective_id="STO-001",
            title="Certify Strategic Planned Actions v1",
            due_by="2026-05-14",
            strategic_objective_id="SO-004",
            description="Complete 7-scenario certification of the strategic planned actions system.",
            success_criteria=[
                "strategic_planned_actions_result.json status=PASS or PARTIAL",
                "5+ planned actions registered and loadable",
                "Scheduler bridge dry-run PASS",
                "One immediate lightweight action executed through AIMS tools",
                "No secrets exposed, no unsafe heavy run scheduled",
            ],
            owner_agent="logi",
            status="ACTIVE",
        ),
        ShortTermObjective(
            objective_id="STO-002",
            title="5-Night Nightly Process Integrity PASS Streak",
            due_by="2026-05-19",
            strategic_objective_id="SO-003",
            description=(
                "Logi Process Integrity Orchestrator runs every night May 14-19 and "
                "produces PASS or documented non-blocking WARN."
            ),
            success_criteria=[
                "5 consecutive Logi PIO runs with status PASS or WARN (no FAIL)",
                "Each run produces ledger.jsonl and certification report",
                "DGX concurrency policy PASS in every run",
                "Lessons captured after each run",
            ],
            owner_agent="logi",
            status="ACTIVE",
        ),
        ShortTermObjective(
            objective_id="STO-003",
            title="Training/Eval Readiness — Code-14 Dataset >= 100",
            due_by="2026-05-18",
            strategic_objective_id="SO-002",
            description=(
                "Traini smoke test passes nightly. gold_pairs.jsonl reaches >= 100 records. "
                "Eval baseline freshness confirmed for golden_v3_action_routing."
            ),
            success_criteria=[
                "Traini smoke-test PASS for 3+ consecutive days",
                "wc -l gold_pairs.jsonl >= 100",
                "ops/ft/logs/eval_baseline_*.json exists and is < 7 days old",
                "build_continuous_dataset dry-run shows >= 14 records for code 14",
            ],
            owner_agent="traini",
            status="ACTIVE",
        ),
        ShortTermObjective(
            objective_id="STO-004",
            title="Knomi/RAG Index Freshness Confirmed",
            due_by="2026-05-16",
            strategic_objective_id="SO-001",
            description=(
                "Knomi agent can answer queries about current model slots, "
                "self-regulation status, and project policy using indexed docs."
            ),
            success_criteria=[
                "Knomi runtime skill smoke PASS or WARN",
                "Query for 'model_slots code 14' returns current model tag",
                "Query for 'Logi process integrity' returns relevant policy",
                "Index freshness < 7 days",
            ],
            owner_agent="knomi",
            status="ACTIVE",
        ),
    ]

    # Dependencies
    dependencies = [
        DependencyLink(from_id="PA-003", to_id="PA-001", dep_type="before",
                       note="RAG freshness check should complete before integrity check uses Knomi"),
        DependencyLink(from_id="PA-001", to_id="PA-002", dep_type="before",
                       note="Process integrity check provides baseline for control plane regression"),
        DependencyLink(from_id="PA-004", to_id="PA-005", dep_type="before",
                       note="Training readiness must be assessed before long-running prep"),
    ]

    # Risks
    risks = [
        RiskItem(
            risk_id="RISK-001",
            description="slot32 (qwen3:32b) and slot120 (nemotron-3-super:120b) loaded simultaneously on DGX",
            probability="low",
            impact="high",
            mitigation="resource_policy on every training action prohibits concurrent load; DGX policy smoke verifies",
            owner="argus",
        ),
        RiskItem(
            risk_id="RISK-002",
            description="Traini dataset < 100 records — training cannot proceed, cycle produces SKIP",
            probability="medium",
            impact="medium",
            mitigation="Action PA-004 checks count daily; if < 100, logs WARN and defers training",
            owner="traini",
        ),
        RiskItem(
            risk_id="RISK-003",
            description="24h/72h long-running certification disrupted by other scheduled actions",
            probability="low",
            impact="high",
            mitigation="All actions check for active 24h/72h run before proceeding; slot to safe window",
            owner="logi",
        ),
        RiskItem(
            risk_id="RISK-004",
            description="Knomi/Qdrant unreachable — RAG freshness check reports GAP",
            probability="medium",
            impact="low",
            mitigation="Action PA-003 records GAP (non-blocking), escalates via Telegram summary",
            owner="knomi",
        ),
    ]

    # Resource constraints
    resource_constraints = [
        "DGX VRAM: max ~100 GB usable; slot14 (10GB) + slot32 (34GB) = safe; slot32 + slot120 FORBIDDEN",
        "Heavy QLoRA training (slot14): ~4-6h GPU; schedule in 22:30-06:30 Dubai window only",
        "Ollama inference during eval: ~10 GB for slot14; coexists with slot32 if needed",
        "Qdrant vector store: local, no external dependency",
        "No secrets written to any file; all keys loaded from .env at runtime",
    ]

    # Agent ownership map
    agent_ownership_map = {
        "logi": ["PA-001", "PA-003", "STO-001", "STO-002"],
        "control_plane": ["PA-002"],
        "knomi": ["PA-003"],
        "traini": ["PA-004", "STO-003"],
        "qa": ["PA-004"],
        "argus": ["PA-005"],
        "omi": ["PA-007"],
    }

    return StrategicPlan(
        plan_id="sp_aims_v1_20260514",
        title="AIMS Strategic Planned Actions v1 — Multi-Day Plan May 14-20, 2026",
        planning_horizon_start=_dubai_iso(2026, 5, 14, 22, 30),
        planning_horizon_end=_dubai_iso(2026, 5, 20, 23, 59),
        timezone="Asia/Dubai",
        created_by="logi_strategic_planner",
        version="1",
        strategic_objectives=strategic_objectives,
        short_term_objectives=short_term_objectives,
        scheduled_activity_ids=["PA-001", "PA-002", "PA-003", "PA-004", "PA-005", "PA-006", "PA-007"],
        dependencies=dependencies,
        risks=risks,
        resource_constraints=resource_constraints,
        agent_ownership_map=agent_ownership_map,
        validation_method=(
            "1. Each planned action writes evidence to evidence_dir after completion.\n"
            "2. Logi compares result against acceptance_criteria (structured check).\n"
            "3. QA/Argus/Traini produce independent evaluation per domain.\n"
            "4. PlannedActionRunner.generate_lessons_learned() captures delta + root cause.\n"
            "5. All results indexed in aims_workspace/strategic_planning/certifications/."
        ),
        result_evaluation_method=(
            "1. Owner agent performs self-evaluation: did outcome match expected_artifacts?\n"
            "2. Domain evaluator (QA for training, Argus for infra, Knomi for RAG) scores result.\n"
            "3. Logi compares agent evaluation with domain evaluation.\n"
            "4. If delta > 20%, corrective action is issued.\n"
            "5. Final gate: acceptance_criteria met? → PASS; partially met? → PARTIAL; none met? → FAIL."
        ),
        lessons_learned_method=(
            "After each action completes (PASS, PARTIAL, or FAIL):\n"
            "1. PlannedActionRunner.generate_lessons_learned() writes lessons_<action_id>.json.\n"
            "2. Logi summarizes root cause, corrective recommendation, next action update.\n"
            "3. Lessons are appended to aims_workspace/repairman_memory/lessons.jsonl.\n"
            "4. Next planning review incorporates lessons into updated plan."
        ),
        next_planning_review_time=_dubai_iso(2026, 5, 21, 9, 0),
        status="ACTIVE",
    )
