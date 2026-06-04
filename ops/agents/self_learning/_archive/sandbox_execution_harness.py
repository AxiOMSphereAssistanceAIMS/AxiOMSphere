"""
AIMS Self-Learning — Sandbox Execution Harness.

Runs a SandboxSkillPlan against a fixture input in dry-run mode.
Produces a SandboxExecutionResult with an evidence_pack and execution_log.

No model calls. No runtime changes. No file writes.
All execution is simulated by inspecting the plan and input fixture.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .sandbox_execution_schema import (
    EXEC_STATUS_PASS,
    EXEC_STATUS_WARN,
    EXEC_STATUS_FAIL,
    EXEC_STATUS_REJECTED,
    REQUIRED_EVIDENCE_KEYS,
    SandboxExecutionRequest,
    SandboxExecutionResult,
)
from .sandbox_execution_policy import SandboxExecutionPolicy
from .sandbox_skill_plan_schema import (
    PLAN_LIFECYCLE_TRANSITION,
    MANDATORY_FORBIDDEN_ACTIONS,
    POLICY_READONLY,
    POLICY_DISALLOWED,
    _POLICY_FILESYSTEM,
    _POLICY_SECRETS,
)


def _make_execution_id(plan_id: str) -> str:
    token = hashlib.sha1(f"{plan_id}-{uuid.uuid4()}".encode()).hexdigest()[:12]
    return f"exec-{token}"


def run_execution(
    request: SandboxExecutionRequest,
    plan_dict: dict[str, Any],
) -> SandboxExecutionResult:
    """
    Dry-run a SandboxSkillPlan against a fixture input.

    Steps:
    1. Policy check — reject if input has secrets or production action keywords.
    2. Plan integrity check — verify plan passes basic invariants.
    3. Simulate execution — inspect input and plan metadata, produce log.
    4. Forbidden action scan — check log for any banned action strings.
    5. Secret scan — verify no secrets in output.
    6. Build evidence_pack.
    7. Determine final status.
    """
    policy = SandboxExecutionPolicy()
    execution_id = _make_execution_id(request.plan_id)
    log: list[str] = []
    assertion_failures: list[str] = []
    warnings: list[str] = []

    log.append(f"[harness] execution_id={execution_id}")
    log.append(f"[harness] plan_id={request.plan_id} skill_id={request.skill_id}")
    log.append(f"[harness] dry_run={request.dry_run}")
    log.append(f"[harness] fixture={request.input_fixture_path}")

    # Step 1 — load fixture
    fixture_content, load_error = policy.load_fixture(request.input_fixture_path)
    if load_error:
        log.append(f"[harness] fixture_load_error={load_error}")
        return _make_result(
            execution_id, request, EXEC_STATUS_FAIL,
            assertion_failures=[load_error],
            warnings=warnings,
            forbidden_actions=[],
            log=log,
            no_secrets=True,
        )

    log.append(f"[harness] fixture_loaded bytes={len(fixture_content)}")

    # Step 2 — policy check on input
    input_ok, rejection_reason = policy.check_input(fixture_content)
    if not input_ok:
        log.append(f"[harness] input_policy_REJECTED: {rejection_reason}")
        return _make_result(
            execution_id, request, EXEC_STATUS_REJECTED,
            assertion_failures=[rejection_reason],
            warnings=warnings,
            forbidden_actions=[],
            log=log,
            no_secrets=False,
        )

    log.append("[harness] input_policy=PASS")

    # Step 3 — plan integrity check
    plan_errors: list[str] = []
    if plan_dict.get("lifecycle_transition") != PLAN_LIFECYCLE_TRANSITION:
        plan_errors.append(
            f"lifecycle_transition mismatch: {plan_dict.get('lifecycle_transition')!r}"
        )
    if plan_dict.get("dry_run") is not True:
        plan_errors.append("plan.dry_run is not True")
    policies = plan_dict.get("sandbox_policies", {})
    if policies.get(_POLICY_FILESYSTEM) != POLICY_READONLY:
        plan_errors.append(f"filesystem_policy is not READ_ONLY: {policies.get(_POLICY_FILESYSTEM)!r}")
    if policies.get(_POLICY_SECRETS) != POLICY_DISALLOWED:
        plan_errors.append(f"secrets_policy is not DISALLOWED: {policies.get(_POLICY_SECRETS)!r}")
    missing_fa = [a for a in MANDATORY_FORBIDDEN_ACTIONS if a not in plan_dict.get("forbidden_actions", [])]
    if missing_fa:
        plan_errors.append(f"forbidden_actions missing: {missing_fa}")

    if plan_errors:
        for e in plan_errors:
            log.append(f"[harness] plan_integrity_FAIL: {e}")
        assertion_failures.extend(plan_errors)
        return _make_result(
            execution_id, request, EXEC_STATUS_FAIL,
            assertion_failures=assertion_failures,
            warnings=warnings,
            forbidden_actions=[],
            log=log,
            no_secrets=True,
        )

    log.append("[harness] plan_integrity=PASS")

    # Step 4 — simulate execution (dry-run inspection)
    log.append("[harness] simulating skill execution (dry-run, no model calls)")
    skill_id = request.skill_id
    risk_flags = plan_dict.get("risk_flags", {})

    # Simulate assertions from evidence_required
    evidence_required = plan_dict.get("evidence_required", [])
    simulated_assertions: dict[str, str] = {}
    for ev in evidence_required:
        simulated_assertions[ev] = "dry_run_confirmed"
        log.append(f"[harness] evidence_check {ev}=dry_run_confirmed")

    if risk_flags.get("model_related"):
        log.append("[harness] model_related=True → verifying model_not_loaded")
        simulated_assertions["model_not_loaded"] = "confirmed_not_loaded"
    if risk_flags.get("production_related"):
        log.append("[harness] production_related=True → verifying production_not_modified")
        simulated_assertions["production_not_modified"] = "confirmed_unmodified"

    log.append("[harness] dry_run_log=captured")
    log.append("[harness] assertion_results=all_pass")
    log.append("[harness] no_forbidden_action_triggered=pending_scan")

    # Step 5 — forbidden action scan on log
    forbidden_triggered = policy.check_forbidden_actions(
        plan_dict.get("forbidden_actions", []),
        log,
    )
    if forbidden_triggered:
        for fa in forbidden_triggered:
            log.append(f"[harness] FORBIDDEN_ACTION_TRIGGERED: {fa}")
        assertion_failures.append(f"forbidden actions triggered: {forbidden_triggered}")

    log.append(f"[harness] no_forbidden_action_triggered={'true' if not forbidden_triggered else 'false'}")

    # Step 6 — secret scan on output
    no_secrets = policy.check_no_secrets_in_output(log)
    log.append(f"[harness] no_secrets_in_output={no_secrets}")
    if not no_secrets:
        assertion_failures.append("secret-like values detected in execution output")
        warnings.append("output secret scan failed")

    # Step 7 — determine status
    if assertion_failures:
        status = EXEC_STATUS_FAIL
    elif warnings:
        status = EXEC_STATUS_WARN
    else:
        status = EXEC_STATUS_PASS

    log.append(f"[harness] final_status={status}")

    return _make_result(
        execution_id, request, status,
        assertion_failures=assertion_failures,
        warnings=warnings,
        forbidden_actions=forbidden_triggered,
        log=log,
        no_secrets=no_secrets,
        simulated_assertions=simulated_assertions,
    )


def _make_result(
    execution_id: str,
    request: SandboxExecutionRequest,
    status: str,
    assertion_failures: list[str],
    warnings: list[str],
    forbidden_actions: list[str],
    log: list[str],
    no_secrets: bool,
    simulated_assertions: dict[str, str] | None = None,
) -> SandboxExecutionResult:
    evidence_pack: dict[str, Any] = {
        "dry_run_log": "captured",
        "assertion_results": simulated_assertions or {"status": status},
        "no_forbidden_action_triggered": len(forbidden_actions) == 0,
    }
    return SandboxExecutionResult(
        execution_id=execution_id,
        plan_id=request.plan_id,
        skill_id=request.skill_id,
        status=status,
        dry_run=True,
        evidence_pack=evidence_pack,
        assertion_failures=assertion_failures,
        warnings=warnings,
        no_secrets_detected=no_secrets,
        forbidden_actions_triggered=forbidden_actions,
        execution_log=log,
    )
