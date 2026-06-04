from __future__ import annotations

import datetime as dt
from typing import Any

from .certification_intake_schema import CertificationCandidatePackage


def build_package(execution: dict[str, Any]) -> dict[str, Any]:
    cid = f"CCP-{execution['execution_id']}"
    pack = CertificationCandidatePackage(
        certification_candidate_id=cid,
        source_execution_id=execution["execution_id"],
        sandbox_plan_id=execution["sandbox_plan_id"],
        source_candidate_skill_id=execution["source_candidate_skill_id"],
        source_skill_pack_id=execution["source_skill_pack_id"],
        owner_agent_id=execution["owner_agent_id"],
        skill_name=execution["skill_name"],
        skill_domain=execution["skill_domain"],
        lifecycle_state_before=execution["lifecycle_state_after"],
        sandbox_result_status=execution["result_status"],
        sandbox_pass_count=int(execution.get("pass_count", 0)),
        sandbox_warn_count=int(execution.get("warn_count", 0)),
        sandbox_fail_count=int(execution.get("fail_count", 0)),
        evidence_refs=list(execution.get("evidence_refs", [])),
        safety_checks=dict(execution.get("safety_checks", {})),
        gate_checklist_id=f"GCL-{cid}",
        rollback_notes="Rollback to CANDIDATE_SKILL if any mandatory gate fails.",
        deprecation_notes="No runtime activation in intake phase.",
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    return pack.to_dict()
