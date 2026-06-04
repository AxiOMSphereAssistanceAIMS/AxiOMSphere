from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ActiveSkillMonitoringEvent:
    event_id: str
    active_skill_id: str
    owner_agent_id: str
    skill_name: str
    event_type: str
    runtime_context: str
    input_summary: str
    output_summary: str
    evidence_refs: list[str] = field(default_factory=list)
    inside_approved_scope: bool = True
    permission_expansion_detected: bool = False
    risk_class_change_detected: bool = False
    unsafe_action_detected: bool = False
    user_visible_effect: str = ""
    success_signal: bool = False
    failure_signal: bool = False
    improvement_signal: bool = False
    rollback_signal: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
