"""Stage 4: Task queue tests — enqueue heavy tasks, worker drain, result fetch.

Tests:
  Step A  MemoryBackend    — push/pop/set/get primitives
  Step B  TaskQueue.enqueue — returns valid task_id, task appears in queue
  Step C  TaskQueue.pop     — FIFO order, marks task as processing
  Step D  TaskQueue.complete / fail — result stored, status updated
  Step E  TaskQueue.status  — pending / processing / done / failed / not_found
  Step F  Queue wiring in sync_pipeline.dispatch — docx/chat → enqueue, ask → clarify
  Step G  Worker loop — pop → execute → complete/fail cycle (mocked executor)

No Redis required — all tests use MemoryBackend.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

OPS = Path(__file__).resolve().parents[1]
WORKSPACE = OPS.parent
for _p in (str(OPS), str(WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── Step A: MemoryBackend primitives ──────────────────────────────────────────

class TestMemoryBackend:
    def _backend(self):
        from core.queue import MemoryBackend
        return MemoryBackend()

    def test_lpush_rpop_fifo(self):
        b = self._backend()
        b.lpush("queue:pending", "task1")
        b.lpush("queue:pending", "task2")
        assert b.rpop("queue:pending") == "task1"
        assert b.rpop("queue:pending") == "task2"
        assert b.rpop("queue:pending") is None

    def test_rpop_empty_returns_none(self):
        b = self._backend()
        assert b.rpop("queue:pending") is None

    def test_lrange_all(self):
        b = self._backend()
        b.lpush("queue:pending", "a")
        b.lpush("queue:pending", "b")
        items = b.lrange("queue:pending")
        assert items == ["a", "b"]

    def test_sadd_srem_smembers(self):
        b = self._backend()
        b.sadd("queue:processing", "id-1")
        b.sadd("queue:processing", "id-2")
        assert "id-1" in b.smembers("queue:processing")
        b.srem("queue:processing", "id-1")
        assert "id-1" not in b.smembers("queue:processing")
        assert "id-2" in b.smembers("queue:processing")

    def test_setex_get(self):
        b = self._backend()
        b.setex("result:abc", 3600, '{"status": "done"}')
        assert b.get("result:abc") == '{"status": "done"}'
        assert b.get("result:missing") is None

    def test_qsize(self):
        b = self._backend()
        assert b.qsize() == 0
        b.lpush("queue:pending", "x")
        b.lpush("queue:pending", "y")
        assert b.qsize() == 2


# ── Step B: TaskQueue.enqueue ─────────────────────────────────────────────────

class TestTaskQueueEnqueue:
    def _q(self):
        from core.queue import TaskQueue, MemoryBackend
        return TaskQueue(_backend=MemoryBackend())

    def test_enqueue_returns_task_id(self):
        q = self._q()
        task_id = q.enqueue("docx", {"prompt": "generate report"})
        assert isinstance(task_id, str)
        assert len(task_id) == 36  # UUID4

    def test_enqueue_increments_qsize(self):
        q = self._q()
        assert q.qsize() == 0
        q.enqueue("docx", {})
        q.enqueue("chat", {})
        assert q.qsize() == 2

    def test_enqueue_payload_preserved(self):
        q = self._q()
        import json
        task_id = q.enqueue("docx", {"prompt": "hello", "files": [{"name": "a.pdf"}]})
        # Read raw from backend
        raw = q._b.lrange("queue:pending")
        task = json.loads(raw[0])
        assert task["type"] == "docx"
        assert task["payload"]["prompt"] == "hello"
        assert task["id"] == task_id

    def test_enqueue_status_field_is_pending(self):
        q = self._q()
        import json
        q.enqueue("chat", {"prompt": "x"})
        raw = q._b.lrange("queue:pending")
        task = json.loads(raw[0])
        assert task["status"] == "pending"


# ── Step C: TaskQueue.pop ─────────────────────────────────────────────────────

class TestTaskQueuePop:
    def _q(self):
        from core.queue import TaskQueue, MemoryBackend
        return TaskQueue(_backend=MemoryBackend())

    def test_pop_returns_first_enqueued(self):
        q = self._q()
        id1 = q.enqueue("docx", {"n": 1})
        id2 = q.enqueue("chat", {"n": 2})
        task = q.pop()
        assert task["id"] == id1
        assert task["type"] == "docx"

    def test_pop_empty_returns_none(self):
        q = self._q()
        assert q.pop() is None

    def test_pop_marks_processing(self):
        q = self._q()
        task_id = q.enqueue("docx", {})
        q.pop()
        assert q.status(task_id) == "processing"

    def test_pop_removes_from_pending(self):
        q = self._q()
        q.enqueue("docx", {})
        assert q.qsize() == 1
        q.pop()
        assert q.qsize() == 0


# ── Step D: complete / fail ───────────────────────────────────────────────────

class TestTaskQueueResults:
    def _q(self):
        from core.queue import TaskQueue, MemoryBackend
        return TaskQueue(_backend=MemoryBackend())

    def test_complete_stores_result(self):
        q = self._q()
        task_id = q.enqueue("docx", {})
        q.pop()
        q.complete(task_id, {"path": "/out/doc.docx"})
        result = q.get_result(task_id)
        assert result is not None
        assert result["status"] == "done"
        assert result["result"]["path"] == "/out/doc.docx"

    def test_fail_stores_error(self):
        q = self._q()
        task_id = q.enqueue("docx", {})
        q.pop()
        q.fail(task_id, "DocAgent timeout")
        result = q.get_result(task_id)
        assert result is not None
        assert result["status"] == "failed"
        assert "timeout" in result["error"]

    def test_get_result_pending_task_returns_none(self):
        q = self._q()
        task_id = q.enqueue("docx", {})
        assert q.get_result(task_id) is None

    def test_complete_clears_processing_set(self):
        q = self._q()
        task_id = q.enqueue("docx", {})
        q.pop()
        assert q.status(task_id) == "processing"
        q.complete(task_id, {"path": "/out/doc.docx"})
        assert q.status(task_id) == "done"


# ── Step E: status ────────────────────────────────────────────────────────────

class TestTaskQueueStatus:
    def _q(self):
        from core.queue import TaskQueue, MemoryBackend
        return TaskQueue(_backend=MemoryBackend())

    def test_status_pending(self):
        q = self._q()
        task_id = q.enqueue("chat", {})
        assert q.status(task_id) == "pending"

    def test_status_processing(self):
        q = self._q()
        task_id = q.enqueue("chat", {})
        q.pop()
        assert q.status(task_id) == "processing"

    def test_status_done(self):
        q = self._q()
        task_id = q.enqueue("chat", {})
        q.pop()
        q.complete(task_id, "response text")
        assert q.status(task_id) == "done"

    def test_status_failed(self):
        q = self._q()
        task_id = q.enqueue("chat", {})
        q.pop()
        q.fail(task_id, "network error")
        assert q.status(task_id) == "failed"

    def test_status_unknown_task(self):
        q = self._q()
        assert q.status("nonexistent-id") == "not_found"


# ── Step F: sync_pipeline queue wiring ───────────────────────────────────────

class TestDispatchQueueWiring:
    """dispatch() with queue= enqueues heavy tasks instead of blocking."""

    def _q(self):
        from core.queue import TaskQueue, MemoryBackend
        return TaskQueue(_backend=MemoryBackend())

    def test_docx_enqueued_not_dispatched(self):
        from sync_pipeline import dispatch
        q = self._q()
        doc_agent_called = []

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"), \
             patch("doc_agent_api.DocAgentClient", side_effect=lambda *a, **kw: doc_agent_called.append(1)):
            result = dispatch("generate a report", [{"name": "data.pdf"}], queue=q)

        assert result["queued"] is True
        assert result["success"] is True
        assert isinstance(result["task_id"], str)
        assert len(result["task_id"]) == 36
        assert q.qsize() == 1
        assert doc_agent_called == []

    def test_chat_enqueued_not_dispatched(self):
        from sync_pipeline import dispatch
        q = self._q()
        router_called = []
        mock_router = MagicMock(side_effect=lambda *a, **kw: router_called.append(1))

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            result = dispatch("analyze this", [], queue=q, model_router=mock_router)

        assert result["queued"] is True
        assert q.qsize() == 1
        assert router_called == []

    def test_ask_not_queued_returns_clarify(self):
        """ask intent is never queued — returned immediately."""
        from sync_pipeline import dispatch
        q = self._q()

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("ask", 0.2)):
            result = dispatch("hmm", [], queue=q)

        assert result["agent"] == "clarify"
        assert q.qsize() == 0

    def test_enqueued_task_payload_contains_prompt(self):
        from sync_pipeline import dispatch
        import json
        q = self._q()

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
            result = dispatch("make the report about safety", [{"name": "a.pdf"}], queue=q)

        raw = q._b.lrange("queue:pending")
        task = json.loads(raw[0])
        assert task["payload"]["prompt"] == "make the report about safety"
        assert task["type"] == "docx"

    def test_no_queue_still_works_sync(self):
        """queue=None (default) preserves Stage 3 sync behaviour."""
        from sync_pipeline import dispatch
        mock_cls = MagicMock()
        mock_cls.return_value.generate.return_value = {"ok": True, "path": "/out/doc.docx"}

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"), \
             patch("doc_agent_api.DocAgentClient", mock_cls):
            result = dispatch("generate a report", [])

        assert result["success"] is True
        assert result.get("queued") is not True


# ── Step G: worker loop simulation ───────────────────────────────────────────

class TestWorkerLoop:
    """Simulate a worker draining the queue: pop → execute → complete/fail."""

    def _q(self):
        from core.queue import TaskQueue, MemoryBackend
        return TaskQueue(_backend=MemoryBackend())

    def _fake_executor(self, task: dict) -> dict:
        """Fake task executor: returns result based on task type."""
        if task["type"] == "docx":
            return {"path": f"/out/{task['id']}.docx"}
        elif task["type"] == "chat":
            return {"text": "Analysis complete."}
        raise ValueError(f"unknown task type: {task['type']}")

    def test_worker_drains_queue_and_stores_results(self):
        q = self._q()
        id1 = q.enqueue("docx", {"prompt": "report 1"})
        id2 = q.enqueue("chat", {"prompt": "analyze this"})
        id3 = q.enqueue("docx", {"prompt": "report 2"})

        # Worker loop
        while True:
            task = q.pop()
            if task is None:
                break
            try:
                result = self._fake_executor(task)
                q.complete(task["id"], result)
            except Exception as e:
                q.fail(task["id"], str(e))

        assert q.qsize() == 0
        assert q.status(id1) == "done"
        assert q.status(id2) == "done"
        assert q.status(id3) == "done"
        assert q.get_result(id1)["result"]["path"].endswith(".docx")

    def test_worker_handles_executor_failure(self):
        q = self._q()
        task_id = q.enqueue("unknown_type", {"prompt": "x"})

        task = q.pop()
        try:
            self._fake_executor(task)
            q.complete(task["id"], {})
        except Exception as e:
            q.fail(task["id"], str(e))

        assert q.status(task_id) == "failed"
        assert "unknown task type" in q.get_result(task_id)["error"]

    def test_worker_processes_in_fifo_order(self):
        q = self._q()
        ids = [q.enqueue("chat", {"n": i}) for i in range(5)]
        order = []
        while True:
            task = q.pop()
            if task is None:
                break
            order.append(task["id"])
            q.complete(task["id"], {})

        assert order == ids
