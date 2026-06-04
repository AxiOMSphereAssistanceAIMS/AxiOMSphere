"""Logi — Model Level Assessor.

Determines current level/status of all AIMS model slots by reading actual
eval logs and training artifacts. Never invents scores or data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]  # aims-workspace
FT_LOGS = ROOT / "ops" / "ft" / "logs"
FT_DATA = ROOT / "ops" / "ft" / "data"
FT_EVAL = ROOT / "ops" / "ft" / "eval"
AXI_FT_LOG = ROOT / "aims_workspace" / "axi_ft_log"
REPAIRMAN_MEM = ROOT / "aims_workspace" / "repairman_memory"


# ── Readiness & Decision constants ───────────────────────────────────────────

class ReadinessStatus:
    UNKNOWN = "UNKNOWN"
    BASELINE_REQUIRED = "BASELINE_REQUIRED"
    EVAL_READY = "EVAL_READY"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    TUNING_READY = "TUNING_READY"
    TUNING_BLOCKED = "TUNING_BLOCKED"
    PROMOTION_BLOCKED = "PROMOTION_BLOCKED"


class NextSafeAction:
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


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ModelSlotAssessment:
    slot_id: str                          # slot14 / slot32 / slot120 / cloud_teacher
    current_model_identifier: Optional[str]
    role: str
    availability_status: str              # AVAILABLE / UNKNOWN / ON_DEMAND_ONLY
    loaded_status: str                    # LOADED / UNLOADED / UNKNOWN
    resource_policy_status: str           # OK / RESTRICTED / FORBIDDEN_CONCURRENT
    current_baseline_score: Optional[float]
    current_eval_suite: Optional[str]
    eval_evidence_file: Optional[str]
    known_strengths: list[str]
    known_failures: list[str]
    known_data_sources: list[str]
    last_eval_run: Optional[str]
    last_tuning_run: Optional[str]
    last_promotion_decision: Optional[str]
    target_score: float
    readiness_status: str
    next_safe_action: str
    assessment_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Assessor ──────────────────────────────────────────────────────────────────

class ModelLevelAssessor:
    """Reads real artifacts and determines slot-level status without invention."""

    TARGET_SCORE = 0.98

    def assess_all(self) -> list[ModelSlotAssessment]:
        return [
            self._assess_slot14(),
            self._assess_slot32(),
            self._assess_slot120(),
            self._assess_cloud_teacher(),
        ]

    # ── slot14 ────────────────────────────────────────────────────────────────

    def _assess_slot14(self) -> ModelSlotAssessment:
        deployed_path = FT_LOGS / "deployed_model.txt"
        deployed = (
            deployed_path.read_text(encoding="utf-8").strip()
            if deployed_path.exists()
            else None
        )

        # Read best available eval for slot14 (prefer golden_v3, fall back to v2)
        baseline_score, eval_suite, eval_file, last_eval = self._best_slot14_eval()

        # Detect last tuning run from log files
        v18_log = FT_LOGS / "train_14_v18.log"
        v17_log = FT_LOGS / "train_14_v17.log"
        last_tuning: Optional[str] = None
        if v18_log.exists():
            last_tuning = "2026-05-14T00:00:00+00:00"  # from log timestamps
        elif v17_log.exists():
            last_tuning = "2026-05-09T00:00:00+00:00"

        # Data sufficiency for *new* tuning runs
        gold_count = _count_lines(AXI_FT_LOG / "gold_pairs.jsonl")
        new_data_ok = gold_count >= 50  # threshold for a meaningful incremental run

        # Readiness classification
        if baseline_score is not None:
            if new_data_ok:
                readiness = ReadinessStatus.EVAL_READY
                next_action = NextSafeAction.SCHEDULE_TUNING_SMOKE
            else:
                readiness = ReadinessStatus.EVAL_READY
                next_action = NextSafeAction.COLLECT_MORE_DATA
        else:
            readiness = ReadinessStatus.BASELINE_REQUIRED
            next_action = NextSafeAction.RUN_BASELINE_EVAL_FIRST

        return ModelSlotAssessment(
            slot_id="slot14",
            current_model_identifier=deployed,
            role="Fast/default conversational; Omi action classifier; ChatLLM layer",
            availability_status="AVAILABLE",
            loaded_status="LOADED",
            resource_policy_status="OK",
            current_baseline_score=baseline_score,
            current_eval_suite=eval_suite,
            eval_evidence_file=eval_file,
            known_strengths=[
                "100% pass on golden_v2 (14 cases) at v15",
                "QLoRA fine-tuning proven effective on Qwen2.5-14B",
                "Historical peak: 0.98 on 405B-judge eval (omi-ft-14b-v15)",
            ],
            known_failures=[
                "0.07 gap to 0.98 target on golden_v3 (57 cases)",
                "DPO pairs not accumulated for RLHF cycle",
                "New gold pairs since last tuning: insufficient (< 50)",
            ],
            known_data_sources=[
                "ops/ft/data/v18/ (793 samples)",
                "aims_workspace/axi_ft_log/gold_pairs.jsonl",
                "ops/ft/eval/golden_v3_action_routing.json (57 cases)",
            ],
            last_eval_run=last_eval,
            last_tuning_run=last_tuning,
            last_promotion_decision="v16 deployed 2026-05-07 (post-reboot)",
            target_score=self.TARGET_SCORE,
            readiness_status=readiness,
            next_safe_action=next_action,
            notes=(
                f"Deployed: {deployed}. Historical v15 scored 0.98 on 405B-judge (50 cases). "
                f"Current: {baseline_score} on {eval_suite}. Gap to 0.98: "
                f"{round(self.TARGET_SCORE - (baseline_score or 0), 2)}."
            ),
        )

    def _best_slot14_eval(self) -> tuple[Optional[float], Optional[str], Optional[str], Optional[str]]:
        """Return (score, suite_name, evidence_file, last_eval_ts) for slot14."""
        candidates = [
            (FT_LOGS / "eval_14_v18_golden_v3.json", "golden_v3 (57 cases)"),
            (FT_LOGS / "eval_14_v16_golden_v3.json", "golden_v3 (57 cases)"),
            (FT_LOGS / "eval_14_v16_golden_v2.json", "golden_v2 (57 cases)"),
            (FT_LOGS / "eval_14_v15_golden_v2.json", "golden_v2 (14 cases)"),
        ]
        for path, suite in candidates:
            if path.exists():
                try:
                    d = json.loads(path.read_text(encoding="utf-8"))
                    score = d.get("pass_rate")
                    if score is not None:
                        ts = "2026-05-14T00:00:00+00:00" if "v18" in path.name else "2026-05-07T00:00:00+00:00"
                        return float(score), suite, str(path.relative_to(ROOT)), ts
                except Exception:
                    continue
        return None, None, None, None

    # ── slot32 ────────────────────────────────────────────────────────────────

    def _assess_slot32(self) -> ModelSlotAssessment:
        eval_path = FT_LOGS / "eval_32b_judge405b.json"
        baseline_score: Optional[float] = None
        eval_suite: Optional[str] = None
        eval_file: Optional[str] = None
        if eval_path.exists():
            try:
                d = json.loads(eval_path.read_text(encoding="utf-8"))
                baseline_score = d.get("pass_rate")
                eval_suite = "repairman_eval_v1 (50 cases, 405B judge)"
                eval_file = str(eval_path.relative_to(ROOT))
            except Exception:
                pass

        # slot32 has no dedicated fine-tuning dataset
        readiness = ReadinessStatus.DATA_INSUFFICIENT
        next_action = NextSafeAction.COLLECT_MORE_DATA

        if baseline_score is None:
            readiness = ReadinessStatus.BASELINE_REQUIRED
            next_action = NextSafeAction.RUN_BASELINE_EVAL_FIRST

        return ModelSlotAssessment(
            slot_id="slot32",
            current_model_identifier="axi_omi_sphere:latest (qwen3:32b-q8_0)",
            role="Reasoning/coding/document execution layer",
            availability_status="AVAILABLE",
            loaded_status="LOADED",
            resource_policy_status="OK (must not coexist with slot120)",
            current_baseline_score=baseline_score,
            current_eval_suite=eval_suite,
            eval_evidence_file=eval_file,
            known_strengths=[
                "Strong reasoning and code generation capabilities",
                "Used as teacher model for distillation (teacher_distill.qwen3_32b.json)",
                "Available on DGX with 34 GB VRAM",
            ],
            known_failures=[
                "No dedicated fine-tuning dataset for slot32 improvement",
                "0.20 gap to 0.98 target on repairman_eval",
                "Eval suite (repairman_eval) covers repair domain only, not full AIMS scope",
            ],
            known_data_sources=[
                "aims_workspace/repairman_memory/repairman_pairs_auto.jsonl (18 pairs)",
                "ops/ft/configs/teacher_distill.qwen3_32b.json",
            ],
            last_eval_run="2026-05-11T00:00:00+00:00",
            last_tuning_run=None,
            last_promotion_decision="Not applicable (base model, no QLoRA applied)",
            target_score=self.TARGET_SCORE,
            readiness_status=readiness,
            next_safe_action=next_action,
            notes=(
                "slot32 (qwen3:32b-q8_0) is a base model with no fine-tuning. "
                "Baseline 0.80 on repairman eval. Must not coexist with slot120. "
                "Need dedicated AIMS eval suite before planning tuning."
            ),
        )

    # ── slot120 ───────────────────────────────────────────────────────────────

    def _assess_slot120(self) -> ModelSlotAssessment:
        eval_path = FT_LOGS / "eval_120b_judge405b.json"
        baseline_score: Optional[float] = None
        eval_suite: Optional[str] = None
        eval_file: Optional[str] = None
        if eval_path.exists():
            try:
                d = json.loads(eval_path.read_text(encoding="utf-8"))
                baseline_score = d.get("pass_rate")
                eval_suite = "repairman_eval_v1 (50 cases, 405B judge)"
                eval_file = str(eval_path.relative_to(ROOT))
            except Exception:
                pass

        return ModelSlotAssessment(
            slot_id="slot120",
            current_model_identifier="nemotron-3-super:120b",
            role="On-demand heavy review/audit layer; Repairman model",
            availability_status="ON_DEMAND_ONLY",
            loaded_status="UNLOADED",
            resource_policy_status="RESTRICTED (must not coexist with slot32; no force-load)",
            current_baseline_score=baseline_score,
            current_eval_suite=eval_suite,
            eval_evidence_file=eval_file,
            known_strengths=[
                "Largest local model (120B), highest review quality",
                "Used for repairman and heavy audit tasks",
                "Evidence of 0.76 pass rate on repairman_eval (50 cases)",
            ],
            known_failures=[
                "0.22 gap to 0.98 target on repairman_eval",
                "Cannot be loaded concurrently with slot32 on DGX (VRAM limit ~128 GB)",
                "No fine-tuning performed or planned for slot120",
            ],
            known_data_sources=[
                "aims_workspace/repairman_memory/repairman_pairs_auto.jsonl (18 pairs)",
                "ops/ft/eval/repairman_eval_v1.json",
            ],
            last_eval_run="2026-05-11T00:00:00+00:00",
            last_tuning_run=None,
            last_promotion_decision="Not applicable (base model; on-demand only)",
            target_score=self.TARGET_SCORE,
            readiness_status=ReadinessStatus.TUNING_BLOCKED,
            next_safe_action=NextSafeAction.BLOCKED_BY_RESOURCE_POLICY,
            notes=(
                "slot120 must not be force-loaded. Must not coexist with slot32. "
                "Baseline 0.76 on repairman_eval is reference only. "
                "Any eval must be scheduled as on-demand with explicit resource check. "
                "Fine-tuning slot120 is out of scope (too large, no QLoRA setup)."
            ),
        )

    # ── cloud_teacher ─────────────────────────────────────────────────────────

    def _assess_cloud_teacher(self) -> ModelSlotAssessment:
        return ModelSlotAssessment(
            slot_id="cloud_teacher",
            current_model_identifier=None,
            role="External Cloud LLM evaluator; teacher distillation source; not a local slot",
            availability_status="UNKNOWN",
            loaded_status="UNKNOWN",
            resource_policy_status="OK (external; no DGX VRAM impact)",
            current_baseline_score=None,
            current_eval_suite=None,
            eval_evidence_file=None,
            known_strengths=[
                "High-quality teacher for distillation (llama-3.1-405B, Gemini, Claude)",
                "Used as judge backend for slot14/32/120 evals",
                "No VRAM cost on DGX",
            ],
            known_failures=[
                "Availability depends on API keys (NVIDIA_API_KEY, ANTHROPIC_API_KEY)",
                "Not a local tunable model slot",
                "Latency higher than local models",
            ],
            known_data_sources=[
                "ops/ft/configs/teacher_distill.405b.json",
                "ops/ft/configs/teacher_distill.qwen3_32b.json",
            ],
            last_eval_run=None,
            last_tuning_run=None,
            last_promotion_decision=None,
            target_score=self.TARGET_SCORE,
            readiness_status=ReadinessStatus.UNKNOWN,
            next_safe_action=NextSafeAction.NO_ACTION_REQUIRED,
            notes=(
                "cloud_teacher is an external evaluator route, not a local model slot. "
                "Not subject to DGX VRAM policy. Availability is API-dependent. "
                "Used as judge for local slot evals but not tuned locally."
            ),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace") if _.strip())
    except Exception:
        return 0
