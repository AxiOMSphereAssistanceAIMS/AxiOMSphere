"""
Claude Code CLI Gate — All Logi Solutions Go Through Review

Every solution from Logi will:
1. Be drafted
2. Sent to Claude Code CLI for review
3. Await task-scope and policy review before execution
4. Include rollback plan if high-risk

This is the execution gate for approved-strategy Logi mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from logi.task_scope_approval_policy import build_safe_task_scope_decision


class ReviewStatus(Enum):
    """Status of Claude Code CLI review."""
    PENDING = "pending_review"
    APPROVED = "approved_for_execution"
    APPROVED_WITH_CHANGES = "approved_with_changes"
    REJECTED = "rejected_do_not_execute"
    NEEDS_MORE_INFO = "needs_more_information"


@dataclass
class RollbackPlan:
    """Rollback plan for high-risk operations."""
    steps: List[str]
    estimated_time_minutes: int
    testing_required: bool
    rollback_command: Optional[str] = None


@dataclass
class LogiSolution:
    """A solution from Logi awaiting Claude Code review."""
    solution_id: str
    objective: str
    solution_type: str  # repair, training, execution, etc.
    proposed_action: str
    affected_files_or_systems: List[str]
    high_risk: bool
    destructive: bool
    rollback_plan: Optional[RollbackPlan] = None
    safety_notes: List[str] = None
    evidence: Dict[str, Any] = None
    task_scope_approval_inherited: bool = True
    policy_allowed: bool = True
    out_of_policy: bool = False
    exception_actions: List[str] = None
    approval_source: Optional[str] = "user_task_scope"
    execution_recommendation: str = "safe_to_execute_in_scope"
    human_approval_required: bool = False
    blocked_reason: str = ""
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + "Z"
        if self.safety_notes is None:
            self.safety_notes = []
        if self.evidence is None:
            self.evidence = {}
        if self.exception_actions is None:
            self.exception_actions = []


@dataclass
class ClaudeCodeReview:
    """Claude Code CLI review result."""
    review_id: str
    solution_id: str
    status: ReviewStatus
    reviewer: str = "claude_code_cli"
    approved_by: Optional[str] = None
    corrections: List[str] = None
    required_changes: List[str] = None
    safety_concerns: List[str] = None
    additional_tests: List[str] = None
    approved_rollback_plan: Optional[RollbackPlan] = None
    execution_allowed: bool = False
    execution_deadline: Optional[str] = None
    task_scope_approval_inherited: bool = True
    policy_allowed: bool = True
    out_of_policy: bool = False
    exception_actions: List[str] = None
    approval_source: Optional[str] = "user_task_scope"
    execution_recommendation: str = "safe_to_execute_in_scope"
    human_approval_required: bool = False
    blocked_reason: str = ""
    notes: str = ""
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + "Z"
        if self.corrections is None:
            self.corrections = []
        if self.required_changes is None:
            self.required_changes = []
        if self.safety_concerns is None:
            self.safety_concerns = []
        if self.additional_tests is None:
            self.additional_tests = []
        if self.exception_actions is None:
            self.exception_actions = []

        # Determine execution status
        self.execution_allowed = self.status in (
            ReviewStatus.APPROVED,
            ReviewStatus.APPROVED_WITH_CHANGES,
        )


class ClaudeCodeGate:
    """Gate for routing all Logi solutions through Claude Code CLI."""

    def __init__(self):
        """Initialize the Claude Code gate."""
        self.pending_reviews: Dict[str, LogiSolution] = {}
        self.completed_reviews: Dict[str, ClaudeCodeReview] = {}

    def submit_for_review(
        self,
        objective: str,
        solution_type: str,
        proposed_action: str,
        affected_files: List[str],
        high_risk: bool = False,
        destructive: bool = False,
        rollback_plan: Optional[RollbackPlan] = None,
        safety_notes: Optional[List[str]] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> LogiSolution:
        """
        Submit a Logi solution for Claude Code CLI review.

        Args:
            objective: What Logi is trying to accomplish
            solution_type: Type of solution (repair, training, execution, etc)
            proposed_action: The actual action to execute
            affected_files: Files/systems affected
            high_risk: Whether this is high-risk
            destructive: Whether this is destructive
            rollback_plan: Rollback plan if needed
            safety_notes: Safety considerations
            evidence: Supporting evidence

        Returns:
            LogiSolution awaiting review
        """
        solution_id = f"logi-solution-{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"

        solution = LogiSolution(
            solution_id=solution_id,
            objective=objective,
            solution_type=solution_type,
            proposed_action=proposed_action,
            affected_files_or_systems=affected_files,
            high_risk=high_risk,
            destructive=destructive,
            rollback_plan=rollback_plan,
            safety_notes=safety_notes or [],
            evidence=evidence or {},
        )

        self.pending_reviews[solution_id] = solution
        return solution

    def get_pending_reviews(self) -> List[LogiSolution]:
        """Get all pending reviews."""
        return list(self.pending_reviews.values())

    def record_review(self, review: ClaudeCodeReview) -> None:
        """
        Record a Claude Code CLI review result.

        Args:
            review: The completed review
        """
        # Move from pending to completed
        if review.solution_id in self.pending_reviews:
            del self.pending_reviews[review.solution_id]

        self.completed_reviews[review.review_id] = review

    def can_execute(self, solution_id: str) -> tuple[bool, Optional[ClaudeCodeReview]]:
        """
        Check if a solution can be executed.

        Args:
            solution_id: The solution ID

        Returns:
            (can_execute, review_result)
        """
        for review in self.completed_reviews.values():
            if review.solution_id == solution_id:
                return review.execution_allowed, review

        return False, None

    def get_review_status(self, solution_id: str) -> Optional[ReviewStatus]:
        """Get the review status of a solution."""
        for review in self.completed_reviews.values():
            if review.solution_id == solution_id:
                return review.status
        return None

    def summarize_gate_status(self) -> dict:
        """Summarize the gate status."""
        return {
            "pending_reviews": len(self.pending_reviews),
            "completed_reviews": len(self.completed_reviews),
            "approved_for_execution": len(
                [r for r in self.completed_reviews.values() if r.execution_allowed]
            ),
            "rejected": len(
                [r for r in self.completed_reviews.values() if r.status == ReviewStatus.REJECTED]
            ),
            "needs_info": len(
                [r for r in self.completed_reviews.values() if r.status == ReviewStatus.NEEDS_MORE_INFO]
            ),
        }

    def build_claude_code_request(self, solution: LogiSolution) -> str:
        """
        Build a request to send to Claude Code CLI.

        Args:
            solution: The solution to review

        Returns:
            Request text for Claude Code CLI
        """
        risk_level = "HIGH RISK" if solution.high_risk else "MEDIUM RISK"
        destructive_warning = "[DESTRUCTIVE OPERATION]" if solution.destructive else ""

        request = f"""
Claude Code Review Request
==========================

Solution ID: {solution.solution_id}
Objective: {solution.objective}
Type: {solution.solution_type}
Risk Level: {risk_level}
{destructive_warning}

Proposed Action:
{solution.proposed_action}

Affected Files/Systems:
{chr(10).join(f'- {f}' for f in solution.affected_files_or_systems)}

Safety Notes:
{chr(10).join(f'- {n}' for n in solution.safety_notes) if solution.safety_notes else '- None specified'}

Rollback Plan:
{'Available and required' if solution.rollback_plan else 'Not applicable'}
{f'Estimated recovery time: {solution.rollback_plan.estimated_time_minutes} minutes' if solution.rollback_plan else ''}

Task-scope execution:
{build_safe_task_scope_decision()}

Please review this solution and provide:
1. Final gate status (PASS / WARN / FAIL style verdict)
2. Any corrections or required changes
3. Safety concerns if any
4. Additional tests that should be run
5. Final execution recommendation

Evidence available: {list(solution.evidence.keys())}
"""
        return request


# Global gate instance
_gate = None


def get_gate() -> ClaudeCodeGate:
    """Get or create the global Claude Code gate."""
    global _gate
    if _gate is None:
        _gate = ClaudeCodeGate()
    return _gate


__all__ = [
    "ReviewStatus",
    "RollbackPlan",
    "LogiSolution",
    "ClaudeCodeReview",
    "ClaudeCodeGate",
    "get_gate",
]
