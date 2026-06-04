from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from repairman.repair_loop import RepairLoop
from repairman.repair_registry import StepExecution


LIVE_STATUSES = [
    "FAILURE_DETECTED",
    "REPAIR_POLICY_CLASSIFIED",
    "REPAIR_PLANNED",
    "REPAIR_EXECUTED",
    "REPAIR_VALIDATED",
    "RETRY_STARTED",
    "RETRY_PASS",
    "RETRY_FAIL",
    "RETRY_LIMIT_EXHAUSTED",
    "ESCALATED",
    "CONTINUE_RUN",
]


def run_live_repair_on_step_failure(
    *,
    run_dir: Path,
    run_id: str,
    cycle_id: str,
    task_id: str,
    step_id: str,
    owner_agent: str,
    executor: Callable[[StepExecution, int], dict[str, Any]],
    repair_executor: Callable[[str, StepExecution, Any], dict[str, Any]],
    validator: Callable[[StepExecution, int], dict[str, Any]],
    repair_type_selector: Callable[[Any], str],
    expected_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    loop = RepairLoop(run_dir=run_dir, task_id=task_id, owner_agent=owner_agent)

    step = StepExecution(
        step_id=step_id,
        task_id=task_id,
        owner_agent=owner_agent,
        executor="live_run_repair_bridge",
        command_or_callable="step_executor",
        expected_artifacts=expected_artifacts or [],
        acceptance_criteria=["Recovered step must validate PASS."],
        max_attempts=5,
    )

    out = loop.run_step(
        step,
        executor=executor,
        repair_executor=repair_executor,
        validator=validator,
        repair_type_selector=repair_type_selector,
    )

    history = out.retry_history
    status_trace = []
    if history:
        status_trace.append("FAILURE_DETECTED")
        status_trace.append("REPAIR_POLICY_CLASSIFIED")
        status_trace.append("REPAIR_PLANNED")
        status_trace.append("REPAIR_EXECUTED")
        status_trace.append("REPAIR_VALIDATED")

    for h in history:
        status_trace.append("RETRY_STARTED")
        if h.get("status") == "PASS":
            status_trace.append("RETRY_PASS")
        else:
            status_trace.append("RETRY_FAIL")

    if out.status == "PASS":
        status_trace.append("CONTINUE_RUN")
    elif out.status == "RETRY_LIMIT_EXHAUSTED":
        status_trace.append("RETRY_LIMIT_EXHAUSTED")
        status_trace.append("ESCALATED")

    result = {
        "run_id": run_id,
        "cycle_id": cycle_id,
        "task_id": task_id,
        "step_id": step_id,
        "final_status": out.status,
        "attempt_count": out.attempt_count,
        "retry_history": history,
        "repair_record": out.repair_record,
        "failure_record": out.failure_record,
        "status_trace": status_trace,
        "live_statuses_supported": LIVE_STATUSES,
        "continue_run": out.status == "PASS",
    }
    (run_dir / f"{step_id}_live_repair_bridge_result.json").write_text(
        __import__("json").dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return result
