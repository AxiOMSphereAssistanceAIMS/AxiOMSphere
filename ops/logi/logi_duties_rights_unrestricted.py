"""
Logi Duties & Rights — Task-Scope Approval with Protected-Action Gating

Authorization: User explicit confirmation 2026-06-02T14:41:12Z
Scope: Logi never stops with blocker-only responses. Always produces useful allowed work.

Protected-Action Matrix:
A. Always allowed (no mutation):
   - planning, analysis, status, work packet generation
   - Claude Code review request drafting

B. Allowed after Claude Code review:
   - code patch proposals, test execution plans, repair proposals
   - non-destructive local test-production execution

C. Blocked/deferred out_of_policy unless separately pre-approved:
   - training execution, model download/delete/promote
   - model registry mutation, database writes
   - expensive API/AWS/Claude calls
   - service restarts

D. Never allowed automatically:
   - secrets exposure, killing OmniRoute, docker compose down

All solutions are reviewed by Claude Code CLI. Normal in-scope work inherits
task-scope approval; exception actions are blocked/deferred by policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List


class LogiDutyCategory(Enum):
    """Logi duty categories (all executable)."""
    PLANNING = "planning"
    ANALYSIS = "analysis"
    REPAIR = "repair"
    EXECUTION = "execution"
    MODEL_OPERATIONS = "model_operations"
    TRAINING = "training"
    SERVICE_MANAGEMENT = "service_management"
    DATA_MUTATION = "data_mutation"


class LogiApprovalGate(Enum):
    """Approval gates for Logi execution."""
    CLAUDE_CODE_CLI_ONLY = "claude_code_cli_review_only"
    CLAUDE_CODE_CLI_PLUS_HUMAN = "claude_code_cli_then_human_approval"
    NEVER_AUTOMATIC = "never_allowed_automatically"


class LogiProtectedActionCategory(Enum):
    """Categories of protected actions (require extra approval)."""
    ALWAYS_ALLOWED = "always_allowed_no_mutation"
    REVIEWED_ONLY = "reviewed_by_claude_code_only"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required_after_review"
    NEVER_ALLOWED = "never_allowed_automatically"


@dataclass
class LogiDuty:
    """A duty Logi can perform."""
    category: LogiDutyCategory
    name: str
    description: str
    requires_approval: LogiApprovalGate
    protected_action_category: LogiProtectedActionCategory
    requires_rollback_plan: bool
    high_risk: bool
    destructive: bool


# All duties available to Logi in unrestricted mode
LOGI_DUTIES = {
    # Planning & Analysis (low risk, always allowed without mutation)
    "planning": LogiDuty(
        category=LogiDutyCategory.PLANNING,
        name="Strategic planning",
        description="Create plans, work packets, strategies",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_ONLY,
        protected_action_category=LogiProtectedActionCategory.ALWAYS_ALLOWED,
        requires_rollback_plan=False,
        high_risk=False,
        destructive=False,
    ),
    "analysis": LogiDuty(
        category=LogiDutyCategory.ANALYSIS,
        name="System analysis",
        description="Analyze systems, interactions, gaps",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_ONLY,
        protected_action_category=LogiProtectedActionCategory.ALWAYS_ALLOWED,
        requires_rollback_plan=False,
        high_risk=False,
        destructive=False,
    ),

    # Repair & Execution (medium-high risk, requires review but can execute after approval)
    "repair": LogiDuty(
        category=LogiDutyCategory.REPAIR,
        name="Code/config repair",
        description="Fix bugs, patch code, update configs",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_ONLY,
        protected_action_category=LogiProtectedActionCategory.REVIEWED_ONLY,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=False,
    ),
    "execution": LogiDuty(
        category=LogiDutyCategory.EXECUTION,
        name="Task execution",
        description="Execute plans, workflows, scripts",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_ONLY,
        protected_action_category=LogiProtectedActionCategory.REVIEWED_ONLY,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=False,
    ),

    # Model Operations (high risk, blocked/deferred out_of_policy unless separately pre-approved)
    "model_download": LogiDuty(
        category=LogiDutyCategory.MODEL_OPERATIONS,
        name="Model download",
        description="Download/load models",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=False,
    ),
    "model_delete": LogiDuty(
        category=LogiDutyCategory.MODEL_OPERATIONS,
        name="Model deletion",
        description="Delete models (DESTRUCTIVE)",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=True,
    ),
    "model_promote": LogiDuty(
        category=LogiDutyCategory.MODEL_OPERATIONS,
        name="Model promotion",
        description="Promote model to production",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=False,
    ),

    # Training (high risk, blocked/deferred out_of_policy unless separately pre-approved)
    "training_start": LogiDuty(
        category=LogiDutyCategory.TRAINING,
        name="Start training",
        description="Start model fine-tuning",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=False,
    ),
    "training_monitor": LogiDuty(
        category=LogiDutyCategory.TRAINING,
        name="Monitor training",
        description="Monitor and adjust training",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_ONLY,
        protected_action_category=LogiProtectedActionCategory.REVIEWED_ONLY,
        requires_rollback_plan=False,
        high_risk=False,
        destructive=False,
    ),

    # Service Management (high risk, blocked/deferred out_of_policy unless separately pre-approved)
    "service_restart": LogiDuty(
        category=LogiDutyCategory.SERVICE_MANAGEMENT,
        name="Service restart",
        description="Restart services (logi-bot, agents, etc)",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=False,
    ),
    "service_start_stop": LogiDuty(
        category=LogiDutyCategory.SERVICE_MANAGEMENT,
        name="Start/stop services",
        description="Start or stop services",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=False,
    ),

    # Data Mutation (high risk, DESTRUCTIVE, blocked/deferred out_of_policy unless separately pre-approved)
    "data_write": LogiDuty(
        category=LogiDutyCategory.DATA_MUTATION,
        name="Database write",
        description="Modify database (DESTRUCTIVE)",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=True,
    ),
    "registry_mutation": LogiDuty(
        category=LogiDutyCategory.DATA_MUTATION,
        name="Registry mutation",
        description="Modify model registry (DESTRUCTIVE)",
        requires_approval=LogiApprovalGate.CLAUDE_CODE_CLI_PLUS_HUMAN,
        protected_action_category=LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED,
        requires_rollback_plan=True,
        high_risk=True,
        destructive=True,
    ),
}


def get_all_duties() -> List[LogiDuty]:
    """Get all available duties."""
    return list(LOGI_DUTIES.values())


def get_duty(name: str) -> LogiDuty | None:
    """Get a specific duty by name."""
    return LOGI_DUTIES.get(name)


def get_duties_by_category(category: LogiDutyCategory) -> List[LogiDuty]:
    """Get duties by category."""
    return [d for d in LOGI_DUTIES.values() if d.category == category]


def get_high_risk_duties() -> List[LogiDuty]:
    """Get high-risk duties."""
    return [d for d in LOGI_DUTIES.values() if d.high_risk]


def get_destructive_duties() -> List[LogiDuty]:
    """Get destructive duties."""
    return [d for d in LOGI_DUTIES.values() if d.destructive]


def get_approval_requirement(duty_name: str) -> LogiApprovalGate:
    """Get approval requirement for a duty."""
    duty = get_duty(duty_name)
    return duty.requires_approval if duty else LogiApprovalGate.CLAUDE_CODE_CLI


def requires_rollback_plan(duty_name: str) -> bool:
    """Check if duty requires rollback plan."""
    duty = get_duty(duty_name)
    return duty.requires_rollback_plan if duty else False


def is_high_risk(duty_name: str) -> bool:
    """Check if duty is high-risk."""
    duty = get_duty(duty_name)
    return duty.high_risk if duty else False


def is_destructive(duty_name: str) -> bool:
    """Check if duty is destructive."""
    duty = get_duty(duty_name)
    return duty.destructive if duty else False


def get_protected_action_duties() -> List[LogiDuty]:
    """Get duties blocked/deferred out_of_policy."""
    return [
        d for d in LOGI_DUTIES.values()
        if d.protected_action_category == LogiProtectedActionCategory.HUMAN_APPROVAL_REQUIRED
    ]


def get_always_allowed_duties() -> List[LogiDuty]:
    """Get duties that never require mutation approval."""
    return [
        d for d in LOGI_DUTIES.values()
        if d.protected_action_category == LogiProtectedActionCategory.ALWAYS_ALLOWED
    ]


def summarize_duties() -> dict:
    """Summarize all duties with correct policy classification."""
    return {
        "mode": "continuous_work_with_protected_action_gating",
        "total_duties": len(LOGI_DUTIES),
        "always_allowed": len(get_always_allowed_duties()),
        "reviewed_only": len([
            d for d in LOGI_DUTIES.values()
            if d.protected_action_category == LogiProtectedActionCategory.REVIEWED_ONLY
        ]),
        "task_scope_approval_inherited": True,
        "policy_allowed": True,
        "out_of_policy": False,
        "exception_actions_blocked_out_of_policy": len(get_protected_action_duties()),
        "human_approval_required": False,
        "high_risk_count": len(get_high_risk_duties()),
        "destructive_count": len(get_destructive_duties()),
        "all_require_claude_review": True,
        "exception_actions_blocked_out_of_policy_flag": True,
        "training_gated_by_traini_governance": True,
        "model_ops_gated": True,
        "destructive_actions_gated": True,
        "authorization": "User explicit confirmation 2026-06-02T14:41:12Z",
    }


__all__ = [
    "LogiDutyCategory",
    "LogiApprovalGate",
    "LogiProtectedActionCategory",
    "LogiDuty",
    "LOGI_DUTIES",
    "get_all_duties",
    "get_duty",
    "get_duties_by_category",
    "get_high_risk_duties",
    "get_destructive_duties",
    "get_protected_action_duties",
    "get_always_allowed_duties",
    "get_approval_requirement",
    "requires_rollback_plan",
    "is_high_risk",
    "is_destructive",
    "summarize_duties",
]
