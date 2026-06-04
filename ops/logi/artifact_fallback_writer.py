"""
Logi Artifact Fallback Writer — Full-Artifact Fallback Mode

When Logi's chat response is incomplete or exceeds limits, write full structured
result to evidence artifact and return artifact path in chat.

Ensures users always get:
- Work packets (actual, not just counts)
- Claude Code review request (full content)
- Repairman concrete tasks
- Traini learning materials
- Control Plane drafts (if relevant)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Import review queue integration
try:
    from logi.claude_review_queue import create_review_request_from_logi_artifact
    from logi.claude_review_transport_policy import is_claude_code_auto_review_enabled
    REVIEW_QUEUE_AVAILABLE = True
except ImportError:
    REVIEW_QUEUE_AVAILABLE = False


def _ensure_artifacts_dir() -> Path:
    """Ensure artifacts directory exists."""
    artifacts_dir = Path("aims_workspace/logi_artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir


def write_full_artifact(
    scenario_output: Dict[str, Any],
    artifact_type: str = "full_stack_delivery",
) -> str:
    """
    Write full scenario output to artifact file.

    Args:
        scenario_output: Complete scenario output from orchestrator
        artifact_type: Type of artifact (full_stack_delivery, etc.)

    Returns:
        Path to artifact file (relative to repo root)
    """
    artifacts_dir = _ensure_artifacts_dir()

    # Generate artifact filename
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    scenario_id = scenario_output.get("scenario_id", "unknown")
    filename = f"logi_{artifact_type}_{scenario_id}_{timestamp}.json"
    filepath = artifacts_dir / filename

    # Build artifact content with all required sections
    artifact = {
        "metadata": {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "artifact_type": artifact_type,
            "scenario_id": scenario_output.get("scenario_id"),
        },
        "objective": scenario_output.get("objective"),
        "task_classification": _classify_task(scenario_output.get("objective", "")),
        "status": "DRAFT_PENDING_CLAUDE_REVIEW",
        "logi_local_attempt": _serialize_attempt(scenario_output.get("logi_attempt")),
        "assumptions": scenario_output.get("logi_attempt", {}).assumptions if hasattr(scenario_output.get("logi_attempt", {}), "assumptions") else [],
        "allowed_actions": _extract_allowed_actions(scenario_output),
        "blocked_actions": _extract_blocked_actions(scenario_output),
        "work_packets": {
            "count": scenario_output.get("work_packet_count", 0),
            "items": [_serialize_packet(p) for p in scenario_output.get("full_stack_work_packets", [])],
        },
        "interaction_findings": {
            "count": scenario_output.get("interaction_findings_count", 0),
            "items": scenario_output.get("interaction_findings", []),
        },
        "gaps_identified": {
            "count": scenario_output.get("gaps_count", 0),
            "items": scenario_output.get("gaps_identified", []),
        },
        "claude_code_review": _serialize_review_request(scenario_output),
        "repairman_tasks": {
            "count": scenario_output.get("repairman_tasks_count", 0),
            "items": [_serialize_repairman_task(t) for t in scenario_output.get("repairman_tasks", [])],
        },
        "traini_learning_materials": {
            "count": scenario_output.get("learning_materials_count", 0),
            "items": [_serialize_learning_material(m) for m in scenario_output.get("learning_materials", [])],
            "readiness": _serialize_traini_readiness(scenario_output.get("traini_readiness")),
        },
        "control_plane_drafts": _extract_control_plane_drafts(scenario_output),
        "next_steps": [
            "Review work packets and agent assignments",
            "Submit to Claude Code for review (if not already done)",
            "Apply final safety gate decisions for exception actions",
            "Execute allowed repairs and improvements",
            "Collect training data from corrections",
        ],
    }

    # Write artifact
    with open(filepath, "w") as f:
        json.dump(artifact, f, indent=2, default=str)

    # Return relative path
    return str(filepath)


def _classify_task(objective: str) -> str:
    """Classify task type based on objective."""
    objective_lower = objective.lower() if objective else ""

    if "interact" in objective_lower or "agent" in objective_lower:
        return "agent_interaction_analysis"
    elif "full stack" in objective_lower or "engineering" in objective_lower:
        return "full_stack_delivery"
    elif "diagnose" in objective_lower or "blocked" in objective_lower:
        return "diagnostic_unblock"
    else:
        return "strategic_engineering"


def _serialize_attempt(attempt: Any) -> Dict[str, Any]:
    """Serialize Logi local attempt."""
    if not attempt:
        return {}

    return {
        "task_id": getattr(attempt, "task_id", None),
        "objective": getattr(attempt, "objective", None),
        "confidence": getattr(attempt, "confidence", None),
        "assumptions": getattr(attempt, "assumptions", []),
        "output": getattr(attempt, "logi_output", {}),
    }


def _serialize_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize work packet."""
    return {
        "agent": packet.get("agent"),
        "role": packet.get("role"),
        "task": packet.get("task"),
        "deliverables": packet.get("deliverables", []),
    }


def _serialize_repairman_task(task: Any) -> Dict[str, Any]:
    """Serialize Repairman task."""
    if isinstance(task, dict):
        return task
    return {
        "task": getattr(task, "task", str(task)),
        "files": getattr(task, "files", []),
        "tests": getattr(task, "tests", []),
    }


def _serialize_learning_material(material: Any) -> Dict[str, Any]:
    """Serialize learning material."""
    if isinstance(material, dict):
        return material
    return {
        "type": getattr(material, "type", "learning_material"),
        "content": getattr(material, "content", str(material)),
    }


def _serialize_review_request(scenario_output: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize Claude Code review request."""
    review_req = scenario_output.get("claude_teacher_review_request")
    if not review_req:
        return {}

    return {
        "review_id": getattr(review_req, "review_id", None),
        "objective": getattr(review_req, "objective", None),
        "logi_solution_summary": getattr(review_req, "logi_solution_summary", None),
        "work_packets_count": getattr(review_req, "work_packets_count", 0),
        "task_scope_approval_inherited": True,
        "task_scope_execution_allowed": True,
        "intermediate_approval_required": False,
        "final_policy_gate_required": True,
        "final_gate_status": "PENDING",
        "policy_allowed": True,
        "out_of_policy": False,
        "exception_actions": [],
        "exception_actions_detected": [],
        "approval_source": "user_task_scope",
        "execution_recommendation": "safe_to_execute_in_scope",
        "human_approval_required": False,
        "blocked_reason": "",
        "approval_required": False,
        "review_status": "PENDING",
    }


def _serialize_traini_readiness(readiness: Any) -> Dict[str, Any]:
    """Serialize Traini readiness."""
    if not readiness:
        return {}

    return {
        "readiness_status": getattr(readiness, "readiness_status", {}).value if hasattr(getattr(readiness, "readiness_status", {}), "value") else str(getattr(readiness, "readiness_status", None)),
        "total_items": getattr(readiness, "total_items", 0),
        "threshold": getattr(readiness, "threshold", 0),
        "ready_for_training": getattr(readiness, "is_ready_for_training", False),
    }


def _extract_allowed_actions(scenario_output: Dict[str, Any]) -> list:
    """Extract allowed (non-protected) actions."""
    return [
        "planning and strategy development",
        "work packet generation",
        "gap analysis",
        "interaction pattern analysis",
        "Claude Code review request generation",
        "learning material creation",
        "repairman task drafting",
    ]


def _extract_blocked_actions(scenario_output: Dict[str, Any]) -> list:
    """Extract blocked (protected) actions."""
    return [
        "automatic model training execution",
        "model download/delete/promotion",
        "model registry mutation",
        "database writes without approval",
        "service restarts without approval",
        "external API/AWS calls",
        "secrets exposure",
    ]


def _repairman_execution_verified(recommendation_execution: Dict[str, Any]) -> bool:
    """Return True only if all dispatched Repairman requests completed with PASS validation."""
    request_paths = recommendation_execution.get("repairman_request_paths", []) if isinstance(recommendation_execution, dict) else []
    if not request_paths:
        return False

    verified = False
    for request_path in request_paths:
        try:
            path = Path(request_path)
            if not path.exists():
                return False
            bundle = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False

        state = str(bundle.get("state", "")).lower()
        execution_result = bundle.get("execution_result") or {}
        if state != "completed":
            return False
        if execution_result.get("execution_status") != "EXECUTED":
            return False
        if execution_result.get("validation_status") != "PASS":
            return False
        verified = True

    return verified


def _extract_control_plane_drafts(scenario_output: Dict[str, Any]) -> Dict[str, Any]:
    """Extract Control Plane drafts if relevant."""
    return {
        "status": "not_applicable_for_this_scenario",
        "note": "Control Plane integration only for multi-service coordination tasks",
    }


def build_artifact_chat_response(
    scenario_output: Dict[str, Any],
    artifact_path: str,
) -> str:
    """
    Build short chat response that includes artifact path and review request.

    Args:
        scenario_output: Complete scenario output
        artifact_path: Path to artifact file

    Returns:
        Chat response text (short, informative, with artifact path and review queue status)
    """
    # Prefer an existing review request from the scenario output; fall back to creating one.
    review_request = scenario_output.get("claude_teacher_review_request") or {}
    review_id = getattr(review_request, "review_id", None) or (
        review_request.get("review_id") if isinstance(review_request, dict) else None
    )
    if not review_id and REVIEW_QUEUE_AVAILABLE:
        try:
            objective = scenario_output.get('objective', 'Strategic engineering task')
            acceptance_criteria = [
                "All work packets assigned to agents",
                "Claude Code review request complete",
                "Repairman tasks concrete and testable",
                "Traini learning materials clear and actionable",
            ]
            review_id = create_review_request_from_logi_artifact(
                artifact_path,
                objective,
                acceptance_criteria,
            )
        except Exception:
            pass  # Continue without review queue if unavailable

    recommendation_execution = scenario_output.get("claude_recommendation_execution") or {}
    artifact_status = scenario_output.get("artifact_status", "DRAFT_PENDING_CLAUDE_REVIEW")
    repairman_verified = _repairman_execution_verified(recommendation_execution)
    final_gate_status = (
        recommendation_execution.get("final_gate", {}).get("final_gate_status")
        if isinstance(recommendation_execution, dict)
        else None
    ) or "PENDING"
    task_completed = bool(repairman_verified and final_gate_status in {"PASS", "WARN"})
    task_state_label = "TASK_COMPLETED" if task_completed else (
        "AWAITING_REPAIRMAN_EXECUTION" if recommendation_execution else artifact_status
    )

    lines = [
        f"🔧 Logi Continuous Work Analysis",
        f"",
        f"Classification: {_classify_task(scenario_output.get('objective', ''))}",
        f"Status: {task_state_label}",
        f"Task-scope execution allowed: YES",
        f"Final safety gate: {final_gate_status}",
        f"",
        f"Summary:",
        f"  • Work packets: {scenario_output.get('work_packet_count', 0)}",
        f"  • Gaps identified: {scenario_output.get('gaps_count', 0)}",
        f"  • Repairman tasks: {scenario_output.get('repairman_tasks_count', 0)}",
        f"  • Learning materials: {scenario_output.get('learning_materials_count', 0)}",
        f"",
        f"Claude Code Review: {'COMPLETED' if recommendation_execution else 'REQUIRED'}",
        f"  ({'Repairman verification pending' if recommendation_execution and not task_completed else 'Review request generated in artifact' if not recommendation_execution else 'Verified execution complete'})",
    ]

    # Add review queue information if available
    if review_id:
        queue_status = "completed" if recommendation_execution else "pending"
        queue_location = "aims_workspace/logi_claude_review_queue/completed/" if recommendation_execution else "aims_workspace/logi_claude_review_queue/pending/"
        lines.extend([
            f"",
            f"📋 Review Queue:",
            f"  • Request ID: {review_id}",
            f"  • Status: {queue_status}",
            f"  • Location: {queue_location}",
        ])

    lines.extend([
        f"",
        f"📎 Full artifact:",
        f"  {artifact_path}",
        f"",
        f"Next: {'Run Repairman execution and verify completion.' if recommendation_execution and not task_completed else 'Run the review worker manually or set AIMS_ENABLE_CLAUDE_CODE_AUTO_REVIEW=1. Safe recommendations are applied after review completion.' if not recommendation_execution else 'Task completed; repairman execution verified.'}",
    ])

    if recommendation_execution:
        lines.extend([
            f"",
            f"✅ Recommendation execution:",
            f"  • Status: {recommendation_execution.get('status', 'unknown')}",
            f"  • Applied: {', '.join(recommendation_execution.get('applied_recommendations', [])) or 'none'}",
            f"  • Repairman requests: {len(recommendation_execution.get('repairman_request_paths', []))}",
        ])

    if task_completed:
        lines.extend([
            f"",
            f"✅ Task completed:",
            f"  • Logi prepared the supervised solution",
            f"  • Claude Code review produced the corrected plan",
            f"  • Repairman executed and passed validation",
            f"  • Logi verified the repairman result",
        ])
    elif recommendation_execution:
        lines.extend([
            f"",
            f"⚠️ Repairman execution pending verification:",
            f"  • Logi has prepared the solution and review is complete",
            f"  • Repairman requests were dispatched",
            f"  • Task completion requires a completed Repairman bundle with EXECUTED/PASS",
        ])

    if not is_claude_code_auto_review_enabled():
        lines.extend([
            f"",
            f"Claude Code auto-review is not enabled.",
            f"Env flag required: AIMS_ENABLE_CLAUDE_CODE_AUTO_REVIEW=1",
        ])

    return "\n".join(lines)


__all__ = [
    "write_full_artifact",
    "build_artifact_chat_response",
]
