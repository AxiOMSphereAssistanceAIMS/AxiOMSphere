"""M-008: Parallel Delegation Coordinator — split/ack/merge with closure evidence.

Dispatches a batch of DelegationTasks to their respective agents in parallel,
collects DelegationAcks, and merges results into a DelegationResult with a
persistent closure_evidence artifact.

Contract:
  - Every dispatched task receives a DelegationAck (ACCEPTED or FAILED)
  - Merge waits until all tasks finish or timeout expires
  - closure_evidence is written regardless of partial failure
  - DelegationResult.all_accepted is False if any task failed
"""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait, FIRST_EXCEPTION
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:
    from chain_closure.closure_schema import ClosureState
except ModuleNotFoundError:  # pragma: no cover - compatibility for PYTHONPATH=.
    from ops.chain_closure.closure_schema import ClosureState

DELEGATION_LOG_ROOT = Path(
    os.environ.get("ARGUS_CRASH_INCIDENT_DIR", "aims_workspace/runtime_incidents")
) / "delegation_batches"

DELEGATION_TIMEOUT_SEC = int(os.environ.get("AIMS_DELEGATION_TIMEOUT_SEC", "120"))
DELEGATION_EVIDENCE_FILENAME = "delegation_result_{batch_id}.json"
NO_PENDING_EVIDENCE_FILENAME = "no_pending_{plan_id}_{user_id}.json"


def _iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_no_pending_execution_evidence(plan_id: str, user_id: int) -> str:
    DELEGATION_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    path = DELEGATION_LOG_ROOT / NO_PENDING_EVIDENCE_FILENAME.format(plan_id=plan_id, user_id=user_id)
    data = {
        "plan_id": plan_id,
        "user_id": user_id,
        "status": "NO_PENDING_STEPS",
        "closure_state": ClosureState.COMPLETED_SUCCESSFULLY.value,
        "next_action": "no_action_required",
        "runtime_behavior_changed": True,
        "timestamp": _iso(),
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


@dataclass
class DelegationTask:
    agent: str
    payload: dict
    title: str = ""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


@dataclass
class DelegationAck:
    task_id: str
    agent: str
    status: str = "ACCEPTED"        # ACCEPTED | FAILED
    accepted_at: str = field(default_factory=_iso)
    result: str = ""
    finished_at: str = ""
    error: str = ""


@dataclass
class DelegationResult:
    batch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tasks: list[DelegationTask] = field(default_factory=list)
    acks: list[DelegationAck] = field(default_factory=list)
    all_accepted: bool = True
    failed_count: int = 0
    merged_result: str = ""
    closure_evidence_path: str = ""
    completed_at: str = field(default_factory=_iso)


def map_delegation_ack_to_closure_state(
    ack: DelegationAck,
    *,
    claim_supported: bool = True,
    retry_count: int = 0,
    max_retries: int = 1,
    repair_attempt_count: int = 0,
    max_repair_attempts: int = 1,
    approval_required: bool = False,
) -> str | None:
    """Map delegation ack outcome to Phase 1 closure states.

    Returns None when no terminal closure should be assigned yet.
    """
    if approval_required:
        return ClosureState.WAITING_FOR_HUMAN_APPROVAL.value

    if ack.status == "ACCEPTED":
        return (
            ClosureState.COMPLETED_SUCCESSFULLY.value
            if claim_supported
            else ClosureState.ESCALATED_WITH_REPORT.value
        )

    is_timeout = "timeout" in (ack.error or "").lower()
    exhausted = retry_count >= max_retries or repair_attempt_count >= max_repair_attempts
    if exhausted:
        return ClosureState.FAILED_AFTER_REPAIR_LIMIT_WITH_EVIDENCE.value
    if is_timeout:
        return ClosureState.ESCALATED_WITH_REPORT.value
    return None


def build_failure_projection(
    *,
    batch_id: str,
    ack: DelegationAck,
    closure_state: str | None,
    evidence_path: str,
    next_action: str,
    retry_count: int = 0,
    repair_attempt_count: int = 0,
    escalation_required: bool = False,
    dead_letter_required: bool = False,
    dead_letter_reason: str = "",
) -> dict:
    if dead_letter_required and not dead_letter_reason:
        raise ValueError("dead_letter_reason required when dead_letter_required=true")
    failure_type = "TIMEOUT" if "timeout" in (ack.error or "").lower() else "FAILED_ACK"
    return {
        "chain_id": batch_id,
        "step_id": ack.task_id,
        "agent": ack.agent,
        "failure_type": failure_type,
        "ack_status": ack.status,
        "closure_state": closure_state or "",
        "evidence_path": evidence_path,
        "next_action": next_action,
        "retry_count": retry_count,
        "repair_attempt_count": repair_attempt_count,
        "escalation_required": escalation_required,
        "dead_letter_required": dead_letter_required,
        "dead_letter_reason": dead_letter_reason,
    }


class DelegationCoordinator:
    """Dispatches tasks in parallel, collects acks, produces closure evidence."""

    def __init__(
        self,
        call_fn: Callable[[str, dict], str],
        timeout: int = DELEGATION_TIMEOUT_SEC,
        log_root: Path = DELEGATION_LOG_ROOT,
    ) -> None:
        self._call = call_fn
        self._timeout = timeout
        self._log_root = log_root

    def delegate_batch(self, tasks: list[DelegationTask]) -> DelegationResult:
        """Dispatch all tasks in parallel, collect acks, write closure evidence."""
        batch_id = uuid.uuid4().hex[:12]
        result = DelegationResult(batch_id=batch_id, tasks=list(tasks))

        if not tasks:
            result.merged_result = "No tasks to delegate."
            result.closure_evidence_path = self._write_evidence(result)
            return result

        futures: dict[Future, DelegationTask] = {}

        with ThreadPoolExecutor(max_workers=min(len(tasks), 8), thread_name_prefix="delegate") as pool:
            for task in tasks:
                fut = pool.submit(self._dispatch_one, task)
                futures[fut] = task

            done, not_done = wait(futures.keys(), timeout=self._timeout)
            for fut in not_done:
                fut.cancel()

        # Collect acks from completed futures only; build FAILED acks for timed-out ones.
        task_order = {t.task_id: i for i, t in enumerate(tasks)}
        acks: list[DelegationAck] = []
        for fut in done:
            acks.append(fut.result())
        for fut in not_done:
            t = futures[fut]
            acks.append(DelegationAck(
                task_id=t.task_id,
                agent=t.agent,
                status="FAILED",
                error=f"timeout after {self._timeout}s",
                finished_at=_iso(),
            ))
        acks.sort(key=lambda a: task_order.get(a.task_id, 999))

        failed = [a for a in acks if a.status == "FAILED"]
        result.acks = acks
        result.all_accepted = len(failed) == 0
        result.failed_count = len(failed)
        result.merged_result = self._merge_results(acks)
        result.completed_at = _iso()
        result.closure_evidence_path = self._write_evidence(result)
        return result

    def _dispatch_one(self, task: DelegationTask) -> DelegationAck:
        ack = DelegationAck(task_id=task.task_id, agent=task.agent)
        try:
            res = self._call(task.agent, task.payload)
            ack.result = str(res)[:2000]
            ack.status = "ACCEPTED"
        except Exception as exc:
            ack.status = "FAILED"
            ack.error = str(exc)[:500]
        finally:
            ack.finished_at = _iso()
        return ack

    def _merge_results(self, acks: list[DelegationAck]) -> str:
        lines = []
        for ack in acks:
            status_icon = "✅" if ack.status == "ACCEPTED" else "❌"
            lines.append(f"{status_icon} [{ack.agent}/{ack.task_id}] {ack.result[:200] or ack.error[:200]}")
        return "\n".join(lines)

    def _write_evidence(self, result: DelegationResult) -> str:
        self._log_root.mkdir(parents=True, exist_ok=True)
        filename = DELEGATION_EVIDENCE_FILENAME.format(batch_id=result.batch_id)
        path = self._log_root / filename
        failure_projections = []
        for ack in result.acks:
            if ack.status != "FAILED":
                continue
            closure_state = map_delegation_ack_to_closure_state(ack)
            escalation_required = closure_state in {
                ClosureState.ESCALATED_WITH_REPORT.value,
                ClosureState.FAILED_AFTER_REPAIR_LIMIT_WITH_EVIDENCE.value,
            }
            failure_projections.append(
                build_failure_projection(
                    batch_id=result.batch_id,
                    ack=ack,
                    closure_state=closure_state,
                    evidence_path=str(path),
                    next_action="retry_or_repair" if not escalation_required else "escalate_with_report",
                    escalation_required=escalation_required,
                    dead_letter_required=escalation_required,
                    dead_letter_reason=(
                        "timeout_finalized_by_coordinator"
                        if "timeout" in (ack.error or "").lower()
                        else "delegation_failure"
                    ),
                )
            )

        data = {
            "batch_id": result.batch_id,
            "all_accepted": result.all_accepted,
            "failed_count": result.failed_count,
            "task_count": len(result.tasks),
            "acks": [asdict(a) for a in result.acks],
            "merged_result": result.merged_result,
            "completed_at": result.completed_at,
            "timeout_outcome_final": True,
            "late_completion_policy": "late_completion_observed_without_status_overwrite",
            "failure_projections": failure_projections,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)
