"""Logi — Model Improvement Orchestrator.

Logi's orchestration logic for the continuous improvement loop:
1. Create model improvement goal
2. Load certified readiness facts
3. Assign tasks to agents (Traini / QA / Argus / Control Plane / Scheduler)
4. Request and collect Traini blocks
5. Compare results against target 0.98
6. Decide next safe action
7. Create next_cycle_input
8. Start cycle 2 using cycle 1 output
9. Schedule or register future continuation
10. Write lessons learned
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
CYCLES_DIR = ROOT / "aims_workspace" / "model_improvement_loop" / "cycles"
LOOP_DIR = ROOT / "aims_workspace" / "model_improvement_loop"
FT_LOGS = ROOT / "ops" / "ft" / "logs"
AXI_FT_LOG = ROOT / "aims_workspace" / "axi_ft_log"
REPAIRMAN_MEM = ROOT / "aims_workspace" / "repairman_memory"
LESSONS_FILE = REPAIRMAN_MEM / "lessons.jsonl"
DUBAI_TZ = timezone(timedelta(hours=4))


# ── Goal model ────────────────────────────────────────────────────────────────

@dataclass
class ModelImprovementGoal:
    goal_id: str
    created_by: str                # "logi"
    target_slots: list[str]        # ["slot14", "slot32"]
    target_score: float            # 0.98
    current_baselines: dict[str, Optional[float]]
    gaps: dict[str, Optional[float]]
    improvement_approach: str
    owner_agents: dict[str, str]   # slot → primary agent
    supporting_agents: list[str]
    safety_policy: dict[str, Any]
    data_generation_prerequisites: list[str]
    forbidden_actions: list[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "ACTIVE"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Agent task model ──────────────────────────────────────────────────────────

@dataclass
class AgentTask:
    task_id: str
    goal_id: str
    cycle_id: str
    assigned_to: str           # "traini" / "qa" / "argus" / "logi"
    task_type: str             # DATA_COLLECTION / EVAL / VALIDATE / MONITOR / SCHEDULE
    slot_id: str
    description: str
    required_output: str
    depends_on: list[str]      # other task_ids
    status: str                # ASSIGNED / IN_PROGRESS / COMPLETED / BLOCKED / FAILED
    result_summary: Optional[str] = None
    result_artifact: Optional[str] = None
    assigned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Orchestrator ──────────────────────────────────────────────────────────────

class ModelImprovementOrchestrator:
    """Logi acts as the orchestrator for continuous model improvement."""

    TARGET_SCORE = 0.98
    CERTIFIED_BASELINES = {
        "slot14": 0.93,
        "slot32": 0.80,
        "slot120": 0.76,
        "cloud_teacher": None,
    }
    CERTIFIED_READINESS = {
        "slot14": "DATA_COLLECTION",
        "slot32": "DATA_COLLECTION",
        "slot120": "BLOCKED",
        "cloud_teacher": "BLOCKED",
    }

    def __init__(self, output_dir: Path) -> None:
        self._dir = output_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        CYCLES_DIR.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, AgentTask] = {}
        self._continuation_actions: list[dict[str, Any]] = []

    # ── Goal creation ──────────────────────────────────────────────────────────

    def create_goal(self) -> ModelImprovementGoal:
        goal_id = f"goal_model_improvement_{uuid.uuid4().hex[:8]}"
        baselines = dict(self.CERTIFIED_BASELINES)
        gaps = {
            slot_id: round(self.TARGET_SCORE - b, 4) if b is not None else None
            for slot_id, b in baselines.items()
        }
        goal = ModelImprovementGoal(
            goal_id=goal_id,
            created_by="logi",
            target_slots=["slot14", "slot32"],
            target_score=self.TARGET_SCORE,
            current_baselines=baselines,
            gaps=gaps,
            improvement_approach=(
                "Evidence-chain iterative improvement: "
                "data collection → eval → tuning smoke → full tuning → eval → promotion. "
                "Each phase is gated by QA, Argus resource policy, Poli approval, and Release gate."
            ),
            owner_agents={
                "slot14": "traini",
                "slot32": "traini",
                "slot120": "argus",  # monitoring only; BLOCKED for tuning
                "cloud_teacher": "logi",  # external; no local tuning
            },
            supporting_agents=["qa", "argus", "poli", "release", "knomi"],
            safety_policy={
                "no_heavy_training": True,
                "no_promotion_without_gates": True,
                "no_slot120_force_load": True,
                "no_slot32_slot120_concurrent": True,
                "no_claim_0_98_without_eval_evidence": True,
                "all_data_is_candidate_until_qa_accepts": True,
                "promotion_requires": ["qa_gate", "poli_approval", "release_gate"],
            },
            data_generation_prerequisites=[
                "slot_function_inventory.json",
                "agent_function_inventory.json",
                "missing_tuning_topics.md",
                "updated_slot14_generation_plan.md",
                "updated_slot32_generation_plan.md",
            ],
            forbidden_actions=[
                "heavy_training",
                "full_tuning_execution",
                "model_promotion",
                "force_load_slot120",
                "slot32_slot120_concurrent_load",
                "runtime_model_registry_swap",
                "claim_0_98_achieved_without_eval",
            ],
        )
        path = self._dir / "model_improvement_goal.json"
        path.write_text(json.dumps(goal.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return goal

    # ── Readiness facts ────────────────────────────────────────────────────────

    def load_certified_readiness(self) -> dict[str, Any]:
        """Load certified model readiness facts from actual eval logs."""
        facts: dict[str, Any] = {
            "source": "model_tuning_readiness_chain_v1 (11/11 PASS)",
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "slots": {},
        }

        for slot_id, baseline in self.CERTIFIED_BASELINES.items():
            gap = round(self.TARGET_SCORE - baseline, 4) if baseline is not None else None
            facts["slots"][slot_id] = {
                "baseline_score": baseline,
                "target_score": self.TARGET_SCORE,
                "gap": gap,
                "readiness_mode": self.CERTIFIED_READINESS[slot_id],
                "source_certified": True,
                "achieved_0_98_currently": False,
            }

        # Cross-check against actual eval log files
        slot14_eval = FT_LOGS / "eval_14_v18_golden_v3.json"
        if not slot14_eval.exists():
            slot14_eval = FT_LOGS / "eval_14_v16_golden_v3.json"
        if slot14_eval.exists():
            try:
                d = json.loads(slot14_eval.read_text(encoding="utf-8"))
                actual = d.get("pass_rate")
                if actual is not None:
                    facts["slots"]["slot14"]["evidence_file"] = str(slot14_eval.relative_to(ROOT))
                    facts["slots"]["slot14"]["evidence_score"] = float(actual)
            except Exception:
                pass

        for sfile, sid in [
            ("eval_32b_judge405b.json", "slot32"),
            ("eval_120b_judge405b.json", "slot120"),
        ]:
            p = FT_LOGS / sfile
            if p.exists():
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    actual = d.get("pass_rate")
                    if actual is not None:
                        facts["slots"][sid]["evidence_file"] = str(p.relative_to(ROOT))
                        facts["slots"][sid]["evidence_score"] = float(actual)
                except Exception:
                    pass

        return facts

    # ── Task assignment ────────────────────────────────────────────────────────

    def assign_tasks(
        self,
        goal: ModelImprovementGoal,
        cycle_id: str,
    ) -> list[AgentTask]:
        tasks = []

        # Traini: data collection for slot14
        t1 = AgentTask(
            task_id=f"task_{cycle_id[:12]}_traini_slot14_dc",
            goal_id=goal.goal_id,
            cycle_id=cycle_id,
            assigned_to="traini",
            task_type="DATA_COLLECTION",
            slot_id="slot14",
            description=(
                "Prepare DATA_COLLECTION block for slot14: "
                "generate or collect ≥50 gold pairs (chat/document) and ≥50 DPO pairs. "
                "Focus: chat, document work, Telegram summaries, procedure review, "
                "anonymization, document comparison, template filling, routing to Omi/Doci/Knomi."
            ),
            required_output="traini_block_result_cycle_1.json with produced_artifacts",
            depends_on=[],
            status="ASSIGNED",
        )
        tasks.append(t1)
        self._tasks[t1.task_id] = t1

        # Traini: data collection for slot32
        t2 = AgentTask(
            task_id=f"task_{cycle_id[:12]}_traini_slot32_dc",
            goal_id=goal.goal_id,
            cycle_id=cycle_id,
            assigned_to="traini",
            task_type="DATA_COLLECTION",
            slot_id="slot32",
            description=(
                "Prepare DATA_COLLECTION block for slot32: "
                "generate coding/reasoning/eval plan dataset. "
                "Focus: coding, bash/python repair, certification scripts, "
                "evidence-chain planning, JSON interpretation, corrective action planning."
            ),
            required_output="traini_block_result_cycle_1.json (slot32) with produced_artifacts",
            depends_on=[],
            status="ASSIGNED",
        )
        tasks.append(t2)
        self._tasks[t2.task_id] = t2

        # QA: validate Traini blocks
        t3 = AgentTask(
            task_id=f"task_{cycle_id[:12]}_qa_validate",
            goal_id=goal.goal_id,
            cycle_id=cycle_id,
            assigned_to="qa",
            task_type="VALIDATE",
            slot_id="slot14",
            description="QA validation of Traini blocks for slot14 and slot32.",
            required_output="traini_block_validation_cycle_1.json",
            depends_on=[t1.task_id, t2.task_id],
            status="ASSIGNED",
        )
        tasks.append(t3)
        self._tasks[t3.task_id] = t3

        # Argus: resource policy check
        t4 = AgentTask(
            task_id=f"task_{cycle_id[:12]}_argus_policy",
            goal_id=goal.goal_id,
            cycle_id=cycle_id,
            assigned_to="argus",
            task_type="MONITOR",
            slot_id="slot32",
            description=(
                "Resource policy check: confirm slot32/slot120 not concurrent, "
                "VRAM budget safe, no force-load violations."
            ),
            required_output="resource_policy_check.json",
            depends_on=[],
            status="ASSIGNED",
        )
        tasks.append(t4)
        self._tasks[t4.task_id] = t4

        # Logi: schedule next cycle
        t5 = AgentTask(
            task_id=f"task_{cycle_id[:12]}_logi_schedule",
            goal_id=goal.goal_id,
            cycle_id=cycle_id,
            assigned_to="logi",
            task_type="SCHEDULE",
            slot_id="slot14",
            description="Register planned continuation actions for cycle 2 and future cycles.",
            required_output="planned_continuation_actions.json",
            depends_on=[t3.task_id, t4.task_id],
            status="ASSIGNED",
        )
        tasks.append(t5)
        self._tasks[t5.task_id] = t5

        # Write task assignments
        task_list = [t.to_dict() for t in tasks]
        path = self._dir / "agent_task_assignments.json"
        path.write_text(json.dumps({
            "cycle_id": cycle_id,
            "goal_id": goal.goal_id,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
            "tasks": task_list,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        return tasks

    # ── Result comparison ──────────────────────────────────────────────────────

    def compare_against_target(
        self,
        slot_id: str,
        current_score: Optional[float],
        block_result: dict[str, Any],
    ) -> dict[str, Any]:
        baseline = self.CERTIFIED_BASELINES.get(slot_id)
        target = self.TARGET_SCORE
        gap = round(target - (current_score or baseline or 0.0), 4)
        achieved = (current_score is not None and current_score >= target)
        return {
            "slot_id": slot_id,
            "target_score": target,
            "certified_baseline": baseline,
            "current_score": current_score,
            "gap_to_target": gap,
            "target_achieved_currently": achieved,
            "comparison_mode": "CERTIFIED_BASELINE",
            "block_quality_status": block_result.get("quality_status", "CANDIDATE"),
            "block_safe_for_next_cycle": block_result.get("safe_for_next_cycle", False),
            "next_action": "COLLECT_MORE_DATA" if not achieved else "EVAL_AND_PROMOTE",
        }

    # ── Continuation scheduling ────────────────────────────────────────────────

    def register_continuation(
        self,
        goal: ModelImprovementGoal,
        cycle_2_id: str,
        next_cycle_input: dict[str, Any],
    ) -> list[dict[str, Any]]:
        now = datetime.now(DUBAI_TZ)

        def _window(days: int, hour: int, minute: int = 0) -> str:
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            dt = dt + timedelta(days=days)
            return dt.isoformat()

        actions = [
            {
                "action_id": "PA-CONT-001",
                "title": "Continue model improvement loop — slot14 data collection trigger",
                "goal_id": goal.goal_id,
                "parent_cycle_id": cycle_2_id,
                "slot_id": "slot14",
                "owner_agent": "logi",
                "assigned_to": "traini",
                "trigger_condition": "gold_pairs >= 50 AND dpo_pairs >= 50",
                "preferred_window_start": _window(1, 22, 30),
                "preferred_window_end": _window(2, 6, 30),
                "timezone": "Asia/Dubai",
                "execution_handler": "logi_subprocess",
                "command_or_callable": "python3 ops/logi/continuous_model_improvement_loop.py",
                "command_args": ["--slot", "slot14", "--action", "data_collection_trigger"],
                "evidence_chain_required": True,
                "resource_policy": {
                    "max_vram_gb": 0,
                    "cpu_only_ok": True,
                    "no_slot120_load": True,
                },
                "next_cycle_input_ref": next_cycle_input.get("from_block", ""),
                "status": "PLANNED",
                "discoverable_by_scheduler": True,
            },
            {
                "action_id": "PA-CONT-002",
                "title": "Continue model improvement loop — slot32 eval plan trigger",
                "goal_id": goal.goal_id,
                "parent_cycle_id": cycle_2_id,
                "slot_id": "slot32",
                "owner_agent": "logi",
                "assigned_to": "traini",
                "trigger_condition": "slot32 dedicated AIMS dataset snapshot created",
                "preferred_window_start": _window(2, 22, 30),
                "preferred_window_end": _window(3, 6, 30),
                "timezone": "Asia/Dubai",
                "execution_handler": "logi_subprocess",
                "command_or_callable": "python3 ops/logi/continuous_model_improvement_loop.py",
                "command_args": ["--slot", "slot32", "--action", "data_collection_trigger"],
                "evidence_chain_required": True,
                "resource_policy": {
                    "max_vram_gb": 0,
                    "cpu_only_ok": True,
                    "no_slot120_load": True,
                },
                "status": "PLANNED",
                "discoverable_by_scheduler": True,
            },
        ]

        self._continuation_actions = actions
        path = self._dir / "planned_continuation_actions.json"
        path.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "goal_id": goal.goal_id,
            "cycle_2_id": cycle_2_id,
            "actions": actions,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        return actions

    # ── Lessons learned ────────────────────────────────────────────────────────

    def write_lessons_summary(
        self,
        goal: ModelImprovementGoal,
        cycle_1_results: list[dict[str, Any]],
        cycle_2_results: list[dict[str, Any]],
    ) -> Path:
        now = datetime.now(timezone.utc).isoformat()
        lessons = {
            "generated_at": now,
            "goal_id": goal.goal_id,
            "summary": [
                {
                    "lesson_id": f"lesson_{i+1:03d}",
                    "slot_id": r.get("slot_id", ""),
                    "cycle": r.get("cycle_number", 1),
                    "decision": r.get("decision", ""),
                    "key_lesson": r.get("key_lesson", ""),
                    "prevention_rule": r.get("prevention_rule", ""),
                }
                for i, r in enumerate(cycle_1_results + cycle_2_results)
            ],
            "rules": [
                "Never claim 0.98 achieved unless eval evidence file proves it",
                "Always write next_cycle_input before closing a cycle",
                "Cycle 2 must explicitly reference cycle 1 cycle_id in consumed_from_cycle",
                "Traini blocks are CANDIDATE until QA accepts; never treat as accepted before validation",
                "slot32 and slot120 must never be loaded concurrently",
                "Continuation actions must be discoverable by scheduler/PlannedActionRunner",
                "Heartbeat must be written within heartbeat_interval_seconds or run is STALE",
            ],
        }
        path = self._dir / "lessons_learned_summary.json"
        path.write_text(json.dumps(lessons, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    # ── Active 24h protection ──────────────────────────────────────────────────

    def detect_active_24h(self) -> dict[str, Any]:
        """Detect if an active 24h run is in progress."""
        active_pid_dir = ROOT / "aims_workspace" / "pids"
        long_running_files = list(ROOT.glob("aims_workspace/*/long_running_*.json")) + \
                             list(ROOT.glob("aims_workspace/*/24h_*.json"))
        active = bool(long_running_files)
        return {
            "detected": active,
            "long_running_files": [str(f.relative_to(ROOT)) for f in long_running_files[:5]],
            "action_taken": "NO_INTERRUPT" if active else "NONE",
            "safe": True,
        }
