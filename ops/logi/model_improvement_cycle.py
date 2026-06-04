"""Logi — Model Improvement Cycle.

Implements the evidence-chain iterative improvement loop:
  input_snapshot → goal → plan → execution → evidence → evaluation → result → next_cycle_input

Each cycle's result becomes structured input to the next cycle.
No heavy training is executed; this module plans and records.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
CYCLES_DIR = ROOT / "aims_workspace" / "model_tuning_readiness" / "cycles"
LESSONS_FILE = ROOT / "aims_workspace" / "repairman_memory" / "lessons.jsonl"

DUBAI_TZ = timezone(timedelta(hours=4))


# ── Cycle status constants ────────────────────────────────────────────────────

class CycleResult:
    EVAL_ONLY = "EVAL_ONLY"
    DATA_COLLECTION_REQUIRED = "DATA_COLLECTION_REQUIRED"
    BASELINE_READY = "BASELINE_READY"
    TUNING_READY = "TUNING_READY"
    BLOCKED = "BLOCKED"
    PROMOTION_CANDIDATE = "PROMOTION_CANDIDATE"
    REJECTED = "REJECTED"
    PLANNING_COMPLETE = "PLANNING_COMPLETE"


class CycleDecision:
    RUN_BASELINE_EVAL_FIRST = "RUN_BASELINE_EVAL_FIRST"
    COLLECT_MORE_DATA = "COLLECT_MORE_DATA"
    RUN_EVAL_ONLY = "RUN_EVAL_ONLY"
    SCHEDULE_TUNING_SMOKE = "SCHEDULE_TUNING_SMOKE"
    SCHEDULE_FULL_TUNING_CANDIDATE = "SCHEDULE_FULL_TUNING_CANDIDATE"
    BLOCKED_BY_RESOURCE_POLICY = "BLOCKED_BY_RESOURCE_POLICY"
    BLOCKED_BY_DATA_QUALITY = "BLOCKED_BY_DATA_QUALITY"
    BLOCKED_BY_MISSING_BASELINE = "BLOCKED_BY_MISSING_BASELINE"
    PROMOTION_BLOCKED = "PROMOTION_BLOCKED"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    SCHEDULE_DATA_COLLECTION_ACTION = "SCHEDULE_DATA_COLLECTION_ACTION"


# ── Cycle data structures ─────────────────────────────────────────────────────

@dataclass
class ImprovementCycle:
    cycle_id: str
    cycle_number: int
    slot_id: str
    input_snapshot_id: str
    input_data: dict[str, Any]
    goal: str
    target_score: float
    baseline_score: Optional[float]
    hypothesis: str
    plan: list[str]
    scheduled_action_id: Optional[str]
    execution_chain_id: Optional[str]
    execution_mode: str                 # DRY_RUN / EVAL_ONLY / LIGHTWEIGHT
    evidence_artifacts: list[str]
    evaluation_result: dict[str, Any]
    baseline_comparison: dict[str, Any]
    decision: str
    final_status: str
    next_cycle_input: dict[str, Any]
    lessons_learned: list[dict[str, Any]]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LessonRecord:
    cycle_id: str
    slot_id: str
    input_condition: str
    decision: str
    reason: str
    next_evidence_needed: str
    prevention_rule: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Cycle Runner ──────────────────────────────────────────────────────────────

class CycleRunner:
    """Runs evidence-chain improvement cycles for model slots."""

    TARGET_SCORE = 0.98

    def run_cycle_1(
        self,
        slot_assessment: Any,        # ModelSlotAssessment
        tuning_readiness: Any,       # TuningReadinessStatus
        snapshot: Any,               # DatasetSnapshot
        resource_policy: dict[str, Any],
        output_dir: Path,
    ) -> ImprovementCycle:
        """Cycle 1: assess → identify gaps → create next_cycle_input."""
        cycle_id = f"cycle1_{slot_assessment.slot_id}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        baseline = slot_assessment.current_baseline_score
        gap = round(self.TARGET_SCORE - (baseline or 0.0), 4) if baseline else None

        input_data = {
            "source": "model_level_assessment",
            "slot_id": slot_assessment.slot_id,
            "model_identifier": slot_assessment.current_model_identifier,
            "readiness_status": slot_assessment.readiness_status,
            "baseline_score": baseline,
            "eval_suite": slot_assessment.current_eval_suite,
            "eval_evidence_file": slot_assessment.eval_evidence_file,
            "training_dataset_version": snapshot.training_dataset_latest,
            "training_dataset_count": snapshot.training_dataset_latest_count,
            "gold_pairs": snapshot.gold_pairs_count,
            "dpo_pairs": snapshot.dpo_pairs_count,
            "resource_policy_status": resource_policy.get("overall_status"),
            "dataset_status": snapshot.dataset_status,
        }

        plan = self._build_plan_cycle1(slot_assessment, tuning_readiness, baseline, gap)
        decision = self._decide_cycle1(slot_assessment, tuning_readiness, baseline)
        final_status = self._status_from_decision(decision)

        evaluation = {
            "mode": "DRY_RUN",
            "baseline_score": baseline,
            "target_score": self.TARGET_SCORE,
            "gap_to_target": gap,
            "eval_suite": slot_assessment.current_eval_suite,
            "evaluation_performed": False,
            "note": "No heavy eval executed during certification; planning cycle only.",
        }

        baseline_comparison = {
            "baseline_available": baseline is not None,
            "baseline_score": baseline,
            "target_score": self.TARGET_SCORE,
            "gap": gap,
            "historical_peak": self._historical_peak(slot_assessment.slot_id),
            "target_achievable": True if gap is not None and gap <= 0.10 else None,
        }

        next_cycle_input = self._build_next_cycle_input_1(
            slot_assessment, tuning_readiness, snapshot, decision, baseline, gap, cycle_id
        )

        lessons = [self._lesson_from_cycle(
            cycle_id=cycle_id,
            slot_id=slot_assessment.slot_id,
            input_cond=f"baseline={baseline}, gap={gap}, mode={tuning_readiness.recommended_mode}",
            decision=decision,
            reason=tuning_readiness.reasoning,
            next_evidence=next_cycle_input.get("required_evidence", ""),
            prevention="Run baseline eval first if score is unknown; collect DPO pairs for RLHF cycles",
        )]

        self._append_lesson(lessons[0])

        cycle = ImprovementCycle(
            cycle_id=cycle_id,
            cycle_number=1,
            slot_id=slot_assessment.slot_id,
            input_snapshot_id=snapshot.snapshot_id,
            input_data=input_data,
            goal=f"Assess {slot_assessment.slot_id} level and identify path to 0.98",
            target_score=self.TARGET_SCORE,
            baseline_score=baseline,
            hypothesis=(
                f"{slot_assessment.slot_id} can reach 0.98 through targeted data collection "
                f"and iterative eval-tuning cycles. Current gap: {gap}."
            ) if baseline else f"{slot_assessment.slot_id} baseline unknown; establish eval first.",
            plan=plan,
            scheduled_action_id=None,
            execution_chain_id=f"exec_dry_{slot_assessment.slot_id}_c1",
            execution_mode="DRY_RUN",
            evidence_artifacts=self._collect_evidence_artifacts(slot_assessment),
            evaluation_result=evaluation,
            baseline_comparison=baseline_comparison,
            decision=decision,
            final_status=final_status,
            next_cycle_input=next_cycle_input,
            lessons_learned=lessons,
            timestamp=now,
        )

        self._write_cycle(cycle, output_dir)
        return cycle

    def run_cycle_2(
        self,
        cycle_1: ImprovementCycle,
        output_dir: Path,
    ) -> ImprovementCycle:
        """Cycle 2: consume cycle 1 result → refine plan → create planned actions."""
        cycle_id = f"cycle2_{cycle_1.slot_id}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        input_data = cycle_1.next_cycle_input.copy()
        input_data["consumed_from_cycle"] = cycle_1.cycle_id

        slot_id = cycle_1.slot_id
        decision_c1 = cycle_1.decision
        baseline = cycle_1.baseline_score
        gap = cycle_1.baseline_comparison.get("gap")

        plan = self._build_plan_cycle2(slot_id, decision_c1, baseline, gap, input_data)
        decision_c2 = self._decide_cycle2(slot_id, decision_c1, input_data)
        scheduled_action = self._suggest_planned_action_id(slot_id, decision_c2)

        evaluation = {
            "mode": "PLANNING",
            "cycle_1_decision_consumed": decision_c1,
            "cycle_1_status": cycle_1.final_status,
            "refined_plan_created": True,
            "planned_action_proposed": scheduled_action is not None,
        }

        baseline_comparison = {
            "cycle_1_baseline": baseline,
            "cycle_1_gap": gap,
            "cycle_2_action": decision_c2,
            "progress": "PLANNING_STAGE",
        }

        next_cycle_input = {
            "from_cycle": cycle_id,
            "slot_id": slot_id,
            "cycle_number": 3,
            "prior_decision": decision_c2,
            "planned_action_id": scheduled_action,
            "required_evidence": self._required_evidence_cycle3(slot_id, decision_c2),
            "ready_for_cycle_3_when": self._ready_condition(slot_id, decision_c2),
        }

        final_status = CycleResult.PLANNING_COMPLETE

        lessons = [self._lesson_from_cycle(
            cycle_id=cycle_id,
            slot_id=slot_id,
            input_cond=f"consuming_cycle_1: decision={decision_c1}, gap={gap}",
            decision=decision_c2,
            reason=f"Cycle 2 refines cycle 1 output. Proposed action: {scheduled_action}",
            next_evidence=next_cycle_input.get("required_evidence", ""),
            prevention="Chain cycles explicitly; each cycle must write next_cycle_input before closing.",
        )]

        self._append_lesson(lessons[0])

        cycle = ImprovementCycle(
            cycle_id=cycle_id,
            cycle_number=2,
            slot_id=slot_id,
            input_snapshot_id=cycle_1.input_snapshot_id,
            input_data=input_data,
            goal=f"Refine cycle 1 plan for {slot_id}: create concrete next action",
            target_score=self.TARGET_SCORE,
            baseline_score=baseline,
            hypothesis=(
                f"Based on cycle 1 decision ({decision_c1}), "
                f"cycle 2 produces a concrete planned action ({scheduled_action}) "
                f"to move {slot_id} closer to 0.98."
            ),
            plan=plan,
            scheduled_action_id=scheduled_action,
            execution_chain_id=f"exec_dry_{slot_id}_c2",
            execution_mode="DRY_RUN",
            evidence_artifacts=[
                f"improvement_cycle_1.json (slot={slot_id})",
                "planned_model_actions.json",
            ],
            evaluation_result=evaluation,
            baseline_comparison=baseline_comparison,
            decision=decision_c2,
            final_status=final_status,
            next_cycle_input=next_cycle_input,
            lessons_learned=lessons,
            timestamp=now,
        )

        self._write_cycle(cycle, output_dir)
        return cycle

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_plan_cycle1(self, slot, readiness, baseline, gap) -> list[str]:
        steps = [
            f"1. Load model level assessment for {slot.slot_id}",
            f"2. Confirm current baseline: {baseline} on {slot.current_eval_suite or 'unknown suite'}",
            f"3. Compute gap to target 0.98: {gap}",
            f"4. Check dataset snapshot: training_v={slot.known_data_sources}",
            f"5. Classify tuning readiness: {readiness.recommended_mode}",
            f"6. Check resource policy: {readiness.resource_policy_status}",
            f"7. Apply decision policy: {readiness.reasoning[:120]}",
            "8. Write evidence artifacts and create next_cycle_input",
        ]
        return steps

    def _build_plan_cycle2(self, slot_id, decision_c1, baseline, gap, input_data) -> list[str]:
        steps = [
            f"1. Consume cycle 1 output: decision={decision_c1}, gap={gap}",
            f"2. Determine concrete next action for {slot_id}",
        ]
        if decision_c1 == CycleDecision.COLLECT_MORE_DATA:
            steps += [
                "3. Create data collection planned action (PA-MTR-xxx)",
                "4. Define required data types: gold pairs, DPO pairs",
                "5. Set data threshold trigger for cycle 3 activation",
            ]
        elif decision_c1 == CycleDecision.RUN_BASELINE_EVAL_FIRST:
            steps += [
                "3. Create baseline eval planned action (PA-MTR-xxx)",
                "4. Define eval suite and acceptance criteria",
                "5. Set baseline threshold for tuning smoke eligibility",
            ]
        elif decision_c1 == CycleDecision.SCHEDULE_TUNING_SMOKE:
            steps += [
                "3. Create tuning smoke planned action (PA-MTR-xxx)",
                "4. Define smoke success criteria: score improvement ≥ 0.02",
                "5. Set full tuning eligibility conditions",
            ]
        else:
            steps += [
                "3. Record blocked status with reason",
                "4. Define unblocking conditions",
            ]
        steps.append("6. Write final_status=PLANNING_COMPLETE and next_cycle_input")
        return steps

    def _decide_cycle1(self, slot, readiness, baseline) -> str:
        if readiness.recommended_mode == "BLOCKED":
            return CycleDecision.BLOCKED_BY_RESOURCE_POLICY
        if baseline is None:
            return CycleDecision.RUN_BASELINE_EVAL_FIRST
        if readiness.recommended_mode == "DATA_COLLECTION":
            return CycleDecision.COLLECT_MORE_DATA
        if readiness.recommended_mode == "TUNING_SMOKE":
            return CycleDecision.SCHEDULE_TUNING_SMOKE
        if readiness.recommended_mode == "EVAL_ONLY":
            return CycleDecision.RUN_EVAL_ONLY
        return CycleDecision.NO_ACTION_REQUIRED

    def _decide_cycle2(self, slot_id, decision_c1, input_data) -> str:
        if decision_c1 == CycleDecision.COLLECT_MORE_DATA:
            return CycleDecision.SCHEDULE_DATA_COLLECTION_ACTION
        if decision_c1 == CycleDecision.RUN_BASELINE_EVAL_FIRST:
            return CycleDecision.RUN_BASELINE_EVAL_FIRST
        if decision_c1 == CycleDecision.SCHEDULE_TUNING_SMOKE:
            return CycleDecision.SCHEDULE_TUNING_SMOKE
        if decision_c1 == CycleDecision.BLOCKED_BY_RESOURCE_POLICY:
            return CycleDecision.BLOCKED_BY_RESOURCE_POLICY
        return CycleDecision.RUN_EVAL_ONLY

    def _status_from_decision(self, decision) -> str:
        mapping = {
            CycleDecision.RUN_BASELINE_EVAL_FIRST: CycleResult.EVAL_ONLY,
            CycleDecision.COLLECT_MORE_DATA: CycleResult.DATA_COLLECTION_REQUIRED,
            CycleDecision.RUN_EVAL_ONLY: CycleResult.EVAL_ONLY,
            CycleDecision.SCHEDULE_TUNING_SMOKE: CycleResult.TUNING_READY,
            CycleDecision.SCHEDULE_FULL_TUNING_CANDIDATE: CycleResult.TUNING_READY,
            CycleDecision.BLOCKED_BY_RESOURCE_POLICY: CycleResult.BLOCKED,
            CycleDecision.BLOCKED_BY_DATA_QUALITY: CycleResult.BLOCKED,
            CycleDecision.BLOCKED_BY_MISSING_BASELINE: CycleResult.EVAL_ONLY,
            CycleDecision.PROMOTION_BLOCKED: CycleResult.BLOCKED,
            CycleDecision.NO_ACTION_REQUIRED: CycleResult.EVAL_ONLY,
            CycleDecision.SCHEDULE_DATA_COLLECTION_ACTION: CycleResult.DATA_COLLECTION_REQUIRED,
        }
        return mapping.get(decision, CycleResult.EVAL_ONLY)

    def _build_next_cycle_input_1(
        self, slot, readiness, snapshot, decision, baseline, gap, from_cycle_id
    ) -> dict[str, Any]:
        return {
            "from_cycle": from_cycle_id,
            "slot_id": slot.slot_id,
            "cycle_number": 2,
            "prior_decision": decision,
            "baseline_score": baseline,
            "gap_to_target": gap,
            "recommended_mode": readiness.recommended_mode,
            "dataset_status": snapshot.dataset_status,
            "gold_pairs_current": snapshot.gold_pairs_count,
            "dpo_pairs_current": snapshot.dpo_pairs_count,
            "required_evidence": self._required_evidence_cycle2(slot.slot_id, decision),
            "ready_for_cycle_2_when": "Cycle 1 complete; cycle 2 triggers immediately",
        }

    def _required_evidence_cycle2(self, slot_id, decision) -> str:
        if decision == CycleDecision.COLLECT_MORE_DATA:
            return "gold_pairs ≥ 50, dpo_pairs ≥ 50; or dataset snapshot updated"
        if decision == CycleDecision.RUN_BASELINE_EVAL_FIRST:
            return "baseline eval result JSON from golden_v3 or equivalent suite"
        if decision == CycleDecision.SCHEDULE_TUNING_SMOKE:
            return "tuning smoke result: score improvement ≥ 0.02"
        if decision == CycleDecision.BLOCKED_BY_RESOURCE_POLICY:
            return "Argus SAFE signal; slot32 unloaded if slot120 needed"
        return "cycle 1 evidence artifacts reviewed"

    def _required_evidence_cycle3(self, slot_id, decision) -> str:
        if decision == CycleDecision.SCHEDULE_DATA_COLLECTION_ACTION:
            return "data collection planned action executed; new pairs accumulated"
        if decision == CycleDecision.RUN_BASELINE_EVAL_FIRST:
            return "baseline eval executed and recorded in FT_LOGS"
        if decision == CycleDecision.SCHEDULE_TUNING_SMOKE:
            return "tuning smoke run completed; eval result shows ≥ 0.02 improvement"
        return "cycle 2 planned actions reviewed and triggered"

    def _ready_condition(self, slot_id, decision) -> str:
        if decision == CycleDecision.SCHEDULE_DATA_COLLECTION_ACTION:
            return "When gold_pairs ≥ 50 OR data collection planned action completes"
        if decision == CycleDecision.RUN_BASELINE_EVAL_FIRST:
            return "When baseline eval planned action completes"
        if decision == CycleDecision.BLOCKED_BY_RESOURCE_POLICY:
            return "When Argus reports SAFE and resource conflict resolved"
        return "When planned action from cycle 2 completes"

    def _suggest_planned_action_id(self, slot_id, decision) -> Optional[str]:
        action_map = {
            CycleDecision.SCHEDULE_DATA_COLLECTION_ACTION: f"PA-MTR-DC-{slot_id}",
            CycleDecision.RUN_BASELINE_EVAL_FIRST: f"PA-MTR-EVAL-{slot_id}",
            CycleDecision.SCHEDULE_TUNING_SMOKE: f"PA-MTR-SMOKE-{slot_id}",
        }
        return action_map.get(decision)

    def _historical_peak(self, slot_id) -> Optional[float]:
        peaks = {
            "slot14": 0.98,   # omi-ft-14b-v15 on 405B-judge eval (50 cases) — evidence: eval_v15_judge405b.json
            "slot32": 0.80,   # axi_omi_sphere on repairman_eval
            "slot120": 0.76,  # nemotron-3-super:120b on repairman_eval
            "cloud_teacher": None,
        }
        return peaks.get(slot_id)

    def _collect_evidence_artifacts(self, slot) -> list[str]:
        artifacts = []
        if slot.eval_evidence_file:
            artifacts.append(slot.eval_evidence_file)
        if slot.slot_id == "slot14":
            artifacts += [
                "ops/ft/logs/eval_v15_judge405b.json (historical 0.98 on 405B judge)",
                "ops/ft/logs/deployed_model.txt",
                "ops/ft/data/v18/ (793 training samples)",
            ]
        elif slot.slot_id == "slot32":
            artifacts += [
                "aims_workspace/repairman_memory/repairman_pairs_auto.jsonl",
                "ops/ft/configs/teacher_distill.qwen3_32b.json",
            ]
        elif slot.slot_id == "slot120":
            artifacts += [
                "aims_workspace/repairman_memory/repairman_pairs_auto.jsonl",
                "ops/ft/eval/repairman_eval_v1.json",
            ]
        return artifacts

    def _lesson_from_cycle(
        self,
        cycle_id: str,
        slot_id: str,
        input_cond: str,
        decision: str,
        reason: str,
        next_evidence: str,
        prevention: str,
    ) -> dict[str, Any]:
        return LessonRecord(
            cycle_id=cycle_id,
            slot_id=slot_id,
            input_condition=input_cond,
            decision=decision,
            reason=reason[:300],
            next_evidence_needed=next_evidence,
            prevention_rule=prevention,
        ).to_dict()

    def _append_lesson(self, lesson: dict[str, Any]) -> None:
        try:
            LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LESSONS_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(lesson, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _write_cycle(self, cycle: ImprovementCycle, output_dir: Path) -> None:
        CYCLES_DIR.mkdir(parents=True, exist_ok=True)
        path = CYCLES_DIR / f"{cycle.cycle_id}.json"
        path.write_text(
            json.dumps(cycle.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )


# ── Planned Actions Factory ───────────────────────────────────────────────────

def build_model_planned_actions(
    assessments: list,           # list[ModelSlotAssessment]
    readiness_list: list,        # list[TuningReadinessStatus]
    cycle_1_results: list[ImprovementCycle],
) -> list[dict[str, Any]]:
    """Create planned actions for baseline eval / data collection / tuning smoke."""
    now = datetime.now(DUBAI_TZ)

    def _window(days_offset: int, hour: int, minute: int = 0) -> str:
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        from datetime import timedelta as td
        dt = dt + td(days=days_offset)
        return dt.isoformat()

    actions = []
    action_counter = 1

    assess_map = {a.slot_id: a for a in assessments}
    ready_map = {r.slot_id: r for r in readiness_list}
    cycle_map = {c.slot_id: c for c in cycle_1_results}

    for slot_id in ["slot14", "slot32", "slot120"]:
        a = assess_map.get(slot_id)
        r = ready_map.get(slot_id)
        c = cycle_map.get(slot_id)
        if not a or not r:
            continue

        decision = c.decision if c else "UNKNOWN"

        if decision in (CycleDecision.COLLECT_MORE_DATA, CycleDecision.SCHEDULE_DATA_COLLECTION_ACTION):
            actions.append({
                "action_id": f"PA-MTR-{action_counter:03d}",
                "title": f"Data collection — {slot_id}",
                "slot_id": slot_id,
                "owner_agent": "traini",
                "coordinating_agent": "logi",
                "supporting_agents": ["argus", "qa", "poli"],
                "due_time": _window(1, 22, 30),
                "timezone": "Asia/Dubai",
                "preferred_window": "night (22:30–06:30 Dubai)",
                "execution_handler": "logi_subprocess",
                "evidence_chain_required": True,
                "expected_artifacts": [
                    f"aims_workspace/axi_ft_log/gold_pairs.jsonl (add ≥50 new pairs)",
                    f"aims_workspace/axi_ft_log/dpo_pairs.jsonl (accumulate ≥50 pairs)",
                ],
                "validation_plan": "gold_pairs ≥ 50 AND dpo_pairs ≥ 50",
                "resource_policy": {
                    "max_vram_gb": 34,
                    "allowed_model_slots": ["slot32"],
                    "forbidden_concurrent_slots": ["slot120"],
                    "max_wall_time_minutes": 60,
                    "cpu_only_ok": False,
                },
                "promotion_policy": {"no_auto_promote": True},
                "rollback_policy": "Do not delete existing pairs; append only",
                "lessons_learned_plan": "Record data collection result in repairman_memory/lessons.jsonl",
                "cycle_ref": c.cycle_id if c else None,
            })
            action_counter += 1

        if decision in (CycleDecision.RUN_BASELINE_EVAL_FIRST, CycleDecision.RUN_EVAL_ONLY):
            eval_suite = a.current_eval_suite or "golden_v3_action_routing.json"
            actions.append({
                "action_id": f"PA-MTR-{action_counter:03d}",
                "title": f"Baseline eval — {slot_id}",
                "slot_id": slot_id,
                "owner_agent": "traini",
                "coordinating_agent": "logi",
                "supporting_agents": ["argus", "qa", "poli"],
                "due_time": _window(2, 23, 0),
                "timezone": "Asia/Dubai",
                "preferred_window": "night (22:30–06:30 Dubai)",
                "execution_handler": "logi_subprocess",
                "evidence_chain_required": True,
                "expected_artifacts": [
                    f"ops/ft/logs/eval_{slot_id}_baseline_<date>.json",
                    "evidence/eval_result.json",
                ],
                "validation_plan": f"pass_rate recorded; no score invented; eval_suite={eval_suite}",
                "resource_policy": {
                    "max_vram_gb": 0 if slot_id == "cloud_teacher" else 34,
                    "allowed_model_slots": [slot_id] if slot_id != "cloud_teacher" else [],
                    "forbidden_concurrent_slots": ["slot120"] if slot_id == "slot32" else [],
                    "max_wall_time_minutes": 30,
                    "cpu_only_ok": slot_id == "cloud_teacher",
                },
                "promotion_policy": {"no_auto_promote": True},
                "rollback_policy": "Eval is read-only; no rollback needed",
                "lessons_learned_plan": "Record eval result in lessons.jsonl; update model_level_inventory.json",
                "cycle_ref": c.cycle_id if c else None,
            })
            action_counter += 1

        if decision == CycleDecision.SCHEDULE_TUNING_SMOKE and slot_id == "slot14":
            actions.append({
                "action_id": f"PA-MTR-{action_counter:03d}",
                "title": f"Tuning smoke — {slot_id}",
                "slot_id": slot_id,
                "owner_agent": "traini",
                "coordinating_agent": "logi",
                "supporting_agents": ["argus", "qa", "poli", "release"],
                "due_time": _window(3, 0, 30),
                "timezone": "Asia/Dubai",
                "preferred_window": "night (00:30–05:30 Dubai)",
                "execution_handler": "logi_subprocess",
                "evidence_chain_required": True,
                "expected_artifacts": [
                    "ops/ft/logs/eval_14_vN_smoke.json",
                    "ops/ft/output/adapter_14_vN/ (smoke adapter)",
                ],
                "validation_plan": "score improvement ≥ 0.02 vs baseline; no regression on golden_v3",
                "resource_policy": {
                    "max_vram_gb": 34,
                    "allowed_model_slots": ["slot14", "slot32"],
                    "forbidden_concurrent_slots": ["slot120"],
                    "max_wall_time_minutes": 120,
                    "cpu_only_ok": False,
                },
                "promotion_policy": {
                    "no_auto_promote": True,
                    "requires": ["QA gate", "Poli approval", "Release gate"],
                },
                "rollback_policy": "Keep prior adapter; do not delete v15/v16/v17/v18 adapters",
                "lessons_learned_plan": "Record smoke result; update improvement roadmap",
                "cycle_ref": c.cycle_id if c else None,
            })
            action_counter += 1

    return actions
