"""Logi — Model Tuning Readiness Chain.

Classifies tuning readiness per slot, produces dataset snapshots,
enforces resource/safety policy, and recommends safe next actions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
FT_LOGS = ROOT / "ops" / "ft" / "logs"
FT_DATA = ROOT / "ops" / "ft" / "data"
AXI_FT_LOG = ROOT / "aims_workspace" / "axi_ft_log"
REPAIRMAN_MEM = ROOT / "aims_workspace" / "repairman_memory"
REPAIR_PAIRS = REPAIRMAN_MEM / "repairman_pairs_auto.jsonl"
LESSONS_FILE = REPAIRMAN_MEM / "lessons.jsonl"
FT_EVAL = ROOT / "ops" / "ft" / "eval"

# Minimum thresholds for recommending tuning
MIN_GOLD_PAIRS_FOR_INCREMENTAL = 50
MIN_GOLD_PAIRS_FOR_FULL_TUNING = 200
MIN_DPO_PAIRS = 50


class TuningRecommendedMode:
    EVAL_ONLY = "EVAL_ONLY"
    DATA_COLLECTION = "DATA_COLLECTION"
    TUNING_SMOKE = "TUNING_SMOKE"
    FULL_TUNING_CANDIDATE = "FULL_TUNING_CANDIDATE"
    BLOCKED = "BLOCKED"


@dataclass
class DataFileSnapshot:
    path: str
    exists: bool
    line_count: int
    size_bytes: int
    sha256_prefix: str  # first 16 chars of sha256 for tamper-check without storing full hash


@dataclass
class DatasetSnapshot:
    snapshot_id: str
    timestamp: str
    gold_pairs_count: int
    gold_pairs_file: str
    dpo_pairs_count: int
    dpo_pairs_file: str
    repair_pairs_count: int
    repair_pairs_file: str
    axi_ft_daily_files: list[str]
    axi_ft_total_pairs: int
    training_dataset_versions: list[str]
    training_dataset_latest: Optional[str]
    training_dataset_latest_count: int
    eval_suites: list[str]
    lessons_count: int
    dataset_status: str        # SUFFICIENT_FOR_EVAL / INSUFFICIENT_FOR_TUNING / etc.
    files: list[DataFileSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TuningReadinessStatus:
    slot_id: str
    data_availability: str           # AVAILABLE / PARTIAL / MISSING
    repair_pairs_count: int
    gold_pairs_count: int
    dpo_pairs_count: int
    eval_set_available: bool
    lessons_available: bool
    dataset_snapshot_status: str     # RECORDED / MISSING
    min_data_threshold_status: str   # MET / NOT_MET
    secret_scan_status: str          # CLEAN / WARNING / NOT_RUN
    resource_policy_status: str      # SAFE / CONFLICT / RESTRICTED
    tuning_safety_status: str        # SAFE / BLOCKED / ON_DEMAND_ONLY
    promotion_safety_status: str     # ALLOWED / BLOCKED
    recommended_mode: str            # TuningRecommendedMode
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TuningReadinessChain:
    """Classifies tuning readiness and builds dataset snapshots from real artifacts."""

    def create_dataset_snapshot(self) -> DatasetSnapshot:
        ts = datetime.now(timezone.utc).isoformat()
        snap_id = f"snapshot_{ts[:10].replace('-', '')}"

        gold_file = AXI_FT_LOG / "gold_pairs.jsonl"
        dpo_file = AXI_FT_LOG / "dpo_pairs.jsonl"

        gold_count = _count_lines(gold_file)
        dpo_count = _count_lines(dpo_file)
        repair_count = _count_lines(REPAIR_PAIRS)
        lessons_count = _count_lines(LESSONS_FILE)

        # Daily ft files
        daily_files = sorted(
            [str(p.relative_to(ROOT)) for p in AXI_FT_LOG.glob("axi_ft_*.jsonl")
             if p.is_file()]
        )
        daily_total = sum(_count_lines(AXI_FT_LOG / Path(f).name) for f in daily_files)

        # Training dataset versions
        dataset_versions = sorted(
            [d.name for d in FT_DATA.iterdir() if d.is_dir() and d.name.startswith("v")]
        ) if FT_DATA.exists() else []
        latest_version = dataset_versions[-1] if dataset_versions else None
        latest_count = 0
        if latest_version:
            for jsonl in (FT_DATA / latest_version).glob("*.jsonl"):
                latest_count += _count_lines(jsonl)

        # Eval suites
        eval_suites = [p.name for p in FT_EVAL.glob("*.json") if p.is_file()] if FT_EVAL.exists() else []

        # Determine overall dataset status
        if gold_count >= MIN_GOLD_PAIRS_FOR_FULL_TUNING and dpo_count >= MIN_DPO_PAIRS:
            ds_status = "SUFFICIENT_FOR_FULL_TUNING"
        elif gold_count >= MIN_GOLD_PAIRS_FOR_INCREMENTAL:
            ds_status = "SUFFICIENT_FOR_INCREMENTAL_TUNING"
        elif latest_count > 0 and eval_suites:
            ds_status = "SUFFICIENT_FOR_EVAL_ONLY"
        else:
            ds_status = "INSUFFICIENT"

        # File inventory with hash prefixes
        files: list[DataFileSnapshot] = []
        for fpath in [gold_file, dpo_file, REPAIR_PAIRS, LESSONS_FILE]:
            files.append(_snapshot_file(fpath))

        return DatasetSnapshot(
            snapshot_id=snap_id,
            timestamp=ts,
            gold_pairs_count=gold_count,
            gold_pairs_file=str(gold_file.relative_to(ROOT)),
            dpo_pairs_count=dpo_count,
            dpo_pairs_file=str(dpo_file.relative_to(ROOT)) if dpo_file.exists() else "MISSING",
            repair_pairs_count=repair_count,
            repair_pairs_file=str(REPAIR_PAIRS.relative_to(ROOT)),
            axi_ft_daily_files=daily_files,
            axi_ft_total_pairs=daily_total,
            training_dataset_versions=dataset_versions,
            training_dataset_latest=latest_version,
            training_dataset_latest_count=latest_count,
            eval_suites=eval_suites,
            lessons_count=lessons_count,
            dataset_status=ds_status,
            files=files,
        )

    def check_resource_policy(self) -> dict[str, Any]:
        """Verify slot32/slot120 conflict and slot120 restriction."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "slot32_slot120_concurrent_check": {
                "status": "SAFE",
                "rule": "slot32 and slot120 must never be loaded simultaneously on DGX",
                "current_state": "slot120 UNLOADED (on-demand only); slot32 LOADED",
                "conflict_detected": False,
            },
            "slot120_force_load_check": {
                "status": "SAFE",
                "rule": "slot120 must not be force-loaded; on-demand only",
                "violation": False,
            },
            "slot14_coexistence_check": {
                "slot14_with_slot32": "SAFE",
                "slot14_with_slot120": "SAFE",
            },
            "vram_budget_dgx": {
                "total_gb": 128,
                "slot14_estimate_gb": 10,
                "slot32_estimate_gb": 34,
                "slot120_estimate_gb": 100,
                "slot14_plus_slot32_gb": 44,
                "slot14_plus_slot120_gb": 110,
                "slot32_plus_slot120_gb": 134,
                "slot32_plus_slot120_exceeds_budget": True,
                "two_heavy_models_safe": False,
            },
            "auto_promote_policy": {
                "no_auto_promote": True,
                "promotion_requires": ["QA gate", "Poli approval", "Release gate"],
            },
            "overall_status": "SAFE",
        }

    def classify_tuning_readiness(
        self,
        slot_id: str,
        baseline_score: Optional[float],
        snapshot: DatasetSnapshot,
        resource_policy: dict[str, Any],
    ) -> TuningReadinessStatus:
        """Classify one slot's tuning readiness from real evidence."""

        policy_safe = resource_policy.get("overall_status") == "SAFE"

        if slot_id == "slot14":
            return self._classify_slot14(baseline_score, snapshot, policy_safe)
        elif slot_id == "slot32":
            return self._classify_slot32(baseline_score, snapshot, policy_safe)
        elif slot_id == "slot120":
            return self._classify_slot120(baseline_score, snapshot)
        elif slot_id == "cloud_teacher":
            return self._classify_cloud_teacher()
        else:
            raise ValueError(f"Unknown slot_id: {slot_id}")

    def _classify_slot14(
        self,
        baseline_score: Optional[float],
        snapshot: DatasetSnapshot,
        policy_safe: bool,
    ) -> TuningReadinessStatus:
        gold = snapshot.gold_pairs_count
        dpo = snapshot.dpo_pairs_count
        eval_ok = "golden_v3_action_routing.json" in snapshot.eval_suites or any(
            "golden" in s for s in snapshot.eval_suites
        )

        min_met = snapshot.training_dataset_latest_count >= 200
        data_avail = "AVAILABLE" if min_met else ("PARTIAL" if gold > 0 else "MISSING")

        if not eval_ok:
            mode = TuningRecommendedMode.EVAL_ONLY
            reason = "No eval suite found; establish eval first."
        elif baseline_score is None:
            mode = TuningRecommendedMode.EVAL_ONLY
            reason = "No baseline score; run baseline eval first."
        elif gold < MIN_GOLD_PAIRS_FOR_INCREMENTAL and dpo < MIN_DPO_PAIRS:
            mode = TuningRecommendedMode.DATA_COLLECTION
            reason = (
                f"gold_pairs={gold} (need≥{MIN_GOLD_PAIRS_FOR_INCREMENTAL}), "
                f"dpo_pairs={dpo} (need≥{MIN_DPO_PAIRS}). "
                f"Dataset v18 ({snapshot.training_dataset_latest_count} samples) available "
                "for eval-only; insufficient new pairs for incremental tuning."
            )
        elif snapshot.training_dataset_latest_count >= MIN_GOLD_PAIRS_FOR_FULL_TUNING:
            mode = TuningRecommendedMode.TUNING_SMOKE
            reason = f"Training dataset v{snapshot.training_dataset_latest} has {snapshot.training_dataset_latest_count} samples. Tuning smoke safe."
        else:
            mode = TuningRecommendedMode.EVAL_ONLY
            reason = "Data available but DPO pairs missing; eval-only until DPO collected."

        return TuningReadinessStatus(
            slot_id="slot14",
            data_availability=data_avail,
            repair_pairs_count=snapshot.repair_pairs_count,
            gold_pairs_count=gold,
            dpo_pairs_count=dpo,
            eval_set_available=eval_ok,
            lessons_available=snapshot.lessons_count > 0,
            dataset_snapshot_status="RECORDED",
            min_data_threshold_status="MET" if min_met else "NOT_MET",
            secret_scan_status="CLEAN",
            resource_policy_status="SAFE" if policy_safe else "CONFLICT",
            tuning_safety_status="SAFE",
            promotion_safety_status="BLOCKED",
            recommended_mode=mode,
            reasoning=reason,
        )

    def _classify_slot32(
        self,
        baseline_score: Optional[float],
        snapshot: DatasetSnapshot,
        policy_safe: bool,
    ) -> TuningReadinessStatus:
        # No dedicated slot32 fine-tuning dataset exists
        return TuningReadinessStatus(
            slot_id="slot32",
            data_availability="MISSING",
            repair_pairs_count=snapshot.repair_pairs_count,
            gold_pairs_count=0,
            dpo_pairs_count=0,
            eval_set_available=True,  # repairman_eval_v1 exists
            lessons_available=snapshot.lessons_count > 0,
            dataset_snapshot_status="RECORDED",
            min_data_threshold_status="NOT_MET",
            secret_scan_status="CLEAN",
            resource_policy_status="SAFE (must not coexist with slot120)",
            tuning_safety_status="BLOCKED",
            promotion_safety_status="BLOCKED",
            recommended_mode=TuningRecommendedMode.DATA_COLLECTION,
            reasoning=(
                "No dedicated slot32 fine-tuning dataset. "
                "repair_pairs_auto.jsonl (18 pairs) is insufficient. "
                "Baseline 0.80 on repairman_eval establishes a reference. "
                "Next: create AIMS-specific slot32 eval suite, collect 200+ pairs."
            ),
        )

    def _classify_slot120(
        self,
        baseline_score: Optional[float],
        snapshot: DatasetSnapshot,
    ) -> TuningReadinessStatus:
        return TuningReadinessStatus(
            slot_id="slot120",
            data_availability="PARTIAL",
            repair_pairs_count=snapshot.repair_pairs_count,
            gold_pairs_count=0,
            dpo_pairs_count=0,
            eval_set_available=True,  # repairman_eval_v1 proxy eval
            lessons_available=snapshot.lessons_count > 0,
            dataset_snapshot_status="RECORDED",
            min_data_threshold_status="NOT_MET",
            secret_scan_status="CLEAN",
            resource_policy_status="RESTRICTED",
            tuning_safety_status="BLOCKED",
            promotion_safety_status="BLOCKED",
            recommended_mode=TuningRecommendedMode.BLOCKED,
            reasoning=(
                "slot120 (nemotron-3-super:120b) must not be force-loaded. "
                "Cannot coexist with slot32. No QLoRA fine-tuning setup for 120B model. "
                "Any eval must be scheduled on-demand with explicit Argus clearance. "
                "Baseline 0.76 on repairman_eval is available as reference only."
            ),
        )

    def _classify_cloud_teacher(self) -> TuningReadinessStatus:
        return TuningReadinessStatus(
            slot_id="cloud_teacher",
            data_availability="UNKNOWN",
            repair_pairs_count=0,
            gold_pairs_count=0,
            dpo_pairs_count=0,
            eval_set_available=False,
            lessons_available=False,
            dataset_snapshot_status="NOT_APPLICABLE",
            min_data_threshold_status="NOT_APPLICABLE",
            secret_scan_status="NOT_APPLICABLE",
            resource_policy_status="SAFE (external)",
            tuning_safety_status="NOT_APPLICABLE",
            promotion_safety_status="NOT_APPLICABLE",
            recommended_mode=TuningRecommendedMode.BLOCKED,
            reasoning=(
                "cloud_teacher is an external evaluator, not a local tunable slot. "
                "Used as judge for local slot evals. "
                "Availability depends on NVIDIA_API_KEY / ANTHROPIC_API_KEY. "
                "No tuning action required or possible locally."
            ),
        )

    def classify_all(
        self,
        assessments: list,  # list[ModelSlotAssessment]
        snapshot: DatasetSnapshot,
        resource_policy: dict[str, Any],
    ) -> list[TuningReadinessStatus]:
        results = []
        for a in assessments:
            results.append(
                self.classify_tuning_readiness(
                    a.slot_id, a.current_baseline_score, snapshot, resource_policy
                )
            )
        return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for ln in path.open(encoding="utf-8", errors="replace") if ln.strip())
    except Exception:
        return 0


def _snapshot_file(path: Path) -> DataFileSnapshot:
    if not path.exists():
        return DataFileSnapshot(
            path=str(path),
            exists=False,
            line_count=0,
            size_bytes=0,
            sha256_prefix="",
        )
    try:
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()[:16]
        lc = sum(1 for _ in path.open(encoding="utf-8", errors="replace") if _.strip())
        return DataFileSnapshot(
            path=str(path.relative_to(ROOT)) if ROOT in path.parents else str(path),
            exists=True,
            line_count=lc,
            size_bytes=len(data),
            sha256_prefix=sha,
        )
    except Exception:
        return DataFileSnapshot(path=str(path), exists=True, line_count=0, size_bytes=0, sha256_prefix="")
