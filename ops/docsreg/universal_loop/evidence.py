"""Evidence persistence and aggregation for loop execution."""
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ops.docsreg.universal_loop.result import UniversalLoopResult
from ops.docsreg.universal_loop.stage_result import StageResult, StageOutcome


def _json_default(obj: Any) -> Any:
    """JSON serializer for non-standard types."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class EvidenceStore:
    """Persist execution evidence with proper serialization."""

    @staticmethod
    def write_json(path: str, payload: Any) -> None:
        """Write JSON with automatic parent directory creation."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(payload, f, indent=2, default=_json_default)

    @staticmethod
    def create_stage_evidence(stage_result: StageResult) -> dict[str, Any]:
        """Convert StageResult to JSON-serializable dict."""
        return {
            "stage_name": stage_result.stage_name,
            "outcome": stage_result.outcome.value,
            "started_at": stage_result.started_at.isoformat(),
            "completed_at": stage_result.completed_at.isoformat(),
            "duration_seconds": stage_result.duration_seconds,
            "quality_before": stage_result.quality_before,
            "quality_after": stage_result.quality_after,
            "quality_delta": stage_result.quality_delta,
            "content_before_length": len(stage_result.content_before),
            "content_after_length": len(stage_result.content_after),
            "errors": stage_result.errors,
            "actions_taken": stage_result.actions_taken,
            "diagnostics": stage_result.diagnostics,
            "failure_detected": stage_result.failure_detected,
            "failure_class": stage_result.failure_class,
        }

    @staticmethod
    def create_loop_evidence_package(result: UniversalLoopResult) -> dict[str, Any]:
        """Aggregate all evidence from loop execution."""
        return {
            "document_id": result.document_id,
            "archetype_type": result.archetype_type,
            "terminal_state": result.terminal_state.value,
            "terminal_reason": result.terminal_reason,
            "started_at": result.started_at.isoformat(),
            "completed_at": result.completed_at.isoformat(),
            "duration_seconds": result.duration_seconds,
            "quality_initial": result.quality_initial,
            "quality_final": result.quality_final,
            "quality_delta": result.quality_delta,
            "iterations": result.iterations,
            "data_retention_rate": result.data_retention_rate,
            "data_loss_percentage": result.data_loss_percentage,
            "requires_operator_decision": result.requires_operator_decision,
            "failures": result.failures,
            "failure_classes": result.failure_classes,
            "actions_executed": result.actions_executed,
            "stage_results": [
                EvidenceStore.create_stage_evidence(sr) for sr in result.stage_results
            ],
            "evidence_package": result.evidence_package,
        }

    @staticmethod
    def detect_failure_class(error_message: str, error_type: str) -> str:
        """Classify failures based on message and type."""
        msg_lower = error_message.lower()
        type_lower = error_type.lower()

        if "timeout" in msg_lower or "timed out" in msg_lower:
            return "TIMEOUT"
        if "structure" in msg_lower or "format" in msg_lower:
            return "STRUCTURE"
        if "policy" in msg_lower or "violation" in msg_lower:
            return "POLICY_VIOLATION"
        if "quality" in msg_lower or "score" in msg_lower:
            return "QUALITY_GATE"
        if "memory" in msg_lower or "resource" in msg_lower or "exhausted" in msg_lower:
            return "RESOURCE_EXHAUSTION"
        if "plateau" in msg_lower or "convergence" in msg_lower:
            return "QUALITY_PLATEAU"
        if "data" in msg_lower and ("loss" in msg_lower or "retention" in msg_lower):
            return "DATA_PRESERVATION_FAILURE"
        return "UNKNOWN"
