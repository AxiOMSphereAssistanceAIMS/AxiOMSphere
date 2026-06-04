"""
Claude Code Teacher Review Worker

Processes review requests from the queue.
Supports simulation mode and optional real Claude Code CLI call.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional

from logi.claude_review_queue import (
    list_pending_review_requests,
    get_pending_review_request,
    mark_review_in_progress,
    write_review_result,
    mark_review_completed,
    mark_review_failed,
    load_review_result,
    apply_review_recommendations,
)
from logi.task_scope_approval_policy import (
    build_safe_task_scope_decision,
    build_blocked_out_of_policy_decision,
)
from logi.claude_review_transport_policy import (
    is_claude_code_auto_review_enabled,
    CLAUDE_CODE_AUTO_REVIEW_ENV,
    get_claude_review_provider,
)
from logi.claude_review_bedrock_backend import invoke_real_claude_review, build_bedrock_review_ledger_sample

# Phase 1 Skill: teaching-patterns
try:
    from ops.ecc_skills.phase_1_teaching.teaching_patterns import TeachingPatterns
    ECC_TEACHING_PATTERNS_AVAILABLE = True
except ImportError:
    ECC_TEACHING_PATTERNS_AVAILABLE = False

_teaching_patterns = None

def _init_teaching_patterns() -> None:
    """Initialize Phase 1 teaching-patterns skill."""
    global _teaching_patterns
    if ECC_TEACHING_PATTERNS_AVAILABLE:
        try:
            _teaching_patterns = TeachingPatterns()
        except Exception:
            _teaching_patterns = None


def build_claude_code_review_prompt(
    artifact_path: str,
    objective: str,
    acceptance_criteria: list,
) -> str:
    """Build review prompt for Claude Code."""
    # Load artifact for content
    try:
        with open(artifact_path) as f:
            artifact = json.load(f)
        artifact_summary = f"Artifact: {json.dumps(artifact, indent=2)[:1000]}..."
    except Exception:
        artifact_summary = f"Artifact file: {artifact_path}"

    prompt = f"""You are Claude Code acting as a teacher/reviewer/corrector for Logi.

Review this Logi artifact for quality and correctness.

Artifact path: {artifact_path}

Objective: {objective}

Acceptance criteria:
{chr(10).join(f"- {c}" for c in acceptance_criteria)}

{artifact_summary}

Your tasks:

1. Verify Logi understood the objective correctly.
2. Identify any mistakes, missing work packets, unsafe assumptions, weak routing, or missing evidence.
3. Correct the plan based on the identified issues.
4. Produce concrete Repairman tasks for code/config/test repairs.
5. Produce Traini learning materials for identified reasoning/planning/classification failures.
6. Report final safety gate outcome at the end of the task.
7. Do NOT execute runtime changes.
8. Do NOT start training.
9. Do NOT modify model registry.
10. Do NOT expose secrets.

Return a strict JSON object:
{{
  "verdict": "accept|accept_with_changes|reject|needs_context",
  "corrected_plan": {{}},
  "mistakes_found": ["mistake1", "mistake2"],
  "repairman_tasks": [{{"task": "...", "files": [], "tests": []}}],
  "traini_learning_materials": ["material1", "material2"],
  "feedback_for_logi": "Detailed feedback on what Logi did well and what to improve.",
  "task_scope_approval_inherited": true,
  "task_scope_execution_allowed": true,
  "intermediate_approval_required": false,
  "final_policy_gate_required": true,
  "final_gate_status": "PENDING",
  "policy_allowed": true,
  "out_of_policy": false,
  "exception_actions": [],
  "exception_actions_detected": [],
  "approval_source": "user_task_scope",
  "execution_recommendation": "safe_to_execute_in_scope",
  "human_approval_required": false,
  "blocked_reason": "",
  "requires_human_approval": false,
  "execution_allowed": false,
  "task_scope_execution_allowed": true,
  "intermediate_approval_required": false,
  "final_policy_gate_required": true,
  "final_gate_status": "PENDING",
  "exception_actions_detected": []
}}

Return ONLY the JSON, no other text."""

    return prompt


def simulate_claude_code_review_for_smoke(
    artifact_path: str,
    objective: str,
) -> Dict[str, Any]:
    """
    Simulate a Claude Code review for testing.

    Used in smoke tests and when real Claude Code CLI is disabled.
    """
    # Load artifact
    try:
        with open(artifact_path) as f:
            artifact = json.load(f)
    except Exception:
        artifact = {}

    # Generate simulated review
    review = {
        "verdict": "accept_with_changes",
        "corrected_plan": artifact.get("logi_local_attempt", {}),
        "mistakes_found": [
            "Missing error handling in work packet routing",
            "Incomplete approval chain specification",
            "Insufficient context for Traini materials",
        ],
        "repairman_tasks": [
            {
                "task": "Implement error handling in packet routing",
                "files": ["ops/logi/conversational_orchestrator.py"],
                "tests": ["test_error_handling"],
            },
            {
                "task": "Add approval chain validation",
                "files": ["ops/logi/claude_code_cli_gate.py"],
                "tests": ["test_approval_chain"],
            },
        ],
        "traini_learning_materials": [
            "Error handling patterns for orchestration",
            "Multi-stage approval chain design",
            "Incomplete information handling",
        ],
        "feedback_for_logi": (
            "Good overall structure and understanding of the objective. "
            "Main improvements needed: add error handling to packet routing, "
            "specify complete approval chain, ensure Traini materials are contextual. "
            "See repairman tasks for concrete fixes."
        ),
        **build_safe_task_scope_decision(),
        "task_scope_execution_allowed": True,
        "intermediate_approval_required": False,
        "final_policy_gate_required": True,
        "final_gate_status": "PENDING",
        "approval_required": False,
        "requires_human_approval": False,
        "exception_actions_detected": [],
        "execution_allowed": False,
    }

    return review


def _build_real_review_metadata(
    review: Dict[str, Any],
    *,
    review_id: str,
    review_mode: str,
    source_artifact: str,
) -> Dict[str, Any]:
    """Normalize real/simulated review metadata."""
    review.setdefault("review_id", review_id)
    review.setdefault("source_artifact", source_artifact)
    review.setdefault("review_mode", review_mode)
    review.setdefault("provider", review_mode)
    review.setdefault("claude_code_called", review.get("claude_code_called", False))
    review.setdefault("simulation_used", review.get("simulation_used", False))
    review.setdefault("command_redacted", [])
    review.setdefault("stdout_excerpt", "")
    review.setdefault("stderr_excerpt", "")
    review.setdefault("model_requested", "")
    review.setdefault("model_effective", "")
    review.setdefault("aws_profile", os.environ.get("AWS_PROFILE", ""))
    review.setdefault("aws_region", os.environ.get("AWS_REGION", ""))
    review.setdefault("bedrock_enabled", os.environ.get("CLAUDE_CODE_USE_BEDROCK", "").lower() in ("1", "true", "yes"))
    review.setdefault("execution_allowed", False)
    review.setdefault("task_scope_approval_inherited", True)
    review.setdefault("task_scope_execution_allowed", True)
    review.setdefault("intermediate_approval_required", False)
    review.setdefault("final_policy_gate_required", True)
    review.setdefault("final_gate_status", "PENDING")
    review.setdefault("policy_allowed", True)
    review.setdefault("out_of_policy", False)
    review.setdefault("exception_actions", [])
    review.setdefault("exception_actions_detected", list(review.get("exception_actions", [])))
    review.setdefault("approval_source", "user_task_scope")
    review.setdefault("execution_recommendation", "safe_to_execute_in_scope")
    review.setdefault("human_approval_required", False)
    review.setdefault("blocked_reason", "")
    review.setdefault("requires_human_approval", False)
    return review


def optionally_call_claude_code_cli_if_enabled(
    artifact_path: str,
    objective: str,
    acceptance_criteria: list,
    *,
    review_id: str,
    review_mode: str,
    prefer_heavy: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Call real Claude Code CLI if enabled.

    Requires AIMS_ENABLE_CLAUDE_CODE_AUTO_REVIEW=1 env var to enable; default is enabled.
    """
    if not is_claude_code_auto_review_enabled():
        return None

    try:
        # Build prompt
        prompt = build_claude_code_review_prompt(artifact_path, objective, acceptance_criteria)
        provider = review_mode or get_claude_review_provider()

        if provider not in {"aws_bedrock_claude_code", "real_local_claude_cli"}:
            return None

        review = invoke_real_claude_review(
            review_id=review_id,
            review_mode=provider,
            prompt=prompt,
            max_tokens=1024,
            prefer_heavy=prefer_heavy,
            require_bedrock_env=(provider == "aws_bedrock_claude_code"),
        )
        review["review_mode"] = provider
        return review

    except Exception:
        return None


def validate_review_result(review: Dict[str, Any]) -> bool:
    """Validate review result has required fields."""
    required_fields = [
        "verdict",
        "corrected_plan",
        "mistakes_found",
        "repairman_tasks",
        "traini_learning_materials",
        "feedback_for_logi",
        "task_scope_approval_inherited",
        "task_scope_execution_allowed",
        "intermediate_approval_required",
        "final_policy_gate_required",
        "final_gate_status",
        "policy_allowed",
        "out_of_policy",
        "exception_actions",
        "exception_actions_detected",
        "approval_source",
        "execution_recommendation",
        "human_approval_required",
        "blocked_reason",
    ]

    return all(field in review for field in required_fields)


def run_review_worker_once(review_id: Optional[str] = None) -> int:
    """
    Process one pending review request.

    Returns:
        0 if success, 1 if error, 2 if no pending requests
    """
    if review_id:
        request = get_pending_review_request(review_id)
        pending = [request] if request else []
    else:
        pending = list_pending_review_requests()

    if not pending:
        return 2  # No pending requests

    # Process first pending request
    request = pending[0]
    if request is None:
        return 2
    review_id = request["review_id"]
    artifact_path = request["source_artifact"]
    objective = request["objective"]
    acceptance_criteria = request.get("acceptance_criteria", [])

    try:
        # Mark in progress
        mark_review_in_progress(review_id)

        review_mode = str(request.get("review_mode") or request.get("review_provider") or get_claude_review_provider()).strip().lower()
        prefer_heavy = str(request.get("review_model_preference", "")).strip().lower() == "opus"

        # Try real Claude Code CLI first when explicitly requested.
        review = optionally_call_claude_code_cli_if_enabled(
            artifact_path,
            objective,
            acceptance_criteria,
            review_id=review_id,
            review_mode=review_mode,
            prefer_heavy=prefer_heavy,
        )

        if review is None:
            if review_mode == "simulation":
                review = simulate_claude_code_review_for_smoke(artifact_path, objective)
                review["simulation_used"] = True
                review["claude_code_called"] = False
                review = _build_real_review_metadata(
                    review,
                    review_id=review_id,
                    review_mode="simulation",
                    source_artifact=artifact_path,
                )
            else:
                raise RuntimeError(
                    f"real review requested but no real result was produced for mode={review_mode}"
                )

        # Normalize task-scope approval schema for downstream consumers.
        review = _build_real_review_metadata(
            review,
            review_id=review_id,
            review_mode=str(review.get("review_mode") or review_mode),
            source_artifact=artifact_path,
        )

        # Validate result
        if not validate_review_result(review):
            mark_review_failed(review_id, "Review result missing required fields")
            return 1

        # Add metadata
        review["review_id"] = review_id
        review["source_artifact"] = artifact_path
        review["reviewer"] = "claude_code"
        review["created_at"] = datetime.utcnow().isoformat() + "Z"

        # Apply safe recommendations first so the completed review result includes the execution summary.
        review["recommendation_execution"] = apply_review_recommendations(review, artifact_path=artifact_path)

        # Write result
        write_review_result(review)
        mark_review_completed(review_id, "")

        return 0

    except Exception as e:
        mark_review_failed(review_id, str(e))
        return 1


def write_worker_evidence(output_dir: str) -> str:
    """Write evidence of worker run."""
    from logi.claude_review_queue import get_queue_status

    status = get_queue_status()

    evidence = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "queue_status": status,
        "claude_code_cli_enabled": os.environ.get(CLAUDE_CODE_AUTO_REVIEW_ENV, "1"),
    }

    import pathlib
    output_path = pathlib.Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    evidence_file = output_path / "worker_evidence.json"
    with open(evidence_file, "w") as f:
        json.dump(evidence, f, indent=2)

    return str(evidence_file)


if __name__ == "__main__":
    import sys

    # CLI: python3 ops/logi/claude_review_worker.py --once [--simulate] [--review-id ID]
    simulate_only = "--simulate" in sys.argv
    once = "--once" in sys.argv
    review_id_arg: Optional[str] = None
    if "--review-id" in sys.argv:
        try:
            review_id_arg = sys.argv[sys.argv.index("--review-id") + 1]
        except Exception:
            review_id_arg = None

    if not once:
        logging.error("Usage: python3 ops/logi/claude_review_worker.py --once [--simulate] [--review-id ID]")
        sys.exit(1)

    if simulate_only:
        os.environ[CLAUDE_CODE_AUTO_REVIEW_ENV] = "0"
        os.environ["AIMS_CLAUDE_REVIEW_PROVIDER"] = "simulation"
    elif review_id_arg:
        # Keep the provider determined by the request or environment.
        pass

    if review_id_arg:
        request = get_pending_review_request(review_id_arg)
        if request is None:
            logging.error("Requested review id not found in pending queue: %s", review_id_arg)
            sys.exit(1)

    result = run_review_worker_once(review_id_arg)
    sys.exit(result)


__all__ = [
    "build_claude_code_review_prompt",
    "simulate_claude_code_review_for_smoke",
    "optionally_call_claude_code_cli_if_enabled",
    "validate_review_result",
    "run_review_worker_once",
    "write_worker_evidence",
]
