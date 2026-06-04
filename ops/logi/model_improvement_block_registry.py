"""Logi — Model Improvement Block Registry.

Defines the Traini block model: each block represents a safe unit of
data/eval/tuning work requested by Logi, prepared by Traini, validated
by QA/Argus, and consumed by the next cycle.

No heavy training executes here. All blocks are plans or safe artifacts.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
BLOCKS_DIR = ROOT / "aims_workspace" / "model_improvement_loop" / "blocks"
DUBAI_TZ = timezone(timedelta(hours=4))


# ── Block type constants ──────────────────────────────────────────────────────

class BlockType:
    DATA_COLLECTION = "DATA_COLLECTION"
    DATA_GENERATION = "DATA_GENERATION"
    DATASET_SNAPSHOT = "DATASET_SNAPSHOT"
    EVAL_ONLY = "EVAL_ONLY"
    TUNING_SMOKE_CANDIDATE = "TUNING_SMOKE_CANDIDATE"
    FULL_TUNING_CANDIDATE = "FULL_TUNING_CANDIDATE"


class BlockReadiness:
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PREPARED = "PREPARED"
    VALIDATED = "VALIDATED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class BlockQualityStatus:
    CANDIDATE = "CANDIDATE"            # generated but not yet evaluated
    QA_PASS = "QA_PASS"               # passed QA gate
    QA_FAIL = "QA_FAIL"               # failed QA gate
    QA_PARTIAL = "QA_PARTIAL"         # partial pass
    ARGUS_SAFE = "ARGUS_SAFE"         # resource policy cleared
    ARGUS_BLOCKED = "ARGUS_BLOCKED"   # resource policy blocked


# ── Traini block model ────────────────────────────────────────────────────────

@dataclass
class TrainiBlock:
    block_id: str
    source_cycle_id: str
    slot_id: str
    block_type: str                 # BlockType constant
    requested_by: str               # "logi"
    owner_agent: str                # "traini"
    supporting_agents: list[str]    # ["argus", "qa", "poli"]
    input_artifacts: list[str]
    produced_artifacts: list[str]
    quality_status: str             # BlockQualityStatus
    readiness_status: str           # BlockReadiness
    resource_policy_status: str
    safe_for_next_cycle: bool
    next_recommended_action: str
    validation_result: Optional[dict[str, Any]]
    lessons_learned_ref: Optional[str]
    request_timestamp: str
    preparation_timestamp: Optional[str]
    validation_timestamp: Optional[str]
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Block factory / registry ──────────────────────────────────────────────────

class BlockRegistry:
    """Creates and manages Traini blocks across cycles."""

    def __init__(self, run_dir: Optional[Path] = None) -> None:
        self._dir = run_dir or BLOCKS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._blocks: dict[str, TrainiBlock] = {}

    def request_block(
        self,
        source_cycle_id: str,
        slot_id: str,
        block_type: str,
        input_artifacts: Optional[list[str]] = None,
        notes: str = "",
    ) -> TrainiBlock:
        block_id = f"blk_{slot_id}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        block = TrainiBlock(
            block_id=block_id,
            source_cycle_id=source_cycle_id,
            slot_id=slot_id,
            block_type=block_type,
            requested_by="logi",
            owner_agent="traini",
            supporting_agents=["argus", "qa"],
            input_artifacts=input_artifacts or [],
            produced_artifacts=[],
            quality_status=BlockQualityStatus.CANDIDATE,
            readiness_status=BlockReadiness.PENDING,
            resource_policy_status="PENDING",
            safe_for_next_cycle=False,
            next_recommended_action="PREPARE_BLOCK",
            validation_result=None,
            lessons_learned_ref=None,
            request_timestamp=now,
            preparation_timestamp=None,
            validation_timestamp=None,
            notes=notes,
        )
        self._blocks[block_id] = block
        self._save(block)
        return block

    def prepare_block(
        self,
        block: TrainiBlock,
        produced_artifacts: list[str],
        quality_status: str = BlockQualityStatus.CANDIDATE,
        notes: str = "",
    ) -> TrainiBlock:
        block.produced_artifacts = produced_artifacts
        block.quality_status = quality_status
        block.readiness_status = BlockReadiness.PREPARED
        block.preparation_timestamp = datetime.now(timezone.utc).isoformat()
        if notes:
            block.notes = (block.notes + " | " + notes).strip(" |")
        self._save(block)
        return block

    def validate_block(
        self,
        block: TrainiBlock,
        qa_result: str,          # "PASS" / "FAIL" / "PARTIAL"
        argus_result: str,       # "SAFE" / "BLOCKED"
        resource_policy_detail: str,
        validation_notes: str = "",
    ) -> TrainiBlock:
        now = datetime.now(timezone.utc).isoformat()
        passed = qa_result == "PASS" and argus_result == "SAFE"
        partial = qa_result in ("PASS", "PARTIAL") and argus_result == "SAFE"

        if passed:
            block.quality_status = BlockQualityStatus.QA_PASS
            block.readiness_status = BlockReadiness.VALIDATED
            block.safe_for_next_cycle = True
            block.next_recommended_action = "USE_AS_NEXT_CYCLE_INPUT"
        elif partial:
            block.quality_status = BlockQualityStatus.QA_PARTIAL
            block.readiness_status = BlockReadiness.VALIDATED
            block.safe_for_next_cycle = True
            block.next_recommended_action = "USE_WITH_CAUTION_AS_NEXT_CYCLE_INPUT"
        else:
            block.quality_status = BlockQualityStatus.QA_FAIL
            block.readiness_status = BlockReadiness.REJECTED
            block.safe_for_next_cycle = False
            block.next_recommended_action = "FIX_AND_RETRY"

        if argus_result == "SAFE":
            block.resource_policy_status = BlockQualityStatus.ARGUS_SAFE
        else:
            block.resource_policy_status = BlockQualityStatus.ARGUS_BLOCKED
            block.safe_for_next_cycle = False
            block.next_recommended_action = "WAIT_FOR_ARGUS_CLEARANCE"

        block.validation_result = {
            "qa_result": qa_result,
            "argus_result": argus_result,
            "resource_policy_detail": resource_policy_detail,
            "validation_notes": validation_notes,
            "timestamp": now,
        }
        block.validation_timestamp = now
        self._save(block)
        return block

    def accept_block(self, block: TrainiBlock) -> TrainiBlock:
        if block.safe_for_next_cycle:
            block.readiness_status = BlockReadiness.ACCEPTED
            self._save(block)
        return block

    def build_next_cycle_input(
        self,
        block: TrainiBlock,
        cycle_id: str,
        cycle_number: int,
    ) -> dict[str, Any]:
        """Convert a validated block into next_cycle_input."""
        return {
            "from_cycle": cycle_id,
            "from_block": block.block_id,
            "slot_id": block.slot_id,
            "cycle_number": cycle_number,
            "block_type": block.block_type,
            "block_readiness_status": block.readiness_status,
            "block_quality_status": block.quality_status,
            "safe_for_next_cycle": block.safe_for_next_cycle,
            "produced_artifacts": block.produced_artifacts,
            "input_artifacts": block.input_artifacts,
            "resource_policy_status": block.resource_policy_status,
            "validation_result": block.validation_result,
            "next_recommended_action": block.next_recommended_action,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def write_registry(self, output_dir: Optional[Path] = None) -> Path:
        out = output_dir or self._dir
        index = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "blocks": [b.to_dict() for b in self._blocks.values()],
        }
        path = out / "traini_block_registry.json"
        path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _save(self, block: TrainiBlock) -> None:
        path = self._dir / f"{block.block_id}.json"
        path.write_text(json.dumps(block.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def all_blocks(self) -> list[TrainiBlock]:
        return list(self._blocks.values())

    def get_block(self, block_id: str) -> Optional[TrainiBlock]:
        return self._blocks.get(block_id)
