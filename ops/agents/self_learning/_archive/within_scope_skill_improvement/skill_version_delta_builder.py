from __future__ import annotations

import datetime as dt

from .skill_improvement_schema import SkillVersionDelta

ALLOWED_IMPROVEMENTS = {
    "PROMPT_REFINEMENT",
    "TRIGGER_REFINEMENT",
    "OUTPUT_SCHEMA_REFINEMENT",
    "REFUSAL_RULE_REFINEMENT",
    "TEST_COVERAGE_EXPANSION",
    "EVIDENCE_REQUIREMENT_REFINEMENT",
}


def _next_version(cur: str) -> str:
    cur = cur or "v1"
    if "." in cur:
        base, minor = cur.split(".", 1)
        if minor.isdigit():
            return f"{base}.{int(minor)+1}"
    if cur.startswith("v") and cur[1:].isdigit():
        return f"{cur}.1"
    return "v1.1"


def build_delta(active_entry: dict, assessment: dict, plan: dict, event_ids: list[str]) -> dict:
    imp = plan.get("improvement_type", "NO_CHANGE")
    if imp not in ALLOWED_IMPROVEMENTS:
        imp = "OUTPUT_SCHEMA_REFINEMENT"

    delta = SkillVersionDelta(
        delta_id=f"DELTA-{active_entry['active_skill_id']}",
        active_skill_id=active_entry["active_skill_id"],
        owner_agent_id=active_entry["owner_agent_id"],
        skill_name=active_entry["skill_name"],
        current_version=active_entry.get("version", "v1"),
        proposed_version=_next_version(active_entry.get("version", "v1")),
        improvement_type=imp,
        source_monitoring_event_ids=event_ids,
        source_assessment_id=assessment.get("assessment_id", ""),
        source_improvement_plan_id=plan.get("improvement_plan_id", ""),
        proposed_changes=list(plan.get("proposed_changes", [])) or ["tighten output schema consistency"],
        unchanged_scope_fields=[
            "approved_scope_id", "approved_risk_class", "approved_permission_level",
            "allowed_actions", "forbidden_actions", "owner_agent_id",
        ],
        permission_delta="no_expansion",
        risk_class_delta="unchanged",
        owner_agent_delta="unchanged",
        runtime_context_delta="unchanged",
        forbidden_action_delta="stricter",
        expected_benefit="higher consistency and better refusal precision",
        required_regression_tests=[
            "scope_regression",
            "forbidden_action_regression",
            "output_schema_regression",
            "evidence_regression",
            "rollback_regression",
        ],
        scope_expansion_detected=False,
        new_approval_required=False,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    return delta.to_dict()
