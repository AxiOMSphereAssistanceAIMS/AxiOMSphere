from __future__ import annotations

import datetime as dt

from .active_skill_registry_schema import ActiveSkillRegistryEntry


def build_active_registry_entry(scope: dict, lineage: dict, rollback_manifest_id: str) -> dict:
    e = ActiveSkillRegistryEntry(
        active_skill_id=f"ASK-{lineage['skill_pack_id']}",
        source_request_id=scope["source_request_id"],
        source_skill_pack_id=lineage["skill_pack_id"],
        source_candidate_skill_id=lineage["candidate_skill_id"],
        owner_agent_id=scope["owner_agent_id"],
        skill_name=scope["skill_name"],
        skill_domain=scope["skill_domain"],
        lifecycle_state="ACTIVE_RUNTIME_SKILL",
        activation_status="ACTIVE_WITHIN_APPROVED_SCOPE",
        approved_scope_id=scope["scope_id"],
        approved_risk_class=scope["approved_risk_class"],
        approved_permission_level=scope["approved_permission_level"],
        allowed_actions=list(scope.get("approved_actions", [])),
        forbidden_actions=list(scope.get("forbidden_actions", [])),
        required_gates=list(scope.get("required_gates", [])),
        activation_conditions=list(scope.get("activation_conditions", [])),
        rollback_manifest_id=rollback_manifest_id,
        evidence_refs=list(lineage.get("evidence_refs", [])),
        activated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        deactivation_conditions=list(scope.get("deactivation_conditions", [])),
    )
    return e.to_dict()
