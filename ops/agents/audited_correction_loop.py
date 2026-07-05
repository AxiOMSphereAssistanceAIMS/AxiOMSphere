"""
audited_correction_loop.py

Orchestrates: actor output → self-check → Codex audit → verifier → learning record.

Does NOT grant PASS — only the deterministic verifier may do that.
Does NOT write learning events from unverified claims.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ops.agents.codex_auditor_adapter import (
    CodexAuditRequest,
    CodexAuditResult,
    run_codex_audit,
)
from ops.agents.model_self_check import SelfCheckResult, run_self_check
from ops.agents.verified_learning_event_recorder import (
    record_learning_event,
    LearningEventInput,
)


@dataclass
class AuditedCorrectionResult:
    status: str                    # VERIFIED_PASS | VERIFIED_FAIL | PARTIAL | BLOCKED
    iterations: int
    self_check_status: str
    codex_audit_status: str
    verifier_status: str
    learning_events_written: int
    evidence_dir: str


def _has_blocking_codex_finding(audit: CodexAuditResult) -> bool:
    return any(f.severity == "BLOCKING" for f in audit.findings)


def _run_verifier(task_context: dict) -> dict:
    """
    Minimal verifier stub. In production, replace with post_state_verifier
    or pytest runner. Returns dict with status and evidence.
    """
    verifier_fn = task_context.get("verifier_fn")
    if callable(verifier_fn):
        try:
            return verifier_fn(task_context)
        except Exception as exc:
            return {"status": "VERIFIED_FAIL", "error": str(exc)}

    # Fallback: check for pre-supplied verifier_result
    pre = task_context.get("verifier_result")
    if pre:
        return pre

    # No verifier available
    return {"status": "VERIFIER_UNAVAILABLE", "note": "No verifier_fn or verifier_result provided"}


def run_audited_correction_loop(
    task_context: dict,
    max_iterations: int = 3,
) -> AuditedCorrectionResult:
    """
    Run the audited correction loop for a single task.

    task_context keys:
        task_id         : str
        objective       : str
        user_request    : str
        actor_output    : str  (mutable — updated by correction_fn each iteration)
        action_results  : list[dict]
        policy_context  : dict
        files_changed   : list[str]
        evidence_files  : list[str]
        test_logs       : list[str]
        constraints     : list[str]
        evidence_dir    : str
        correction_fn   : callable(task_context, findings) -> str | None
        verifier_fn     : callable(task_context) -> dict | None
    """
    ev_dir = task_context.get("evidence_dir", "aims_workspace/self_learning/inbox")
    Path(ev_dir).mkdir(parents=True, exist_ok=True)

    iterations = 0
    self_check_status = "NOT_RUN"
    codex_audit_status = "NOT_RUN"
    verifier_status = "NOT_RUN"
    learning_events = 0
    initial_actor_output = task_context.get("actor_output", "")

    for iteration in range(1, max_iterations + 1):
        iterations = iteration
        actor_output = task_context.get("actor_output", "")

        # Step 1: Self-check
        self_check = run_self_check(
            user_request=task_context.get("user_request", ""),
            actor_output=actor_output,
            action_results=task_context.get("action_results", []),
            policy_context=task_context.get("policy_context", {}),
        )
        self_check_status = self_check.status

        # Step 2: Codex audit
        audit_request = CodexAuditRequest(
            task_id=task_context.get("task_id", "unknown"),
            objective=task_context.get("objective", ""),
            files_changed=task_context.get("files_changed", []),
            evidence_files=task_context.get("evidence_files", []),
            test_logs=task_context.get("test_logs", []),
            actor_output=actor_output,
            self_check_output=json.dumps({
                "status": self_check.status,
                "findings": self_check.findings,
            }),
            constraints=task_context.get("constraints", []),
        )
        codex_result = run_codex_audit(audit_request, ev_dir)
        codex_audit_status = codex_result.status

        # Check if both self-check and Codex are clean
        self_check_clean = self_check.status == "PASS"
        codex_clean = codex_result.status in ("PASSED", "SKIPPED")

        if self_check_clean and codex_clean:
            break  # proceed to verifier

        # Attempt correction if correction_fn provided
        correction_fn = task_context.get("correction_fn")
        if callable(correction_fn):
            all_findings = list(self_check.findings)
            for f in codex_result.findings:
                all_findings.append(f"{f.severity}: {f.finding}")
            new_output = correction_fn(task_context, all_findings)
            if new_output:
                task_context["actor_output"] = new_output
        else:
            # No correction function — cannot improve, stop
            break

    # Step 3: Run deterministic verifier
    verifier_result = _run_verifier(task_context)
    verifier_status = verifier_result.get("status", "VERIFIER_UNAVAILABLE")

    # Step 4: Record learning event if applicable
    if self_check.learning_candidate and verifier_status not in ("VERIFIER_UNAVAILABLE",):
        event = LearningEventInput(
            task_id=task_context.get("task_id", "unknown"),
            user_request=task_context.get("user_request", ""),
            actor_initial_output=initial_actor_output,
            actor_final_output=task_context.get("actor_output", ""),
            self_check_result={
                "status": self_check.status,
                "mistake_class": self_check.mistake_class,
                "findings": self_check.findings,
            },
            codex_audit_result={
                "status": codex_result.status,
                "findings": [
                    {"severity": f.severity, "category": f.category,
                     "finding": f.finding, "recommendation": f.recommendation}
                    for f in codex_result.findings
                ],
            },
            verifier_result=verifier_result,
            correction_summary=(
                "Actor output corrected after self-check/Codex findings"
                if initial_actor_output != task_context.get("actor_output", "")
                else "No correction applied"
            ),
            mistake_class=self_check.mistake_class,
            evidence_dir=ev_dir,
        )
        record_learning_event(event)
        learning_events += 1

    # Determine final status
    blocking_unresolved = _has_blocking_codex_finding(codex_result) and iterations >= max_iterations

    if blocking_unresolved:
        final_status = "BLOCKED"
    elif verifier_status == "VERIFIED_PASS":
        final_status = "VERIFIED_PASS"
    elif verifier_status == "VERIFIED_FAIL":
        final_status = "VERIFIED_FAIL"
    elif verifier_status == "VERIFIER_UNAVAILABLE":
        # Partial: self-check/Codex ran but no verifier
        final_status = "PARTIAL"
    else:
        final_status = "PARTIAL"

    return AuditedCorrectionResult(
        status=final_status,
        iterations=iterations,
        self_check_status=self_check_status,
        codex_audit_status=codex_audit_status,
        verifier_status=verifier_status,
        learning_events_written=learning_events,
        evidence_dir=ev_dir,
    )
