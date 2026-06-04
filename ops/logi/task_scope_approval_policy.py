"""Task-scope execution policy for Logi.

User task scope is the default execution boundary for normal Logi work:
- in-scope, reversible, non-destructive work is allowed to execute
- Claude Code review remains a quality gate
- only one final safety gate should remain at the end of the task
- exception actions are blocked/deferred without repeated human approval loops
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


SAFE_TO_EXECUTE_IN_SCOPE = "safe_to_execute_in_scope"
BLOCKED_OUT_OF_POLICY = "blocked_out_of_policy"
NEEDS_MORE_CONTEXT = "needs_more_context"
FAILED_POLICY_CHECK = "failed_policy_check"
USER_TASK_SCOPE = "user_task_scope"


@dataclass
class TaskScopeApprovalDecision:
    task_scope_approval_inherited: bool
    task_scope_execution_allowed: bool
    intermediate_approval_required: bool
    final_policy_gate_required: bool
    final_gate_status: str
    policy_allowed: bool
    out_of_policy: bool
    exception_actions: list[str] = field(default_factory=list)
    approval_source: str | None = USER_TASK_SCOPE
    execution_recommendation: str = SAFE_TO_EXECUTE_IN_SCOPE
    human_approval_required: bool = False
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_safe_task_scope_decision() -> dict[str, Any]:
    return TaskScopeApprovalDecision(
        task_scope_approval_inherited=True,
        task_scope_execution_allowed=True,
        intermediate_approval_required=False,
        final_policy_gate_required=True,
        final_gate_status="PENDING",
        policy_allowed=True,
        out_of_policy=False,
        exception_actions=[],
        approval_source=USER_TASK_SCOPE,
        execution_recommendation=SAFE_TO_EXECUTE_IN_SCOPE,
        human_approval_required=False,
        blocked_reason="",
    ).to_dict()


def build_blocked_out_of_policy_decision(
    exception_actions: list[str] | None = None,
    blocked_reason: str = "Exception action not covered by task-scope policy.",
) -> dict[str, Any]:
    return TaskScopeApprovalDecision(
        task_scope_approval_inherited=False,
        task_scope_execution_allowed=False,
        intermediate_approval_required=False,
        final_policy_gate_required=True,
        final_gate_status="PENDING",
        policy_allowed=False,
        out_of_policy=True,
        exception_actions=list(exception_actions or []),
        approval_source=None,
        execution_recommendation=BLOCKED_OUT_OF_POLICY,
        human_approval_required=False,
        blocked_reason=blocked_reason,
    ).to_dict()


def build_needs_context_decision(blocked_reason: str = "More context required before policy decision.") -> dict[str, Any]:
    return TaskScopeApprovalDecision(
        task_scope_approval_inherited=False,
        task_scope_execution_allowed=False,
        intermediate_approval_required=False,
        final_policy_gate_required=True,
        final_gate_status="PENDING",
        policy_allowed=False,
        out_of_policy=False,
        exception_actions=[],
        approval_source=None,
        execution_recommendation=NEEDS_MORE_CONTEXT,
        human_approval_required=False,
        blocked_reason=blocked_reason,
    ).to_dict()


def build_failed_policy_check_decision(blocked_reason: str = "Policy check failed.") -> dict[str, Any]:
    return TaskScopeApprovalDecision(
        task_scope_approval_inherited=False,
        task_scope_execution_allowed=False,
        intermediate_approval_required=False,
        final_policy_gate_required=True,
        final_gate_status="FAIL",
        policy_allowed=False,
        out_of_policy=False,
        exception_actions=[],
        approval_source=None,
        execution_recommendation=FAILED_POLICY_CHECK,
        human_approval_required=False,
        blocked_reason=blocked_reason,
    ).to_dict()


def classify_task_scope_approval(
    *,
    in_scope: bool = True,
    exception_actions: list[str] | None = None,
    blocked_reason: str = "",
) -> dict[str, Any]:
    if in_scope and not exception_actions:
        return build_safe_task_scope_decision()
    return build_blocked_out_of_policy_decision(exception_actions, blocked_reason or "Exception action not covered by task-scope policy.")


def render_task_scope_policy_message(decision: dict[str, Any]) -> str:
    if decision.get("execution_recommendation") == SAFE_TO_EXECUTE_IN_SCOPE:
        return (
            "Task-scope execution allowed.\n"
            "Claude Code review required.\n"
            "Final safety gate pending or passed at task end."
        )
    if decision.get("execution_recommendation") == BLOCKED_OUT_OF_POLICY:
        exc = decision.get("exception_actions") or []
        extra = f" Exception actions: {', '.join(exc)}." if exc else ""
        return (
            "Task-scope execution does not cover this request.\n"
            "Claude Code review remains required for normal work, but exception actions are blocked_out_of_policy."
            f"{extra}"
        )
    if decision.get("execution_recommendation") == NEEDS_MORE_CONTEXT:
        return "Needs more context before policy decision."
    return "Policy gate failed."


__all__ = [
    "SAFE_TO_EXECUTE_IN_SCOPE",
    "BLOCKED_OUT_OF_POLICY",
    "NEEDS_MORE_CONTEXT",
    "FAILED_POLICY_CHECK",
    "USER_TASK_SCOPE",
    "TaskScopeApprovalDecision",
    "build_safe_task_scope_decision",
    "build_blocked_out_of_policy_decision",
    "build_needs_context_decision",
    "build_failed_policy_check_decision",
    "classify_task_scope_approval",
    "render_task_scope_policy_message",
]
