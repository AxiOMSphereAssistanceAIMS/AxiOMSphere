"""Natural-language syntax intent schema for Logi Telegram UX."""

from __future__ import annotations

from dataclasses import asdict, dataclass


ALLOWED_INTENT_TYPES = {
    "plan_view",
    "strategic_plan_view",
    "active_strategic_plan_view",
    "strategic_plan_refresh",
    "strategic_execution_package_prepare",
    "project_pulse_view",
    "change_stack_view",
    "next_strategic_action_view",
    "status_view",
    "blocked_view",
    "approvals_view",
    "chain_status_view",
    "next_actions_view",
    "inter_agent_review_request",
    "consolidated_decision_request",
    "approval_action",
    "repair_action",
    "execute_action",
    "restart_action",
    "activate_action",
    "promotion_blockers_view",
    "known_failures_view",
    "unknown",
}

ALLOWED_HORIZONS = {"day", "week", "month", "strategic", "none"}
ALLOWED_MODES = {"read_only", "request_only", "mutation", "unknown"}


@dataclass
class SyntaxIntent:
    raw_text: str
    normalized_text: str
    detected_language: str
    intent_type: str
    horizon: str
    mode: str
    target_agents: list[str]
    requested_workflow: str
    confidence: float
    safety_class: str
    enabled: bool
    reason: str
    response_style: str

    def validate(self) -> None:
        if self.intent_type not in ALLOWED_INTENT_TYPES:
            raise ValueError(f"invalid intent_type: {self.intent_type}")
        if self.horizon not in ALLOWED_HORIZONS:
            raise ValueError(f"invalid horizon: {self.horizon}")
        if self.mode not in ALLOWED_MODES:
            raise ValueError(f"invalid mode: {self.mode}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)
