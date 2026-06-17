"""Stage 5: Worker tests — drain queue, dispatch handlers, result lifecycle.

Tests:
  Step A  PipelineWorker.run_one — single task processing
  Step B  Handler dispatch — correct handler called per task type
  Step C  Unknown task type — graceful fail, not crash
  Step D  Handler failure — exception caught, task marked failed
  Step E  Handler returns success=False — task marked failed
  Step F  run_loop with max_idle — drains batch then stops
  Step G  run_in_thread — concurrent drain in background thread
  Step H  Full end-to-end: enqueue → worker → result (mocked agents)

No real Ollama, NIM, Anthropic, or DocAgent connections.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

OPS = Path(__file__).resolve().parents[1]
WORKSPACE = OPS.parent
for _p in (str(OPS), str(WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _make_queue():
    from core.queue import TaskQueue, MemoryBackend
    return TaskQueue(_backend=MemoryBackend())


def _make_worker(queue, handlers=None):
    from workers.pipeline_worker import PipelineWorker
    return PipelineWorker(queue, handlers=handlers)


# ── Step A: run_one basics ────────────────────────────────────────────────────

class TestRunOne:
    def test_empty_queue_returns_false(self):
        q = _make_queue()
        w = _make_worker(q)
        assert w.run_one() is False

    def test_task_in_queue_returns_true(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"docx": lambda p: {"success": True, "path": "/out/doc.docx"}})
        q.enqueue("docx", {"prompt": "test"})
        assert w.run_one() is True

    def test_task_removed_from_queue_after_processing(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"docx": lambda p: {"success": True}})
        q.enqueue("docx", {})
        w.run_one()
        assert q.qsize() == 0

    def test_second_run_one_on_empty_returns_false(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"chat": lambda p: {"success": True}})
        q.enqueue("chat", {})
        w.run_one()
        assert w.run_one() is False


# ── Step B: handler dispatch ──────────────────────────────────────────────────

class TestHandlerDispatch:
    def test_correct_handler_called_for_task_type(self):
        calls = []
        q = _make_queue()
        w = _make_worker(q, handlers={
            "docx": lambda p: calls.append(("docx", p)) or {"success": True},
            "chat": lambda p: calls.append(("chat", p)) or {"success": True},
        })
        q.enqueue("docx", {"prompt": "report"})
        q.enqueue("chat", {"prompt": "analyze"})
        w.run_one()
        w.run_one()
        assert calls[0][0] == "docx"
        assert calls[1][0] == "chat"

    def test_payload_passed_to_handler(self):
        received = {}
        q = _make_queue()
        w = _make_worker(q, handlers={
            "docx": lambda p: received.update(p) or {"success": True},
        })
        q.enqueue("docx", {"prompt": "hello", "files": [{"name": "a.pdf"}]})
        w.run_one()
        assert received["prompt"] == "hello"
        assert received["files"][0]["name"] == "a.pdf"

    def test_result_stored_after_completion(self):
        q = _make_queue()
        w = _make_worker(q, handlers={
            "docx": lambda p: {"success": True, "result": "/out/doc.docx", "agent": "doc_agent"},
        })
        task_id = q.enqueue("docx", {})
        w.run_one()
        assert q.status(task_id) == "done"
        assert q.get_result(task_id)["status"] == "done"

    def test_handler_registered_after_init(self):
        q = _make_queue()
        w = _make_worker(q)
        custom_called = []
        w.register("custom", lambda p: custom_called.append(1) or {"success": True})
        q.enqueue("custom", {})
        w.run_one()
        assert custom_called == [1]
        assert q.status(q.enqueue("custom", {})) == "pending"  # new one is pending


# ── Step C: unknown task type ─────────────────────────────────────────────────

class TestUnknownTaskType:
    def test_unknown_type_does_not_crash(self):
        q = _make_queue()
        w = _make_worker(q, handlers={})
        task_id = q.enqueue("unknown_type", {})
        w.run_one()  # must not raise

    def test_unknown_type_task_marked_failed(self):
        q = _make_queue()
        w = _make_worker(q, handlers={})
        task_id = q.enqueue("unknown_type", {})
        w.run_one()
        assert q.status(task_id) == "failed"
        result = q.get_result(task_id)
        assert "no handler" in result["error"]

    def test_unknown_type_does_not_affect_other_tasks(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"chat": lambda p: {"success": True}})
        bad_id = q.enqueue("unknown_type", {})
        good_id = q.enqueue("chat", {})
        w.run_one()
        w.run_one()
        assert q.status(bad_id) == "failed"
        assert q.status(good_id) == "done"


# ── Step D: handler exception ─────────────────────────────────────────────────

class TestHandlerException:
    def test_exception_does_not_propagate(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"docx": lambda p: (_ for _ in ()).throw(RuntimeError("boom"))})
        q.enqueue("docx", {})
        w.run_one()  # must not raise

    def test_exception_marks_task_failed(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"docx": lambda p: 1 / 0})
        task_id = q.enqueue("docx", {})
        w.run_one()
        assert q.status(task_id) == "failed"
        assert "division by zero" in q.get_result(task_id)["error"]

    def test_exception_error_message_preserved(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"docx": lambda p: (_ for _ in ()).throw(RuntimeError("doc-agent timeout"))})
        task_id = q.enqueue("docx", {})
        w.run_one()
        assert "timeout" in q.get_result(task_id)["error"]


# ── Step E: handler returns success=False ────────────────────────────────────

class TestHandlerFailureResult:
    def test_success_false_marks_task_failed(self):
        q = _make_queue()
        w = _make_worker(q, handlers={
            "docx": lambda p: {"success": False, "error": "template not found"},
        })
        task_id = q.enqueue("docx", {})
        w.run_one()
        assert q.status(task_id) == "failed"
        assert "template not found" in q.get_result(task_id)["error"]

    def test_success_true_marks_task_done(self):
        q = _make_queue()
        w = _make_worker(q, handlers={
            "chat": lambda p: {"success": True, "result": "answer"},
        })
        task_id = q.enqueue("chat", {})
        w.run_one()
        assert q.status(task_id) == "done"


# ── Step F: run_loop with max_idle ────────────────────────────────────────────

class TestRunLoop:
    def test_run_loop_drains_all_tasks(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"docx": lambda p: {"success": True}})
        ids = [q.enqueue("docx", {}) for _ in range(5)]
        w.run_loop(max_idle=1, sleep=0)
        for task_id in ids:
            assert q.status(task_id) == "done"

    def test_run_loop_stops_on_max_idle(self):
        q = _make_queue()
        w = _make_worker(q, handlers={})
        started = time.monotonic()
        w.run_loop(max_idle=2, sleep=0.01)
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, "should have stopped quickly on empty queue"

    def test_run_loop_stops_on_stop_event(self):
        q = _make_queue()
        processed = []
        task_started = threading.Event()

        def slow_handler(p):
            task_started.set()
            processed.append(1)
            return {"success": True}

        w = _make_worker(q, handlers={"chat": slow_handler})
        for _ in range(10):
            q.enqueue("chat", {})

        def stopper():
            # Wait for at least one task to start processing, then stop
            task_started.wait(timeout=1.0)
            w.stop()

        t = threading.Thread(target=stopper)
        t.start()
        w.run_loop(sleep=0)
        t.join(timeout=2.0)
        # Some tasks were processed before stop was called
        assert len(processed) > 0, f"Expected > 0 tasks processed, got {len(processed)}"
        assert len(processed) <= 10, f"Expected <= 10 tasks processed, got {len(processed)}"


# ── Step G: run_in_thread ─────────────────────────────────────────────────────

class TestRunInThread:
    def test_thread_drains_queue(self):
        q = _make_queue()
        w = _make_worker(q, handlers={"docx": lambda p: {"success": True, "path": "/out/doc.docx"}})
        ids = [q.enqueue("docx", {}) for _ in range(3)]
        t = w.run_in_thread(sleep=0.01)
        # Give the thread time to process
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if all(q.status(i) == "done" for i in ids):
                break
            time.sleep(0.02)
        w.stop()
        t.join(timeout=1.0)
        for i in ids:
            assert q.status(i) == "done"

    def test_thread_is_daemon(self):
        q = _make_queue()
        w = _make_worker(q)
        t = w.run_in_thread()
        w.stop()
        t.join(timeout=1.0)
        assert t.daemon is True


# ── Step H: end-to-end — enqueue → worker → result (mocked agents) ───────────

class TestEndToEnd:
    """Full pipeline: sync_pipeline.dispatch(queue=q) → worker drains → result."""

    def test_docx_e2e_with_mocked_doc_agent(self):
        from sync_pipeline import dispatch
        q = _make_queue()

        mock_client = MagicMock()
        mock_client.generate.return_value = {"ok": True, "path": "/out/report.docx"}
        mock_cls = MagicMock(return_value=mock_client)

        # Stage 4: enqueue
        with patch("router.fallback_router._keyword_fast_path", return_value="docx"), \
             patch("doc_agent_api.DocAgentClient", mock_cls):
            result = dispatch("generate safety report", [{"name": "data.pdf", "excerpt": "content"}], queue=q)

        assert result["queued"] is True
        task_id = result["task_id"]
        assert q.status(task_id) == "pending"

        # Stage 5: worker processes
        with patch("doc_agent_api.DocAgentClient", mock_cls):
            w = _make_worker(q)  # uses default _handle_docx handler
            w.run_one()

        assert q.status(task_id) == "done"
        final = q.get_result(task_id)
        assert final["status"] == "done"

    def test_chat_e2e_with_mocked_model_router(self):
        from sync_pipeline import dispatch
        q = _make_queue()

        mock_router = MagicMock()
        mock_router.generate.return_value = {
            "success": True, "result": "Analysis done.", "provider": "nim",
        }

        # Stage 4: enqueue
        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            result = dispatch("analyze these docs", [], queue=q)

        task_id = result["task_id"]

        # Stage 5: worker processes (inject mock router via handler)
        def chat_handler(payload):
            from sync_pipeline import _handle_chat
            return _handle_chat(payload["prompt"], payload.get("files", []), model_router=mock_router)

        w = _make_worker(q, handlers={"chat": chat_handler})
        w.run_one()

        assert q.status(task_id) == "done"
        assert q.get_result(task_id)["result"]["result"] == "Analysis done."

    def test_multiple_tasks_all_resolved(self):
        """5 mixed tasks, all processed by worker loop, none left pending."""
        from sync_pipeline import dispatch
        q = _make_queue()

        mock_client = MagicMock()
        mock_client.generate.return_value = {"ok": True, "path": "/out/doc.docx"}
        mock_router = MagicMock()
        mock_router.generate.return_value = {"success": True, "result": "ok", "provider": "local"}

        ids = []
        # 3 docx + 2 chat
        for i in range(3):
            with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
                r = dispatch(f"report {i}", [], queue=q)
                ids.append(r["task_id"])
        for i in range(2):
            with patch("router.fallback_router._keyword_fast_path", return_value=None), \
                 patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
                r = dispatch(f"analyze {i}", [], queue=q)
                ids.append(r["task_id"])

        def docx_handler(p):
            return {"success": True, "result": "/out/doc.docx"}
        def chat_handler(p):
            return {"success": True, "result": "answer", "agent": "local"}

        w = _make_worker(q, handlers={"docx": docx_handler, "chat": chat_handler})
        w.run_loop(max_idle=1, sleep=0)

        for task_id in ids:
            assert q.status(task_id) == "done", f"task {task_id} not done"
