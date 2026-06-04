from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RecoveryFailureRecord:
    failure_id: str
    run_id: str
    cycle_id: str
    task_id: str
    step_id: str
    detected_at: str
    failure_type: str
    severity: str
    affected_service: str
    affected_agent: str
    expected_state: str
    actual_state: str
    active_certification_context: dict[str, Any]
    scheduler_context: dict[str, Any]
    evidence_paths: list[str]
    suspected_root_cause: str
    safe_to_auto_repair: bool
    requires_poli_approval: bool
    recommended_repair: str
    retry_count: int
    max_retries: int = 5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecoveryOrchestrator:
    """Failure classification + policy mapping for autonomous recovery.

    This layer is provider-agnostic and only works with run/cycle/task state.
    """

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self.run_root.mkdir(parents=True, exist_ok=True)

    def classify_failure(self, *, failure_type: str, affected_service: str, required_by_active_cert: bool, scheduler_intentional_stop: bool) -> dict[str, Any]:
        severity = "WARN"
        policy_class = "QUEUE_OR_RESCHEDULE"
        recommended = "retry_transient_network_tool_call"

        if failure_type in {"SECRET_EXPOSURE_RISK", "SLOT32_SLOT120_CONFLICT"}:
            severity = "CRITICAL"
            policy_class = "FORBIDDEN"
            recommended = "escalate_security_policy"
        elif failure_type in {"RESOURCE_WINDOW_CONFLICT", "HEAVY_TRAINING_CONFLICT"}:
            severity = "PARTIAL"
            policy_class = "QUEUE_OR_RESCHEDULE"
            recommended = "queue_after_active_run"
        elif failure_type in {"SERVICE_NOT_UP", "ALWAYS_ON_NOT_UP"}:
            if scheduler_intentional_stop and not required_by_active_cert:
                severity = "INFO"
                policy_class = "QUEUE_OR_RESCHEDULE"
                recommended = "skip_as_policy_expected"
            elif required_by_active_cert:
                severity = "BLOCKER"
                policy_class = "AUTO_ALLOWED"
                recommended = "start_required_service_if_safe"
            else:
                severity = "WARN"
                policy_class = "QUEUE_OR_RESCHEDULE"
                recommended = "reschedule_to_safe_window"
        elif failure_type in {"CONTROL_PLANE_GAP", "MISSING_EVIDENCE"}:
            severity = "BLOCKER"
            policy_class = "AUTO_ALLOWED"
            recommended = "rerun_transient_check"

        if affected_service in {"axi-bot", "omi-bot"} and required_by_active_cert:
            # Start may be allowed; restart remains approval-required.
            policy_class = "AUTO_ALLOWED"

        return {
            "failure_type": failure_type,
            "severity": severity,
            "policy_class": policy_class,
            "recommended_repair": recommended,
        }

    def build_failure_record(
        self,
        *,
        run_id: str,
        cycle_id: str,
        task_id: str,
        step_id: str,
        failure_type: str,
        affected_service: str,
        affected_agent: str,
        expected_state: str,
        actual_state: str,
        active_certification_context: dict[str, Any],
        scheduler_context: dict[str, Any],
        evidence_paths: list[str],
        suspected_root_cause: str,
        policy: dict[str, Any],
        retry_count: int = 0,
        max_retries: int = 5,
    ) -> RecoveryFailureRecord:
        failure_id = f"failure_{run_id}_{cycle_id}_{step_id}_{retry_count}"
        safe_to_auto = policy.get("policy_class") == "AUTO_ALLOWED"
        requires_poli = policy.get("policy_class") == "APPROVAL_REQUIRED"
        return RecoveryFailureRecord(
            failure_id=failure_id,
            run_id=run_id,
            cycle_id=cycle_id,
            task_id=task_id,
            step_id=step_id,
            detected_at=now_iso(),
            failure_type=failure_type,
            severity=str(policy.get("severity", "WARN")),
            affected_service=affected_service,
            affected_agent=affected_agent,
            expected_state=expected_state,
            actual_state=actual_state,
            active_certification_context=active_certification_context,
            scheduler_context=scheduler_context,
            evidence_paths=evidence_paths,
            suspected_root_cause=suspected_root_cause,
            safe_to_auto_repair=safe_to_auto,
            requires_poli_approval=requires_poli,
            recommended_repair=str(policy.get("recommended_repair", "")),
            retry_count=retry_count,
            max_retries=max_retries,
        )
