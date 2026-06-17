"""Smoke tests for DelegationCoordinator (M-008) — logi_parallel_delegation_coordinator skill."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ops.logi.delegation_coordinator import (
    DELEGATION_TIMEOUT_SEC,
    DelegationAck,
    DelegationCoordinator,
    DelegationResult,
    DelegationTask,
    map_delegation_ack_to_closure_state,
    build_failure_projection,
    write_no_pending_execution_evidence,
)
from ops.logi.claim_evidence_verifier import get_verifier
from ops.chain_closure.closure_schema import ClosureState


# ── helpers ───────────────────────────────────────────────────────────────────

def _ok_call(agent: str, payload: dict) -> str:
    return f"OK: {agent} processed {payload.get('title', 'task')}"


def _fail_call(agent: str, payload: dict) -> str:
    raise RuntimeError(f"Agent {agent} refused task")


def _slow_call(agent: str, payload: dict) -> str:
    time.sleep(0.5)
    return "too late"


def _coordinator(call_fn=_ok_call, timeout: int = 10, tmp_path: Path | None = None) -> DelegationCoordinator:
    root = tmp_path or Path("/tmp/test_delegation_batches")
    return DelegationCoordinator(call_fn=call_fn, timeout=timeout, log_root=root)


# ── empty batch ──────────────────────────────────────────────────────────────

class TestEmptyBatch:
    def test_empty_batch_returns_result(self, tmp_path):
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([])
        assert isinstance(result, DelegationResult)

    def test_empty_batch_all_accepted(self, tmp_path):
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([])
        assert result.all_accepted is True
        assert result.failed_count == 0

    def test_empty_batch_writes_evidence(self, tmp_path):
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([])
        assert result.closure_evidence_path
        assert Path(result.closure_evidence_path).exists()

    def test_empty_batch_acks_empty(self, tmp_path):
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([])
        assert result.acks == []


# ── delegation ack contract ───────────────────────────────────────────────────

class TestDelegationAckContract:
    def test_every_task_gets_ack(self, tmp_path):
        tasks = [DelegationTask(agent=f"agent{i}", payload={"x": i}) for i in range(5)]
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch(tasks)
        assert len(result.acks) == len(tasks)

    def test_ack_has_task_id(self, tmp_path):
        task = DelegationTask(agent="omi", payload={"doc": "test"})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        ack = result.acks[0]
        assert ack.task_id == task.task_id

    def test_ack_has_agent(self, tmp_path):
        task = DelegationTask(agent="doci", payload={})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.acks[0].agent == "doci"

    def test_successful_ack_status_accepted(self, tmp_path):
        task = DelegationTask(agent="knomi", payload={"query": "test"})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.acks[0].status == "ACCEPTED"

    def test_successful_ack_has_result(self, tmp_path):
        task = DelegationTask(agent="knomi", payload={"query": "test"})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.acks[0].result

    def test_successful_ack_has_finished_at(self, tmp_path):
        task = DelegationTask(agent="omi", payload={})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.acks[0].finished_at


# ── failure handling ──────────────────────────────────────────────────────────

class TestFailureHandling:
    def test_failed_task_ack_status_failed(self, tmp_path):
        task = DelegationTask(agent="broken", payload={})
        coord = _coordinator(call_fn=_fail_call, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.acks[0].status == "FAILED"

    def test_failed_task_ack_has_error(self, tmp_path):
        task = DelegationTask(agent="broken", payload={})
        coord = _coordinator(call_fn=_fail_call, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert "refused" in result.acks[0].error

    def test_failed_task_all_accepted_false(self, tmp_path):
        task = DelegationTask(agent="broken", payload={})
        coord = _coordinator(call_fn=_fail_call, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.all_accepted is False

    def test_failed_count_increments(self, tmp_path):
        tasks = [DelegationTask(agent=f"a{i}", payload={}) for i in range(3)]
        coord = _coordinator(call_fn=_fail_call, tmp_path=tmp_path)
        result = coord.delegate_batch(tasks)
        assert result.failed_count == 3

    def test_partial_failure_all_accepted_false(self, tmp_path):
        calls = [True, False, True]  # call index → succeed?
        call_iter = iter(calls)

        def mixed_call(agent: str, payload: dict) -> str:
            if next(call_iter):
                return "ok"
            raise RuntimeError("fail")

        tasks = [DelegationTask(agent=f"a{i}", payload={}) for i in range(3)]
        coord = _coordinator(call_fn=mixed_call, tmp_path=tmp_path)
        result = coord.delegate_batch(tasks)
        assert result.all_accepted is False
        assert result.failed_count == 1

    def test_partial_failure_success_acks_accepted(self, tmp_path):
        counter = {"n": 0}

        def mixed_call(agent: str, payload: dict) -> str:
            counter["n"] += 1
            if counter["n"] == 2:
                raise RuntimeError("second fails")
            return "success"

        tasks = [DelegationTask(agent=f"a{i}", payload={}) for i in range(3)]
        coord = _coordinator(call_fn=mixed_call, tmp_path=tmp_path)
        result = coord.delegate_batch(tasks)
        accepted = [a for a in result.acks if a.status == "ACCEPTED"]
        assert len(accepted) == 2


# ── parallel execution ────────────────────────────────────────────────────────

class TestParallelExecution:
    def test_parallel_faster_than_sequential(self, tmp_path):
        """4 tasks that each sleep 0.2s should finish in <1s if parallel."""
        def slow_call(agent: str, payload: dict) -> str:
            time.sleep(0.2)
            return "done"

        tasks = [DelegationTask(agent=f"a{i}", payload={}) for i in range(4)]
        coord = _coordinator(call_fn=slow_call, tmp_path=tmp_path)
        t0 = time.monotonic()
        result = coord.delegate_batch(tasks)
        elapsed = time.monotonic() - t0
        assert result.all_accepted
        assert elapsed < 0.8, f"Expected parallel execution <0.8s, got {elapsed:.2f}s"

    def test_all_tasks_complete(self, tmp_path):
        tasks = [DelegationTask(agent=f"agent{i}", payload={"i": i}) for i in range(8)]
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch(tasks)
        assert len(result.acks) == 8
        assert all(a.status == "ACCEPTED" for a in result.acks)


# ── timeout handling ──────────────────────────────────────────────────────────

class TestTimeoutHandling:
    def test_timed_out_task_ack_failed(self, tmp_path):
        task = DelegationTask(agent="slow_agent", payload={})
        coord = _coordinator(call_fn=_slow_call, timeout=0, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.acks[0].status == "FAILED"

    def test_timed_out_task_error_mentions_timeout(self, tmp_path):
        task = DelegationTask(agent="slow_agent", payload={})
        coord = _coordinator(call_fn=_slow_call, timeout=0, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert "timeout" in result.acks[0].error

    def test_timed_out_all_accepted_false(self, tmp_path):
        task = DelegationTask(agent="slow_agent", payload={})
        coord = _coordinator(call_fn=_slow_call, timeout=0, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert result.all_accepted is False


# ── closure evidence ──────────────────────────────────────────────────────────

class TestClosureEvidence:
    def test_evidence_file_written(self, tmp_path):
        task = DelegationTask(agent="omi", payload={"doc": "x"})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        assert Path(result.closure_evidence_path).exists()

    def test_evidence_file_valid_json(self, tmp_path):
        task = DelegationTask(agent="omi", payload={})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        data = json.loads(Path(result.closure_evidence_path).read_text())
        assert "batch_id" in data

    def test_evidence_contains_batch_id(self, tmp_path):
        task = DelegationTask(agent="omi", payload={})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        data = json.loads(Path(result.closure_evidence_path).read_text())
        assert data["batch_id"] == result.batch_id

    def test_evidence_contains_all_accepted(self, tmp_path):
        task = DelegationTask(agent="omi", payload={})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        data = json.loads(Path(result.closure_evidence_path).read_text())
        assert "all_accepted" in data
        assert data["all_accepted"] is True

    def test_evidence_contains_acks(self, tmp_path):
        tasks = [DelegationTask(agent=f"a{i}", payload={}) for i in range(3)]
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch(tasks)
        data = json.loads(Path(result.closure_evidence_path).read_text())
        assert len(data["acks"]) == 3

    def test_evidence_written_on_partial_failure(self, tmp_path):
        """Evidence must be written even when some tasks fail."""
        tasks = [DelegationTask(agent="broken", payload={})]
        coord = _coordinator(call_fn=_fail_call, tmp_path=tmp_path)
        result = coord.delegate_batch(tasks)
        assert Path(result.closure_evidence_path).exists()
        data = json.loads(Path(result.closure_evidence_path).read_text())
        assert data["all_accepted"] is False
        assert data["failed_count"] == 1

    def test_each_batch_gets_unique_evidence_file(self, tmp_path):
        task = DelegationTask(agent="omi", payload={})
        coord = _coordinator(tmp_path=tmp_path)
        r1 = coord.delegate_batch([task])
        r2 = coord.delegate_batch([task])
        assert r1.closure_evidence_path != r2.closure_evidence_path

    def test_merged_result_in_evidence(self, tmp_path):
        task = DelegationTask(agent="knomi", payload={})
        coord = _coordinator(tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        data = json.loads(Path(result.closure_evidence_path).read_text())
        assert "merged_result" in data
        assert "knomi" in data["merged_result"]


class TestClosureStateMapping:
    def test_successful_ack_maps_completed_successfully(self):
        ack = DelegationAck(task_id="s1", agent="knomi", status="ACCEPTED", result="ok")
        state = map_delegation_ack_to_closure_state(ack, claim_supported=True)
        assert state == ClosureState.COMPLETED_SUCCESSFULLY.value

    def test_failed_ack_maps_controlled_retry_state(self):
        ack = DelegationAck(task_id="s2", agent="omi", status="FAILED", error="error")
        state = map_delegation_ack_to_closure_state(ack, retry_count=0, max_retries=2)
        assert state is None

    def test_timeout_ack_maps_escalated(self):
        ack = DelegationAck(task_id="s3", agent="omi", status="FAILED", error="timeout after 10s")
        state = map_delegation_ack_to_closure_state(ack, retry_count=0, max_retries=2)
        assert state == ClosureState.ESCALATED_WITH_REPORT.value

    def test_failed_after_limit_requires_evidence_path(self):
        ack = DelegationAck(task_id="s4", agent="omi", status="FAILED", error="timeout")
        state = map_delegation_ack_to_closure_state(
            ack,
            retry_count=2,
            max_retries=2,
            repair_attempt_count=1,
            max_repair_attempts=1,
        )
        proj = build_failure_projection(
            batch_id="b1",
            ack=ack,
            closure_state=state,
            evidence_path="/tmp/evidence.json",
            next_action="escalate_with_report",
            escalation_required=True,
            dead_letter_required=True,
            dead_letter_reason="timeout_finalized_by_coordinator",
        )
        assert proj["closure_state"] == ClosureState.FAILED_AFTER_REPAIR_LIMIT_WITH_EVIDENCE.value
        assert proj["evidence_path"]

    def test_dead_letter_requires_dead_letter_reason(self):
        ack = DelegationAck(task_id="s5", agent="omi", status="FAILED", error="timeout")
        with pytest.raises(ValueError):
            build_failure_projection(
                batch_id="b2",
                ack=ack,
                closure_state=ClosureState.ESCALATED_WITH_REPORT.value,
                evidence_path="/tmp/evidence.json",
                next_action="escalate_with_report",
                dead_letter_required=True,
                dead_letter_reason="",
            )


class TestRefinementBehavior:
    def test_timeout_outcome_finality_marker_written(self, tmp_path):
        task = DelegationTask(agent="slow_agent", payload={})
        coord = _coordinator(call_fn=_slow_call, timeout=0, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        data = json.loads(Path(result.closure_evidence_path).read_text())
        assert data["timeout_outcome_final"] is True
        assert "late_completion_policy" in data

    def test_late_completion_cannot_overwrite_timeout_outcome(self, tmp_path):
        task = DelegationTask(agent="slow_agent", payload={})
        coord = _coordinator(call_fn=_slow_call, timeout=0, tmp_path=tmp_path)
        result = coord.delegate_batch([task])
        data1 = json.loads(Path(result.closure_evidence_path).read_text())
        time.sleep(0.6)
        data2 = json.loads(Path(result.closure_evidence_path).read_text())
        assert data1["failed_count"] == data2["failed_count"]
        assert data1["acks"][0]["status"] == data2["acks"][0]["status"]

    def test_no_pending_steps_writes_evidence_marker(self, tmp_path):
        path = write_no_pending_execution_evidence("plan_test", 999)
        p = Path(path)
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["status"] == "NO_PENDING_STEPS"
        assert data["closure_state"] == ClosureState.COMPLETED_SUCCESSFULLY.value

    def test_claim_verification_failure_prevents_completed_status(self):
        verdict = get_verifier().verify_step_completion("step-x", "knomi", "error: timeout reached")
        assert verdict.result != "SUPPORTED"
