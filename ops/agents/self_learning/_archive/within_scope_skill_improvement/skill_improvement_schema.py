from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SkillVersionDelta:
    delta_id: str
    active_skill_id: str
    owner_agent_id: str
    skill_name: str
    current_version: str
    proposed_version: str
    improvement_type: str
    source_monitoring_event_ids: list[str] = field(default_factory=list)
    source_assessment_id: str = ""
    source_improvement_plan_id: str = ""
    proposed_changes: list[str] = field(default_factory=list)
    unchanged_scope_fields: list[str] = field(default_factory=list)
    permission_delta: str = "no_expansion"
    risk_class_delta: str = "unchanged"
    owner_agent_delta: str = "unchanged"
    runtime_context_delta: str = "unchanged"
    forbidden_action_delta: str = "unchanged"
    expected_benefit: str = ""
    required_regression_tests: list[str] = field(default_factory=list)
    scope_expansion_detected: bool = False
    new_approval_required: bool = False
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
