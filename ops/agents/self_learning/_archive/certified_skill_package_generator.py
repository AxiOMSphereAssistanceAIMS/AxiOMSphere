"""
AIMS Self-Learning — Certified Skill Package Generator.

Converts SANDBOX_PASS execution results into CertifiedSkillPackage objects.
SANDBOX_WARN/SANDBOX_FAIL/REJECTED_UNSAFE executions are skipped or flagged.

No model calls, no runtime changes, no service calls.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
from typing import Any

from .certified_skill_schema import (
    CERT_LIFECYCLE_TRANSITION,
    CERT_STATUS_READY,
    CERT_STATUS_WARN,
    CERT_STATUS_REJECTED,
    CERT_VERSION,
    GATES_ALWAYS_REQUIRED_BEFORE_RUNTIME,
    GATE_TRAINI_RUNTIME,
    REQUIRED_SAFETY_INVARIANTS,
    CertifiedSkillPackage,
)
from .sandbox_execution_schema import (
    EXEC_STATUS_PASS,
    EXEC_STATUS_WARN,
)

_SAFETY_INVARIANTS: dict[str, bool] = {k: True for k in REQUIRED_SAFETY_INVARIANTS}


def _make_certified_id(execution_id: str, skill_id: str) -> str:
    token = hashlib.sha1(f"{execution_id}-{skill_id}".encode()).hexdigest()[:10]
    return f"cert-{token}"


def _make_validator_signature(pkg_id: str, execution_id: str) -> str:
    digest = hashlib.sha256(f"{pkg_id}:{execution_id}:{CERT_VERSION}".encode()).hexdigest()[:16]
    return f"aims-cert-v{CERT_VERSION}-{digest}"


def _resolve_skill_domain(skill_id: str) -> str:
    if "doc" in skill_id or "ocr" in skill_id:
        return "document_management"
    if "repair" in skill_id or "debug" in skill_id or "tdd" in skill_id:
        return "repair_diagnostics"
    if "model" in skill_id or "lm-eval" in skill_id or "vllm" in skill_id:
        return "model_operations"
    if "codebase" in skill_id or "pr" in skill_id:
        return "code_review"
    if "subagent" in skill_id or "task" in skill_id:
        return "task_orchestration"
    return "general"


def _build_rollback_plan(skill_id: str, skill_domain: str) -> str:
    return (
        f"To roll back certified skill '{skill_id}' ({skill_domain}): "
        "(1) Set certification_status to CERTIFICATION_REJECTED in registry. "
        "(2) Remove from certified_skill_packages.json. "
        "(3) Notify owner_agent_id via Argus event. "
        "(4) Archive evidence pack to aims_workspace/agent_self_learning/archive/. "
        "(5) No runtime rollback needed — skill was never activated."
    )


def _build_deprecation_plan(skill_id: str) -> str:
    return (
        f"Deprecation plan for '{skill_id}': "
        "(1) Transition certification_status to CERTIFICATION_REJECTED. "
        "(2) Log deprecation reason in certification_report.json. "
        "(3) Retain evidence pack for audit trail for 90 days. "
        "(4) Block re-promotion unless new SANDBOX_PASS evidence is produced. "
        "(5) skill lifecycle_state transitions to DEPRECATED_SKILL only after "
        "explicit_AIMS_activation_decision gate approval."
    )


def generate_package(
    execution_result: dict[str, Any],
    evidence_pack: dict[str, Any],
    created_at: str,
) -> CertifiedSkillPackage | None:
    """
    Generate a CertifiedSkillPackage from a single execution result.

    Returns None for REJECTED_UNSAFE or SANDBOX_FAIL.
    Returns a WARN-status package for SANDBOX_WARN.
    Returns a READY-status package for SANDBOX_PASS.
    """
    exec_status = execution_result.get("status")
    execution_id = execution_result.get("execution_id", "")
    plan_id = execution_result.get("plan_id", "")
    skill_id = execution_result.get("skill_id", "")

    # Never certify unsafe or failed executions
    if exec_status in ("REJECTED_UNSAFE", "SANDBOX_FAIL"):
        return None

    if exec_status == EXEC_STATUS_PASS:
        cert_status = CERT_STATUS_READY
    elif exec_status == EXEC_STATUS_WARN:
        cert_status = CERT_STATUS_WARN
    else:
        return None

    certified_id = _make_certified_id(execution_id, skill_id)
    skill_domain = _resolve_skill_domain(skill_id)

    # Gather evidence refs from execution result and evidence pack
    ep = evidence_pack.get(execution_id, {})
    evidence_refs: list[str] = []
    for key in ("dry_run_log", "assertion_results", "no_forbidden_action_triggered"):
        if key in ep:
            evidence_refs.append(f"{execution_id}:{key}")
    if not evidence_refs:
        evidence_refs = [f"{execution_id}:evidence_pack"]

    sandbox_result_refs = [
        f"sandbox_execution_report.json#{execution_id}",
        f"sandbox_execution_evidence_pack.json#{execution_id}",
    ]

    # Determine risk flags from result metadata
    model_related = bool(
        execution_result.get("metadata", {}).get("model_related")
        or "model" in skill_id
        or "lm-eval" in skill_id
        or "vllm" in skill_id
    )
    production_related = bool(
        execution_result.get("metadata", {}).get("production_related")
    )

    # production_related packages are always WARN unless already WARN
    if production_related and cert_status == CERT_STATUS_READY:
        cert_status = CERT_STATUS_WARN

    # Gates required before any runtime activation
    gates_before_runtime = list(GATES_ALWAYS_REQUIRED_BEFORE_RUNTIME)
    if model_related:
        gates_before_runtime.append(GATE_TRAINI_RUNTIME)

    residual_risks: list[str] = []
    if model_related:
        residual_risks.append("model_policy_must_be_verified_at_activation")
    if production_related:
        residual_risks.append("production_impact_requires_explicit_review")
    if cert_status == CERT_STATUS_WARN:
        residual_risks.append("sandbox_warnings_present_require_resolution")

    rollback_plan = _build_rollback_plan(skill_id, skill_domain)
    deprecation_plan = _build_deprecation_plan(skill_id)

    validator_sig = _make_validator_signature(certified_id, execution_id)

    return CertifiedSkillPackage(
        certified_skill_id=certified_id,
        candidate_skill_id=skill_id,
        sandbox_plan_id=plan_id,
        execution_id=execution_id,
        owner_agent_id=execution_result.get("metadata", {}).get("owner_agent_id", ""),
        skill_domain=skill_domain,
        proposed_name=skill_id.replace("-", "_"),
        lifecycle_transition=CERT_LIFECYCLE_TRANSITION,
        certification_status=cert_status,
        evidence_pack_refs=evidence_refs,
        sandbox_result_refs=sandbox_result_refs,
        gates_passed=["argus_gate", "logi_gate", "qa_gate"],
        gates_required_before_runtime=gates_before_runtime,
        safety_invariants=dict(_SAFETY_INVARIANTS),
        residual_risks=residual_risks,
        rollback_plan=rollback_plan,
        deprecation_plan=deprecation_plan,
        runtime_activation_allowed=False,
        self_approval_allowed=False,
        active_runtime_requested=False,
        model_related=model_related,
        production_related=production_related,
        certification_created_at=created_at,
        certification_version=CERT_VERSION,
        validator_signature=validator_sig,
        metadata=execution_result.get("metadata", {}),
    )


def generate_packages(
    execution_results: list[dict[str, Any]],
    evidence_pack: dict[str, Any],
) -> tuple[list[CertifiedSkillPackage], list[dict[str, Any]]]:
    """
    Generate certification packages for all eligible executions.

    Returns (packages, skipped_entries).
    skipped_entries records executions that were not certified with their reason.
    """
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    packages: list[CertifiedSkillPackage] = []
    skipped: list[dict[str, Any]] = []

    for result in execution_results:
        pkg = generate_package(result, evidence_pack, created_at)
        if pkg is not None:
            packages.append(pkg)
        else:
            skipped.append({
                "execution_id": result.get("execution_id"),
                "skill_id": result.get("skill_id"),
                "status": result.get("status"),
                "reason": f"execution status {result.get('status')!r} is not eligible for certification",
            })

    return packages, skipped
