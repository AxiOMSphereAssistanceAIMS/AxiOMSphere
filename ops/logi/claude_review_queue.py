"""
Logi ↔ Claude Code Teacher Review Queue

File-backed queue for automatic Logi → Claude Code teacher review requests.

Flow:
1. Logi creates artifact → creates review request → queue/pending
2. Review worker picks up → queue/in_progress
3. Claude Code reviews → queue/completed with result
4. Logi ingests result → artifact updated
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from logi.task_scope_approval_policy import (
    build_safe_task_scope_decision,
    build_blocked_out_of_policy_decision,
)
from logi.claude_review_transport_policy import get_claude_review_provider
try:
    from orchestrator_planning.final_policy_gate import evaluate_final_policy_gate
except ImportError:
    # Fallback if orchestrator_planning not available
    evaluate_final_policy_gate = None


def ensure_review_queue_dirs() -> Dict[str, Path]:
    """Ensure review queue directories exist."""
    base = Path("aims_workspace/logi_claude_review_queue")
    dirs = {
        "base": base,
        "pending": base / "pending",
        "in_progress": base / "in_progress",
        "completed": base / "completed",
        "failed": base / "failed",
        "executed": base / "executed",
    }

    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    return dirs


def create_review_request_from_logi_artifact(
    artifact_path: str,
    objective: str,
    acceptance_criteria: Optional[List[str]] = None,
) -> str:
    """
    Create a review request from a Logi artifact.

    Args:
        artifact_path: Path to Logi artifact (JSON)
        objective: What Logi was trying to accomplish
        acceptance_criteria: What constitutes a good solution

    Returns:
        Review request ID
    """
    dirs = ensure_review_queue_dirs()
    review_id = f"logi-review-{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"

    request = {
        "review_id": review_id,
        "source_agent": "logi",
        "source_artifact": artifact_path,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "objective": objective,
        "acceptance_criteria": acceptance_criteria or [],
        "status": "pending",
        "reviewer": "claude_code",
        "review_mode": get_claude_review_provider(),
        "review_provider": get_claude_review_provider(),
        "auto_execute": False,
        **build_safe_task_scope_decision(),
        "approval_required": False,
        "task_scope_execution_allowed": True,
        "intermediate_approval_required": False,
        "final_policy_gate_required": True,
        "final_gate_status": "PENDING",
        "exception_actions_detected": [],
        "allowed_actions": [
            "review",
            "correct",
            "produce_feedback",
            "identify_mistakes",
            "suggest_repairman_tasks",
            "suggest_traini_materials",
        ],
        "forbidden_actions": [
            "runtime_mutation",
            "training_execution",
            "model_registry_mutation",
            "model_promotion",
            "model_deletion",
            "model_download",
            "secret_exposure",
            "service_restart",
            "external_api_call",
            "aws_call",
        ],
        "expected_outputs": [
            "verdict",
            "corrected_plan",
            "mistakes_found",
            "repairman_tasks",
            "traini_learning_materials",
            "feedback_for_logi",
        ],
        "policy_decision": build_safe_task_scope_decision(),
    }

    # Write request to pending queue
    request_file = dirs["pending"] / f"{review_id}.json"
    with open(request_file, "w") as f:
        json.dump(request, f, indent=2, default=str)

    return review_id


def get_pending_review_request(review_id: str) -> Optional[Dict[str, Any]]:
    """Return a pending request by id if present."""
    dirs = ensure_review_queue_dirs()
    path = dirs["pending"] / f"{review_id}.json"
    if not path.exists():
        return None
    with open(path) as handle:
        return json.load(handle)


def list_pending_review_requests() -> List[Dict[str, Any]]:
    """Get all pending review requests."""
    dirs = ensure_review_queue_dirs()
    pending = []

    for file in sorted(dirs["pending"].glob("*.json")):
        with open(file) as f:
            pending.append(json.load(f))

    return pending


def mark_review_in_progress(review_id: str) -> None:
    """Move review request to in_progress."""
    dirs = ensure_review_queue_dirs()

    pending_file = dirs["pending"] / f"{review_id}.json"
    if not pending_file.exists():
        raise FileNotFoundError(f"Review request not found: {review_id}")

    in_progress_file = dirs["in_progress"] / f"{review_id}.json"

    # Load, update status, and move
    with open(pending_file) as f:
        request = json.load(f)

    request["status"] = "in_progress"
    request["started_at"] = datetime.utcnow().isoformat() + "Z"

    with open(in_progress_file, "w") as f:
        json.dump(request, f, indent=2, default=str)

    pending_file.unlink()


def write_review_result(review_result: Dict[str, Any]) -> str:
    """
    Write review result from Claude Code.

    Args:
        review_result: Dict with review_id, verdict, corrected_plan, etc.

    Returns:
        Path to result file
    """
    dirs = ensure_review_queue_dirs()
    review_id = review_result["review_id"]

    # Ensure result has required fields
    review_result.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
    review_result.setdefault("execution_allowed", False)
    review_result.setdefault("task_scope_approval_inherited", True)
    review_result.setdefault("policy_allowed", True)
    review_result.setdefault("out_of_policy", False)
    review_result.setdefault("exception_actions", [])
    review_result.setdefault("approval_source", "user_task_scope")
    review_result.setdefault("execution_recommendation", "safe_to_execute_in_scope")
    review_result.setdefault("human_approval_required", False)
    review_result.setdefault("blocked_reason", "")
    review_result.setdefault("approval_required", False)
    review_result.setdefault("requires_human_approval", False)
    review_result.setdefault("task_scope_execution_allowed", True)
    review_result.setdefault("intermediate_approval_required", False)
    review_result.setdefault("final_policy_gate_required", True)
    review_result.setdefault("final_gate_status", "PENDING")
    review_result.setdefault("exception_actions_detected", list(review_result.get("exception_actions", [])))

    result_file = dirs["completed"] / f"{review_id}.json"
    with open(result_file, "w") as f:
        json.dump(review_result, f, indent=2, default=str)

    return str(result_file)


def mark_review_completed(review_id: str, result_path: str) -> None:
    """Mark review as completed and move to completed."""
    dirs = ensure_review_queue_dirs()

    in_progress_file = dirs["in_progress"] / f"{review_id}.json"
    if not in_progress_file.exists():
        raise FileNotFoundError(f"In-progress review not found: {review_id}")

    # Result is already in completed dir, just remove in_progress
    in_progress_file.unlink()


def mark_review_failed(review_id: str, error_message: str) -> None:
    """Mark review as failed."""
    dirs = ensure_review_queue_dirs()

    in_progress_file = dirs["in_progress"] / f"{review_id}.json"
    if in_progress_file.exists():
        # Load and update
        with open(in_progress_file) as f:
            request = json.load(f)

        request["status"] = "failed"
        request["error_message"] = error_message
        request["failed_at"] = datetime.utcnow().isoformat() + "Z"

        failed_file = dirs["failed"] / f"{review_id}.json"
        with open(failed_file, "w") as f:
            json.dump(request, f, indent=2, default=str)

        in_progress_file.unlink()
    else:
        # Maybe it's in pending
        pending_file = dirs["pending"] / f"{review_id}.json"
        if pending_file.exists():
            with open(pending_file) as f:
                request = json.load(f)

            request["status"] = "failed"
            request["error_message"] = error_message
            request["failed_at"] = datetime.utcnow().isoformat() + "Z"

            failed_file = dirs["failed"] / f"{review_id}.json"
            with open(failed_file, "w") as f:
                json.dump(request, f, indent=2, default=str)

            pending_file.unlink()


def load_review_result(review_id: str) -> Optional[Dict[str, Any]]:
    """Load completed review result."""
    dirs = ensure_review_queue_dirs()

    result_file = dirs["completed"] / f"{review_id}.json"
    if result_file.exists():
        with open(result_file) as f:
            payload = json.load(f)
        execution = load_review_recommendation_execution(review_id)
        if execution:
            payload["recommendation_execution"] = execution
        return payload

    return None


def get_review_status(review_id: str) -> Optional[Dict[str, Any]]:
    """Return the current queue status and path for a review id."""
    dirs = ensure_review_queue_dirs()

    stages = {
        "pending": dirs["pending"] / f"{review_id}.json",
        "in_progress": dirs["in_progress"] / f"{review_id}.json",
        "completed": dirs["completed"] / f"{review_id}.json",
        "failed": dirs["failed"] / f"{review_id}.json",
    }

    for stage, path in stages.items():
        if not path.exists():
            continue

        status: Dict[str, Any] = {
            "review_id": review_id,
            "status": stage,
            "queue_path": str(path),
            "queue_dir": str(path.parent),
            "queue_stage": stage,
        }

        try:
            with open(path) as f:
                payload = json.load(f)
            status["request"] = payload
            if stage == "completed":
                status["result"] = payload
                status["verdict"] = payload.get("verdict")
                status["corrected_plan"] = payload.get("corrected_plan", {})
                status["feedback_for_logi"] = payload.get("feedback_for_logi", "")
                status["task_scope_execution_allowed"] = payload.get("task_scope_execution_allowed", True)
                status["intermediate_approval_required"] = payload.get("intermediate_approval_required", False)
                status["final_policy_gate_required"] = payload.get("final_policy_gate_required", True)
                status["final_gate_status"] = payload.get("final_gate_status", "PENDING")
                execution = load_review_recommendation_execution(review_id)
                if execution:
                    status["recommendation_execution"] = execution
        except Exception:
            pass

        return status

    return None


def write_review_recommendation_execution(
    review_id: str,
    execution: Dict[str, Any],
) -> str:
    """Write recommendation execution record for a completed review."""
    dirs = ensure_review_queue_dirs()
    execution = dict(execution)
    execution.setdefault("review_id", review_id)
    execution.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
    execution.setdefault("status", "applied")
    path = dirs["executed"] / f"{review_id}.json"
    with open(path, "w") as f:
        json.dump(execution, f, indent=2, default=str)
    return str(path)


def load_review_recommendation_execution(review_id: str) -> Optional[Dict[str, Any]]:
    """Load recommendation execution record if present."""
    dirs = ensure_review_queue_dirs()
    path = dirs["executed"] / f"{review_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def apply_review_recommendations(
    review_result: Dict[str, Any],
    artifact_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply safe recommendations after a completed Claude Code review.

    This does not execute protected actions. It materializes safe in-scope
    recommendations by updating the source artifact, recording the execution
    decision, and dispatching repairman follow-up requests for concrete fixes.
    """
    review_id = review_result.get("review_id")
    if not review_id:
        raise ValueError("review_result missing review_id")

    dirs = ensure_review_queue_dirs()
    existing = load_review_recommendation_execution(review_id)
    if existing:
        return existing

    resolved_artifact_path = artifact_path or review_result.get("source_artifact")
    verdict_value = review_result.get("verdict", "")
    verdict = str(getattr(verdict_value, "value", verdict_value)).strip().lower()
    policy_allowed = bool(review_result.get("policy_allowed", True))
    out_of_policy = bool(review_result.get("out_of_policy", False))
    execution_recommendation = str(review_result.get("execution_recommendation", "")).strip()
    task_scope_approval_inherited = bool(review_result.get("task_scope_approval_inherited", True))
    final_gate_status = str(review_result.get("final_gate_status", "PENDING")).upper()
    safe_to_apply = (
        verdict in {"accept", "accept_with_changes"}
        and policy_allowed
        and not out_of_policy
        and task_scope_approval_inherited
        and execution_recommendation in {"safe_to_execute_in_scope", "safe_to_execute_in_scope_after_review", ""}
        and final_gate_status != "FAIL"
    )

    execution: Dict[str, Any] = {
        "review_id": review_id,
        "source_artifact": resolved_artifact_path,
        "verdict": review_result.get("verdict"),
        "task_scope_approval_inherited": task_scope_approval_inherited,
        "task_scope_execution_allowed": bool(review_result.get("task_scope_execution_allowed", True)),
        "intermediate_approval_required": bool(review_result.get("intermediate_approval_required", False)),
        "final_policy_gate_required": bool(review_result.get("final_policy_gate_required", True)),
        "policy_allowed": policy_allowed,
        "out_of_policy": out_of_policy,
        "execution_recommendation": execution_recommendation or "safe_to_execute_in_scope",
        "final_gate_status": final_gate_status,
        "status": "applied" if safe_to_apply else "blocked_out_of_policy",
        "applied_recommendations": [],
        "blocked_recommendations": [],
        "repairman_request_paths": [],
        "traini_material_path": "",
        "artifact_updated": False,
    }

    if not safe_to_apply:
        if out_of_policy or not policy_allowed:
            execution["blocked_recommendations"] = list(review_result.get("exception_actions", []))
        execution_path = write_review_recommendation_execution(review_id, execution)
        execution["execution_path"] = execution_path
        return execution

    if resolved_artifact_path:
        try:
            ingest_review_result_into_logi_artifact(str(resolved_artifact_path), review_result)
            execution["artifact_updated"] = True
            execution["applied_recommendations"].append("ingest_review_result_into_logi_artifact")
        except Exception as exc:
            execution["blocked_recommendations"].append(f"artifact_update_failed: {exc}")

    # Dispatch repairman follow-up tasks as safe in-scope work packets.
    try:
        from repairman.agent_repair_client import submit_logi_request

        for index, task in enumerate(review_result.get("repairman_tasks", []), start=1):
            task_name = str(task.get("task", "")).strip() or f"claude_review_recommendation_{index}"
            request_path = submit_logi_request(
                task=task_name,
                mode="repair",
                source="claude_code_review_result",
                task_type="LOGI_CLAUDE_REVIEW_RECOMMENDATION",
                symptom_class="CLAUDE_REVIEW_CORRECTION",
                affected_component="ops/logi",
                impact="safe_in_scope_recommendation_dispatch",
                evidence_paths=[path for path in [resolved_artifact_path] if path],
                logs_excerpt=str(review_result.get("feedback_for_logi", ""))[:3500],
                rerun_command=[],
                success_criteria=[
                    "task_scope_approval_inherited",
                    "policy_allowed",
                    "validation_evidence_required",
                ],
                rollback_requirement="Re-run review ingestion and clear recommendation execution record if dispatch must be reverted.",
                allowed_actions=["WRITE_TEXT", "APPEND_TEXT", "RUN_COMMAND"],
                forbidden_actions=[
                    "DELETE_PATH",
                    "RM_RF",
                    "RESTART_SERVICE",
                    "LOAD_MODEL",
                    "UNLOAD_MODEL",
                    "EDIT_ENV",
                    "READ_SECRET",
                    "READ_RAW_CLAUDE_MEM",
                    "TRAIN_MODEL",
                    "USE_SLOT120_AS_JUDGE",
                ],
            )
            execution["repairman_request_paths"].append(request_path)
        if execution["repairman_request_paths"]:
            execution["applied_recommendations"].append("repairman_follow_up_requests_dispatched")
    except Exception as exc:
        execution["blocked_recommendations"].append(f"repairman_dispatch_failed: {exc}")

    traini_materials = review_result.get("traini_learning_materials") or []
    if traini_materials:
        traini_dir = dirs["executed"] / "traini_materials"
        traini_dir.mkdir(parents=True, exist_ok=True)
        traini_path = traini_dir / f"{review_id}.json"
        traini_payload = {
            "review_id": review_id,
            "source_artifact": resolved_artifact_path,
            "materials": traini_materials,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "training_execution_allowed": False,
        }
        with open(traini_path, "w") as f:
            json.dump(traini_payload, f, indent=2, default=str)
        execution["traini_material_path"] = str(traini_path)
        execution["applied_recommendations"].append("traini_learning_materials_recorded")

    execution_path = write_review_recommendation_execution(review_id, execution)
    execution["execution_path"] = execution_path

    if resolved_artifact_path and Path(resolved_artifact_path).exists():
        try:
            with open(resolved_artifact_path) as f:
                artifact = json.load(f)
            artifact["claude_code_recommendation_execution"] = {
                "review_id": review_id,
                "status": execution["status"],
                "execution_path": execution_path,
                "repairman_request_paths": execution["repairman_request_paths"],
                "traini_material_path": execution["traini_material_path"],
                "applied_recommendations": execution["applied_recommendations"],
                "blocked_recommendations": execution["blocked_recommendations"],
                "final_gate_status": execution["final_gate_status"],
            }
            with open(resolved_artifact_path, "w") as f:
                json.dump(artifact, f, indent=2, default=str)
        except Exception as exc:
            execution["blocked_recommendations"].append(f"artifact_execution_write_failed: {exc}")

    final_gate = evaluate_final_policy_gate(
        scope_compliant=bool(task_scope_approval_inherited and policy_allowed and not out_of_policy),
        reversible=bool(
            review_result.get("rollback_plan")
            or review_result.get("rollback_requirement")
            or review_result.get("rollback_path_present", False)
        ),
        rollback_path_present=bool(review_result.get("rollback_plan") or review_result.get("rollback_requirement") or resolved_artifact_path),
        tests_passed=str(review_result.get("verdict", "")).lower() in {"accept", "accept_with_changes"},
        evidence_package_exists=bool(resolved_artifact_path and Path(resolved_artifact_path).exists()),
        no_secrets_exposed=not bool(review_result.get("secrets_exposed", False)),
        exception_actions_detected=list(review_result.get("exception_actions_detected", review_result.get("exception_actions", []))),
        no_destructive_action_out_of_scope=not bool(review_result.get("destructive_action_out_of_scope", False)),
        no_model_mutation_out_of_scope=not bool(review_result.get("model_mutation_out_of_scope", False)),
        no_training_out_of_scope=not bool(review_result.get("training_out_of_scope", False)),
        no_external_calls_out_of_scope=not bool(review_result.get("external_calls_out_of_scope", False)),
    )
    execution["final_gate_status"] = final_gate["final_gate_status"]
    execution["final_gate"] = final_gate
    if final_gate["final_gate_status"] != "PASS":
        execution["blocked_recommendations"].append(f"final_gate:{final_gate['final_gate_status']}")

    if execution["blocked_recommendations"]:
        execution["status"] = "applied_with_warnings"

    execution_path = write_review_recommendation_execution(review_id, execution)
    execution["execution_path"] = execution_path
    return execution


def ingest_review_result_into_logi_artifact(
    artifact_path: str,
    review_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update Logi artifact with review result.

    Args:
        artifact_path: Path to Logi artifact
        review_result: Result from Claude Code review

    Returns:
        Updated artifact dict
    """
    # Load artifact
    with open(artifact_path) as f:
        artifact = json.load(f)

    # Ingest review result
    artifact["claude_code_review_result"] = {
        "review_id": review_result.get("review_id"),
        "verdict": review_result.get("verdict"),
        "created_at": review_result.get("created_at"),
        "task_scope_approval_inherited": review_result.get("task_scope_approval_inherited", True),
        "policy_allowed": review_result.get("policy_allowed", True),
        "out_of_policy": review_result.get("out_of_policy", False),
        "execution_recommendation": review_result.get("execution_recommendation", "safe_to_execute_in_scope"),
        "task_scope_execution_allowed": review_result.get("task_scope_execution_allowed", True),
        "intermediate_approval_required": review_result.get("intermediate_approval_required", False),
        "final_policy_gate_required": review_result.get("final_policy_gate_required", True),
        "final_gate_status": review_result.get("final_gate_status", "PENDING"),
    }

    # Update status if there are corrections
    if review_result.get("verdict") in ("accept_with_changes", "needs_revision"):
        artifact["status"] = "CLAUDE_REVIEW_COMPLETE_WITH_CORRECTIONS"
        artifact["corrected_plan"] = review_result.get("corrected_plan", {})
        artifact["mistakes_found"] = review_result.get("mistakes_found", [])
        artifact["feedback_from_claude"] = review_result.get("feedback_for_logi", "")
    else:
        artifact["status"] = "CLAUDE_REVIEW_COMPLETE"

    # Add Repairman tasks and Traini materials if present
    if review_result.get("repairman_tasks"):
        artifact["repairman_tasks_from_review"] = review_result["repairman_tasks"]

    if review_result.get("traini_learning_materials"):
        artifact["traini_learning_materials_from_review"] = (
            review_result["traini_learning_materials"]
        )

    # Write updated artifact
    with open(artifact_path, "w") as f:
        json.dump(artifact, f, indent=2, default=str)

    return artifact


def get_queue_status() -> Dict[str, int]:
    """Get counts of requests in each queue."""
    dirs = ensure_review_queue_dirs()

    return {
        "pending": len(list(dirs["pending"].glob("*.json"))),
        "in_progress": len(list(dirs["in_progress"].glob("*.json"))),
        "completed": len(list(dirs["completed"].glob("*.json"))),
        "failed": len(list(dirs["failed"].glob("*.json"))),
    }


__all__ = [
    "ensure_review_queue_dirs",
    "create_review_request_from_logi_artifact",
    "get_pending_review_request",
    "list_pending_review_requests",
    "mark_review_in_progress",
    "write_review_result",
    "mark_review_completed",
    "mark_review_failed",
    "load_review_result",
    "get_review_status",
    "write_review_recommendation_execution",
    "load_review_recommendation_execution",
    "apply_review_recommendations",
    "ingest_review_result_into_logi_artifact",
    "get_queue_status",
]
