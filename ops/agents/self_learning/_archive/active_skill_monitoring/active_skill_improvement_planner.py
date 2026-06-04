from __future__ import annotations

import datetime as dt


def build_improvement_plan(active_entry: dict, assessment: dict) -> dict:
    if assessment.get("new_approval_required"):
        return {
            "improvement_plan_id": f"IMP-{active_entry['active_skill_id']}",
            "active_skill_id": active_entry["active_skill_id"],
            "owner_agent_id": active_entry["owner_agent_id"],
            "skill_name": active_entry["skill_name"],
            "improvement_type": "NEW_SCOPE_REQUEST",
            "current_version": active_entry.get("version", "v1"),
            "proposed_version": "v_next",
            "changes_inside_approved_scope": False,
            "scope_expansion_required": True,
            "new_approval_required": True,
            "proposed_changes": ["scope expansion proposal required"],
            "required_tests": ["new_scope_tests"],
            "evidence_refs": list(active_entry.get("evidence_refs", [])),
            "next_action": "CREATE_NEW_SKILL_REQUEST_OR_SCOPE_EXPANSION_REQUEST",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    if assessment.get("rollback_recommended"):
        return {
            "improvement_plan_id": f"IMP-{active_entry['active_skill_id']}",
            "active_skill_id": active_entry["active_skill_id"],
            "owner_agent_id": active_entry["owner_agent_id"],
            "skill_name": active_entry["skill_name"],
            "improvement_type": "ROLLBACK",
            "current_version": active_entry.get("version", "v1"),
            "proposed_version": active_entry.get("version", "v1"),
            "changes_inside_approved_scope": False,
            "scope_expansion_required": False,
            "new_approval_required": True,
            "proposed_changes": ["rollback active skill"],
            "required_tests": ["rollback_validation"],
            "evidence_refs": list(active_entry.get("evidence_refs", [])),
            "next_action": "ROLLBACK_PIPELINE",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    if assessment.get("improvement_needed"):
        return {
            "improvement_plan_id": f"IMP-{active_entry['active_skill_id']}",
            "active_skill_id": active_entry["active_skill_id"],
            "owner_agent_id": active_entry["owner_agent_id"],
            "skill_name": active_entry["skill_name"],
            "improvement_type": "OUTPUT_SCHEMA_REFINEMENT",
            "current_version": active_entry.get("version", "v1"),
            "proposed_version": "v1.1",
            "changes_inside_approved_scope": True,
            "scope_expansion_required": False,
            "new_approval_required": False,
            "proposed_changes": ["tighten output schema and refusal messaging"],
            "required_tests": ["schema_regression", "refusal_rule_regression"],
            "evidence_refs": list(active_entry.get("evidence_refs", [])),
            "next_action": "QUEUE_WITHIN_SCOPE_SKILL_IMPROVEMENT",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    return {
        "improvement_plan_id": f"IMP-{active_entry['active_skill_id']}",
        "active_skill_id": active_entry["active_skill_id"],
        "owner_agent_id": active_entry["owner_agent_id"],
        "skill_name": active_entry["skill_name"],
        "improvement_type": "NO_CHANGE",
        "current_version": active_entry.get("version", "v1"),
        "proposed_version": active_entry.get("version", "v1"),
        "changes_inside_approved_scope": True,
        "scope_expansion_required": False,
        "new_approval_required": False,
        "proposed_changes": [],
        "required_tests": [],
        "evidence_refs": list(active_entry.get("evidence_refs", [])),
        "next_action": "NO_ACTION_REQUIRED",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
