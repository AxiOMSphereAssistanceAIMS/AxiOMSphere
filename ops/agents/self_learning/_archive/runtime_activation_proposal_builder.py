"""
AIMS Self-Learning — Runtime Activation Proposal Builder.

Converts staged CERTIFIED_SKILL entries into RuntimeActivationProposal objects.
No activation occurs. No runtime registries are modified.
No model calls, no service calls.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
from typing import Any

from .runtime_activation_proposal_schema import (
    PROPOSAL_CURRENT_STATE,
    PROPOSAL_TARGET_STATE,
    PROPOSAL_STATUS_BLOCKED,
    PROPOSAL_STATUS_REJECTED,
    ACTIVATION_BLOCKED,
    REQUIRED_APPROVALS_BASE,
    APPROVAL_TRAINI,
    REQUIRED_RUNTIME_GATES,
    REQUIRED_SAFETY_INVARIANTS,
    FORBIDDEN_GOVERNORS,
    FORBIDDEN_DIRECT_CONTROLS,
    PROPOSAL_VERSION,
    RuntimeActivationProposal,
)

_STAGED_FOR_REVIEW = "STAGED_FOR_REVIEW"
_STAGED_WITH_WARNINGS = "STAGED_WITH_WARNINGS"
_CERTIFIED_SKILL = "CERTIFIED_SKILL"

_PROPOSED_BY = "aims_runtime_activation_proposal_workflow_v1"


def _make_proposal_id(staged_skill_id: str) -> str:
    token = hashlib.sha1(f"proposal-{staged_skill_id}".encode()).hexdigest()[:10]
    return f"prop-{token}"


def _build_deactivation_plan(skill_id: str, skill_domain: str) -> str:
    return (
        f"Deactivation plan for '{skill_id}' ({skill_domain}): "
        "(1) Remove skill from active registry via explicit_AIMS_activation_decision gate. "
        "(2) Drain in-flight requests before deregistering. "
        "(3) Notify owner_agent_id via Argus event. "
        "(4) Restore previous skill version or disable capability. "
        "(5) Verify system health via ArgusBot post-deactivation health check. "
        "(6) Archive activation record to aims_workspace/agent_self_learning/archive/."
    )


def _build_monitoring_plan(skill_id: str) -> str:
    return (
        f"Monitoring plan for '{skill_id}': "
        "(1) ArgusBot monitors skill invocation rate and error rate. "
        "(2) Alert threshold: error_rate > 5% over 5-minute window. "
        "(3) Log all skill activations to aims_workspace/agent_self_learning/activation_log/. "
        "(4) Weekly audit of skill behavior against certified evidence pack. "
        "(5) Immediate deactivation trigger if forbidden action detected at runtime."
    )


def _build_rate_limit_plan(skill_id: str, production_related: bool) -> str:
    limit = "10 invocations/minute" if production_related else "50 invocations/minute"
    return (
        f"Rate limit plan for '{skill_id}': "
        f"Max {limit} per agent. "
        "(1) Enforce via Logi task ledger gate. "
        "(2) Backpressure: queue overflow → BLOCKED state. "
        "(3) Rate limit violations logged to Argus. "
        "(4) Exceed 3 violations → automatic suspension pending review."
    )


def _build_blast_radius(skill_domain: str, production_related: bool, model_related: bool) -> str:
    scope = []
    if production_related:
        scope.append("production_document_pipeline")
    if model_related:
        scope.append("model_inference_layer")
    scope.append(f"{skill_domain}_subsystem")
    return (
        f"Blast radius: limited to {', '.join(scope)}. "
        "No cross-subsystem cascade permitted without explicit gate approval. "
        "DGX slot32/slot120 policy enforced — skill may not affect 120B model slots."
    )


def _build_validation_commands(skill_id: str, skill_domain: str) -> list[str]:
    return [
        f"PYTHONPATH=ops python3 ops/evals/aims_certified_skill_registry_staging_smoke.py",
        f"PYTHONPATH=ops python3 ops/evals/aims_runtime_activation_proposal_smoke.py",
        f"grep -r 'ACTIVE_RUNTIME_SKILL' aims_workspace/agent_self_learning/staged_registry/ || echo 'clean'",
        f"python3 -c \"import json; d=json.load(open('aims_workspace/agent_self_learning/runtime_activation_proposals/runtime_activation_proposals.json')); assert all(not p['runtime_activation_allowed'] for p in d['proposals']), 'FAIL'\"",
    ]


def _build_post_activation_checks(skill_id: str) -> list[str]:
    return [
        "ArgusBot health check: verify no forbidden actions triggered in first 100 invocations",
        "Logi task ledger: verify rate limits enforced",
        "QA agent: run regression smoke on affected subsystem",
        f"Verify '{skill_id}' appears in active registry with correct metadata",
        "Confirm rollback plan is staged and tested",
        "Monitor error rate for 24 hours post-activation",
    ]


def _check_rejection_reasons(entry: dict[str, Any]) -> list[str]:
    reasons: list[str] = []

    if entry.get("self_approval_allowed") is not False:
        reasons.append("self_approval_allowed is not False")
    if entry.get("runtime_activation_allowed") is not False:
        reasons.append("runtime_activation_allowed is not False")
    if entry.get("active_runtime_requested") is not False:
        reasons.append("active_runtime_requested is not False")
    if not entry.get("rollback_plan"):
        reasons.append("missing rollback_plan")
    if not entry.get("deprecation_plan"):
        reasons.append("missing deprecation_plan")

    inv = entry.get("safety_invariants", {})
    for key in REQUIRED_SAFETY_INVARIANTS:
        if inv.get(key) is not True:
            reasons.append(f"safety_invariants[{key!r}] is not True")

    gates = entry.get("required_runtime_gates", [])
    for gate in ("argus_gate", "logi_gate", "qa_gate"):
        if gate not in gates:
            reasons.append(f"missing required gate: {gate!r}")

    # Forbidden governor check (empty owner_agent_id is permitted — defaults to pipeline)
    owner = str(entry.get("owner_agent_id", "")).lower()
    if any(fg in owner for fg in FORBIDDEN_GOVERNORS):
        reasons.append(f"owner_agent_id references forbidden governor: {owner!r}")

    return reasons


def build_proposal(
    entry: dict[str, Any],
    proposed_at: str,
) -> tuple[RuntimeActivationProposal | None, dict[str, Any] | None]:
    """
    Build a RuntimeActivationProposal from a staged skill entry.

    Returns (proposal, None) on success or (None, rejection_record) on failure.
    """
    staging_status = entry.get("staging_status", "")
    lifecycle_state = entry.get("lifecycle_state", "")

    if lifecycle_state != _CERTIFIED_SKILL or staging_status not in (
        _STAGED_FOR_REVIEW, _STAGED_WITH_WARNINGS
    ):
        return None, {
            "staged_skill_id": entry.get("staged_skill_id"),
            "certified_skill_id": entry.get("certified_skill_id"),
            "staging_status": staging_status,
            "reason": f"entry not eligible: lifecycle={lifecycle_state!r}, status={staging_status!r}",
        }

    rejection_reasons = _check_rejection_reasons(entry)
    staged_skill_id = entry.get("staged_skill_id", "")

    if rejection_reasons:
        return None, {
            "staged_skill_id": staged_skill_id,
            "certified_skill_id": entry.get("certified_skill_id"),
            "staging_status": staging_status,
            "reason": "; ".join(rejection_reasons),
            "rejection_reasons": rejection_reasons,
        }

    proposal_id = _make_proposal_id(staged_skill_id)
    model_related = bool(entry.get("model_related"))
    production_related = bool(entry.get("production_related"))
    skill_id = entry.get("candidate_skill_id", "")
    skill_domain = entry.get("skill_domain", "")

    required_approvals = list(REQUIRED_APPROVALS_BASE)
    if model_related:
        required_approvals.append(APPROVAL_TRAINI)

    required_gates = list(REQUIRED_RUNTIME_GATES)

    activation_blockers = required_approvals + required_gates

    safety_invariants = dict(entry.get("safety_invariants", {}))
    for key in REQUIRED_SAFETY_INVARIANTS:
        if key not in safety_invariants:
            safety_invariants[key] = True

    proposal = RuntimeActivationProposal(
        proposal_id=proposal_id,
        staged_skill_id=staged_skill_id,
        certified_skill_id=entry.get("certified_skill_id", ""),
        owner_agent_id=entry.get("owner_agent_id") or "aims_self_learning_pipeline",
        skill_domain=skill_domain,
        proposed_name=entry.get("proposed_name", ""),
        current_lifecycle_state=PROPOSAL_CURRENT_STATE,
        proposed_lifecycle_state=PROPOSAL_TARGET_STATE,
        proposal_status=PROPOSAL_STATUS_BLOCKED,
        activation_request_status=ACTIVATION_BLOCKED,
        required_approvals=required_approvals,
        required_runtime_gates=required_gates,
        safety_invariants=safety_invariants,
        rollback_plan=entry.get("rollback_plan", ""),
        deactivation_plan=_build_deactivation_plan(skill_id, skill_domain),
        monitoring_plan=_build_monitoring_plan(skill_id),
        rate_limit_plan=_build_rate_limit_plan(skill_id, production_related),
        blast_radius=_build_blast_radius(skill_domain, production_related, model_related),
        activation_blockers=activation_blockers,
        validation_commands_required=_build_validation_commands(skill_id, skill_domain),
        post_activation_checks_required=_build_post_activation_checks(skill_id),
        runtime_activation_allowed=False,
        self_approval_allowed=False,
        active_runtime_requested=False,
        production_related=production_related,
        model_related=model_related,
        proposed_at=proposed_at,
        proposed_by=_PROPOSED_BY,
        proposal_version=PROPOSAL_VERSION,
        metadata=dict(entry.get("metadata", {})),
    )
    return proposal, None


def build_proposals(
    staged_entries: list[dict[str, Any]],
) -> tuple[list[RuntimeActivationProposal], list[dict[str, Any]]]:
    """
    Build proposals for all eligible staged entries.

    Returns (proposals, rejected_records).
    """
    proposed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    proposals: list[RuntimeActivationProposal] = []
    rejected: list[dict[str, Any]] = []

    for entry in staged_entries:
        proposal, rejection = build_proposal(entry, proposed_at)
        if proposal is not None:
            proposals.append(proposal)
        else:
            rejected.append(rejection)

    return proposals, rejected


def load_staged_entries(staged_path: pathlib.Path) -> list[dict[str, Any]]:
    if not staged_path.exists():
        raise FileNotFoundError(f"Staged registry not found: {staged_path}")
    data = json.loads(staged_path.read_text(encoding="utf-8"))
    return data.get("staged_entries", [])
