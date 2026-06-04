"""
AIMS Self-Learning — Staged Skill Registry Builder.

Loads Phase 10 certified packages and stages eligible ones for review.
Only CERTIFIED_SKILL_READY and CERTIFIED_SKILL_WARN packages are staged.
All safety invariants, gates, rollback/deprecation plans are preserved.
No model calls, no runtime changes, no service calls.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
from typing import Any

from .staged_skill_registry_schema import (
    STAGED_LIFECYCLE_STATE,
    STAGING_GATES_ALWAYS_REQUIRED,
    STAGING_GATE_TRAINI,
    STAGING_REQUIRED_INVARIANTS,
    STAGING_STATUS_REVIEW,
    STAGING_STATUS_WARN,
    STAGING_STATUS_REJECTED,
    STAGING_VERSION,
    ACTIVATION_NOT_REQUESTED,
    ACTIVATION_BLOCKED,
    StagedCertifiedSkillEntry,
)

_CERT_STATUS_READY = "CERTIFIED_SKILL_READY"
_CERT_STATUS_WARN = "CERTIFIED_SKILL_WARN"
_REQUIRED_LIFECYCLE_TRANSITION = "SANDBOX_SKILL -> CERTIFIED_SKILL"

_STAGED_BY = "aims_certified_skill_registry_staging_workflow_v1"


def _make_staged_id(certified_skill_id: str) -> str:
    token = hashlib.sha1(f"staged-{certified_skill_id}".encode()).hexdigest()[:10]
    return f"staged-{token}"


def _check_rejection_reasons(pkg: dict[str, Any]) -> list[str]:
    """Return a list of rejection reasons for a package that cannot be staged."""
    reasons: list[str] = []

    if pkg.get("self_approval_allowed") is not False:
        reasons.append("self_approval_allowed is not False")
    if pkg.get("runtime_activation_allowed") is not False:
        reasons.append("runtime_activation_allowed is not False")
    if pkg.get("active_runtime_requested") is not False:
        reasons.append("active_runtime_requested is not False")
    if pkg.get("lifecycle_transition") != _REQUIRED_LIFECYCLE_TRANSITION:
        reasons.append(
            f"lifecycle_transition is not {_REQUIRED_LIFECYCLE_TRANSITION!r}"
        )
    if "ACTIVE_RUNTIME_SKILL" in str(pkg.get("lifecycle_transition", "")):
        reasons.append("lifecycle_transition references ACTIVE_RUNTIME_SKILL")
    if not pkg.get("rollback_plan"):
        reasons.append("missing rollback_plan")
    if not pkg.get("deprecation_plan"):
        reasons.append("missing deprecation_plan")

    invariants = pkg.get("safety_invariants", {})
    for key in STAGING_REQUIRED_INVARIANTS:
        if invariants.get(key) is not True:
            reasons.append(f"safety_invariants[{key!r}] is not True")

    gates = pkg.get("gates_required_before_runtime", [])
    for gate in STAGING_GATES_ALWAYS_REQUIRED:
        if gate not in gates:
            reasons.append(f"missing required gate: {gate!r}")

    if pkg.get("model_related") and STAGING_GATE_TRAINI not in gates:
        reasons.append(f"model_related package missing gate: {STAGING_GATE_TRAINI!r}")

    return reasons


def stage_package(
    pkg: dict[str, Any],
    staged_at: str,
) -> tuple[StagedCertifiedSkillEntry | None, dict[str, Any] | None]:
    """
    Attempt to stage a single certified package.

    Returns (entry, None) on success or (None, rejection_record) on failure.
    """
    cert_status = pkg.get("certification_status", "")

    # Only READY and WARN are eligible
    if cert_status not in (_CERT_STATUS_READY, _CERT_STATUS_WARN):
        return None, {
            "certified_skill_id": pkg.get("certified_skill_id"),
            "candidate_skill_id": pkg.get("candidate_skill_id"),
            "certification_status": cert_status,
            "reason": f"certification_status {cert_status!r} is not eligible for staging",
        }

    rejection_reasons = _check_rejection_reasons(pkg)
    certified_skill_id = pkg.get("certified_skill_id", "")

    if rejection_reasons:
        return None, {
            "certified_skill_id": certified_skill_id,
            "candidate_skill_id": pkg.get("candidate_skill_id"),
            "certification_status": cert_status,
            "reason": "; ".join(rejection_reasons),
            "rejection_reasons": rejection_reasons,
        }

    staged_id = _make_staged_id(certified_skill_id)

    staging_status = (
        STAGING_STATUS_REVIEW if cert_status == _CERT_STATUS_READY
        else STAGING_STATUS_WARN
    )

    # activation_blockers — list all gates that must be cleared
    activation_blockers = list(pkg.get("gates_required_before_runtime", []))

    activation_request_status = ACTIVATION_BLOCKED if activation_blockers else ACTIVATION_NOT_REQUESTED

    certification_refs = [
        f"certified_skill_packages.json#{certified_skill_id}",
        f"certification_report.json#{certified_skill_id}",
    ]

    entry = StagedCertifiedSkillEntry(
        staged_skill_id=staged_id,
        certified_skill_id=certified_skill_id,
        candidate_skill_id=pkg.get("candidate_skill_id", ""),
        owner_agent_id=pkg.get("owner_agent_id", ""),
        skill_domain=pkg.get("skill_domain", ""),
        proposed_name=pkg.get("proposed_name", ""),
        lifecycle_state=STAGED_LIFECYCLE_STATE,
        staging_status=staging_status,
        certification_refs=certification_refs,
        evidence_pack_refs=list(pkg.get("evidence_pack_refs", [])),
        required_runtime_gates=list(pkg.get("gates_required_before_runtime", [])),
        safety_invariants=dict(pkg.get("safety_invariants", {})),
        rollback_plan=pkg.get("rollback_plan", ""),
        deprecation_plan=pkg.get("deprecation_plan", ""),
        runtime_activation_allowed=False,
        self_approval_allowed=False,
        active_runtime_requested=False,
        activation_request_status=activation_request_status,
        activation_blockers=activation_blockers,
        staged_at=staged_at,
        staged_by=_STAGED_BY,
        model_related=bool(pkg.get("model_related")),
        production_related=bool(pkg.get("production_related")),
        staging_version=STAGING_VERSION,
        metadata=dict(pkg.get("metadata", {})),
    )
    return entry, None


def build_staged_registry(
    certified_packages: list[dict[str, Any]],
) -> tuple[list[StagedCertifiedSkillEntry], list[dict[str, Any]]]:
    """
    Stage all eligible certified packages.

    Returns (staged_entries, rejected_records).
    """
    staged_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entries: list[StagedCertifiedSkillEntry] = []
    rejected: list[dict[str, Any]] = []

    for pkg in certified_packages:
        entry, rejection = stage_package(pkg, staged_at)
        if entry is not None:
            entries.append(entry)
        else:
            rejected.append(rejection)

    return entries, rejected


def load_certified_packages(packages_path: pathlib.Path) -> list[dict[str, Any]]:
    if not packages_path.exists():
        raise FileNotFoundError(f"Certified packages file not found: {packages_path}")
    data = json.loads(packages_path.read_text(encoding="utf-8"))
    return data.get("packages", [])
