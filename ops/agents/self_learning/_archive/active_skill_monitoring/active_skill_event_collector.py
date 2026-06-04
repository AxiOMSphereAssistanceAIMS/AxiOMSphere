from __future__ import annotations

import datetime as dt

from .active_skill_monitoring_schema import ActiveSkillMonitoringEvent


def collect_events(active_entry: dict, first_use: dict) -> list[dict]:
    ev1 = ActiveSkillMonitoringEvent(
        event_id=f"EV-{active_entry['active_skill_id']}-FIRST",
        active_skill_id=active_entry["active_skill_id"],
        owner_agent_id=active_entry["owner_agent_id"],
        skill_name=active_entry["skill_name"],
        event_type="CONTROLLED_FIRST_USE",
        runtime_context=active_entry.get("runtime_use_mode", "CONTROLLED_SCOPE_ONLY"),
        input_summary=str(first_use.get("input_context", "")),
        output_summary=str(first_use.get("output_summary", "")),
        evidence_refs=list(first_use.get("evidence_refs", [])),
        inside_approved_scope=True,
        success_signal=first_use.get("result_status") in {"FIRST_USE_PASS", "FIRST_USE_WARN"},
        failure_signal=first_use.get("result_status") == "FIRST_USE_FAIL",
        improvement_signal=True,
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    ).to_dict()

    ev2 = ActiveSkillMonitoringEvent(
        event_id=f"EV-{active_entry['active_skill_id']}-IMPROVE",
        active_skill_id=active_entry["active_skill_id"],
        owner_agent_id=active_entry["owner_agent_id"],
        skill_name=active_entry["skill_name"],
        event_type="IMPROVEMENT_OBSERVED",
        runtime_context=active_entry.get("runtime_use_mode", "CONTROLLED_SCOPE_ONLY"),
        input_summary="post-first-use analysis",
        output_summary="minor schema refinement opportunity",
        evidence_refs=list(active_entry.get("evidence_refs", [])),
        inside_approved_scope=True,
        improvement_signal=True,
        success_signal=True,
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    ).to_dict()

    return [ev1, ev2]
