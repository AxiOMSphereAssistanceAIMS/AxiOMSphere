from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .per_agent_loop_schema import AgentSelfLearningProfile


AGENT_DEFS = [
    ("axi", "orchestrator_chat"),
    ("omi", "assistant_dialogue"),
    ("argus", "safety_truth_audit"),
    ("logi", "planning_execution"),
    ("traini", "model_improvement"),
    ("knomi", "knowledge_memory"),
    ("doci", "document_work"),
    ("mainy_repairman", "repair_execution"),
    ("autonomy_control", "autonomy_governance"),
    ("long_running_self_regulation", "long_run_regulation"),
    ("strategic_planned_actions", "planned_action_orchestration"),
    ("self_test_planning", "self_test_planning"),
    ("model_tuning_readiness", "tuning_readiness"),
    ("nemotron_skill_tuning_readiness", "nemotron_tuning_readiness"),
    ("hermes_external_worker", "external_shadow_worker"),
]


def _pace(agent_id: str) -> str:
    if agent_id in {"axi", "omi", "argus", "logi"}:
        return "on_event"
    if agent_id in {"traini", "model_tuning_readiness", "nemotron_skill_tuning_readiness"}:
        return "hourly"
    return "daily"


def build_profiles(root: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    profiles: list[dict] = []
    for agent_id, role in AGENT_DEFS:
        next_due = now + timedelta(minutes=30)
        p = AgentSelfLearningProfile(
            agent_id=agent_id,
            agent_role=role,
            self_learning_enabled=True,
            loop_mode="SELF_LEARNING_DRY_RUN" if agent_id != "argus" else "OBSERVATION_ONLY",
            loop_pace=_pace(agent_id),
            observation_sources=[f"{root}/{agent_id}/events", f"{root}/{agent_id}/evidence"],
            local_evidence_store=f"{root}/per_agent_loop/{agent_id}/evidence",
            local_skill_request_outbox=f"{root}/per_agent_loop/{agent_id}/skill_request_outbox",
            assigned_active_skills=[],
            owned_skill_domains=[role],
            allowed_skill_permission_levels=["ADVISORY_ONLY", "READ_ONLY_ANALYSIS", "SYNTHETIC_SANDBOX_EXECUTION", "CONTROLLED_RUNTIME_USE"],
            forbidden_actions=[
                "self_approval",
                "permission_expansion_without_approval",
                "service_restart",
                "model_load_unload",
                "training_launch",
                "secrets_access",
                "raw_claude_mem_access",
                "deletion",
                "quarantine",
            ],
            last_loop_run=now.isoformat(),
            next_loop_due=next_due.isoformat(),
            status="READY",
        )
        profiles.append(p.to_dict())
    return profiles
