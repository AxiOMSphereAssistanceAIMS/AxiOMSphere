"""Stage 6: End-to-end integration tests — full pipeline from dispatch to result.

Tests:
  Step A  Full lifecycle: dispatch → queue → worker → get_result
  Step B  HTTP API: /health, POST /task, GET /task/{id}, GET /result/{id}
  Step C  Concurrent workers — two workers, same queue, no double-processing
  Step D  Worker resilience — handler crash, worker continues next task
  Step E  Status polling — background worker + poll-until-done pattern
  Step F  Real Ollama classification (auto-skipped if Ollama not reachable)

No real Ollama, NIM, Anthropic, or DocAgent connections (except Step F).
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# ── Step A: Full lifecycle ────────────────────────────────────────────────────

class TestFullLifecycle:
    def test_dispatch_enqueue_worker_result(self):
        from sync_pipeline import dispatch
        q = _make_queue()

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
            r = dispatch("safety report", [{"name": "a.pdf", "excerpt": "data"}], queue=q)

        assert r["queued"] is True
        task_id = r["task_id"]
        assert q.status(task_id) == "pending"

        w = _make_worker(q, handlers={"docx": lambda p: {"success": True, "result": "/out/doc.docx"}})
        w.run_one()

        assert q.status(task_id) == "done"
        res = q.get_result(task_id)
        assert res["status"] == "done"
        assert res["result"]["result"] == "/out/doc.docx"

    def test_full_chat_lifecycle(self):
        from sync_pipeline import dispatch
        q = _make_queue()

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            r = dispatch("analyze risks", [], queue=q)

        task_id = r["task_id"]
        w = _make_worker(q, handlers={"chat": lambda p: {"success": True, "result": "Risk: low"}})
        w.run_one()

        assert q.status(task_id) == "done"
        assert q.get_result(task_id)["result"]["result"] == "Risk: low"

    def test_get_result_before_worker_is_none(self):
        from sync_pipeline import dispatch
        q = _make_queue()

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
            r = dispatch("report", [], queue=q)

        assert q.get_result(r["task_id"]) is None

    def test_failed_task_result_has_error(self):
        q = _make_queue()
        task_id = q.enqueue("docx", {})
        w = _make_worker(q, handlers={"docx": lambda p: {"success": False, "error": "template missing"}})
        w.run_one()

        assert q.status(task_id) == "failed"
        assert "template missing" in q.get_result(task_id)["error"]

    def test_five_mixed_tasks_all_resolved(self):
        from sync_pipeline import dispatch
        q = _make_queue()
        ids = []

        for i in range(3):
            with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
                ids.append(dispatch(f"report {i}", [], queue=q)["task_id"])
        for i in range(2):
            with patch("router.fallback_router._keyword_fast_path", return_value=None), \
                 patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
                ids.append(dispatch(f"analyze {i}", [], queue=q)["task_id"])

        w = _make_worker(q, handlers={
            "docx": lambda p: {"success": True},
            "chat": lambda p: {"success": True},
        })
        w.run_loop(max_idle=1, sleep=0)

        for tid in ids:
            assert q.status(tid) == "done"


# ── Step B: HTTP API ──────────────────────────────────────────────────────────

class TestHTTPAPI:
    @pytest.fixture
    def client_and_queue(self):
        from fastapi.testclient import TestClient
        from api.app import app
        from core.queue import TaskQueue, MemoryBackend
        q = TaskQueue(_backend=MemoryBackend())
        with patch("api.app._queue", new=lambda: q):
            yield TestClient(app), q

    def test_health(self, client_and_queue):
        client, _ = client_and_queue
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_enqueue_returns_task_id(self, client_and_queue):
        client, _ = client_and_queue
        r = client.post("/task", json={"type": "docx", "payload": {"prompt": "report"}})
        assert r.status_code == 200
        data = r.json()
        assert "task_id" in data
        assert len(data["task_id"]) == 36

    def test_task_status_pending(self, client_and_queue):
        client, q = client_and_queue
        task_id = q.enqueue("docx", {})
        r = client.get(f"/task/{task_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_task_status_done_after_worker(self, client_and_queue):
        client, q = client_and_queue
        task_id = q.enqueue("docx", {})
        w = _make_worker(q, handlers={"docx": lambda p: {"success": True}})
        w.run_one()
        r = client.get(f"/task/{task_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "done"

    def test_task_status_not_found(self, client_and_queue):
        client, _ = client_and_queue
        r = client.get("/task/nonexistent-task-id-xyz")
        assert r.status_code == 404

    def test_result_returns_200_when_done(self, client_and_queue):
        client, q = client_and_queue
        task_id = q.enqueue("docx", {})
        w = _make_worker(q, handlers={"docx": lambda p: {"success": True, "path": "/out/doc.docx"}})
        w.run_one()
        r = client.get(f"/result/{task_id}")
        assert r.status_code == 200

    def test_result_404_before_done(self, client_and_queue):
        client, q = client_and_queue
        task_id = q.enqueue("docx", {})
        r = client.get(f"/result/{task_id}")
        assert r.status_code == 404

    def test_result_409_for_failed_task(self, client_and_queue):
        client, q = client_and_queue
        task_id = q.enqueue("docx", {})
        w = _make_worker(q, handlers={"docx": lambda p: {"success": False, "error": "fail"}})
        w.run_one()
        r = client.get(f"/result/{task_id}")
        assert r.status_code == 409

    def test_enqueue_via_api_then_worker_via_queue(self, client_and_queue):
        """Task posted through API, worker drains the shared queue, result readable."""
        client, q = client_and_queue
        r = client.post("/task", json={"type": "chat", "payload": {"prompt": "summary"}})
        task_id = r.json()["task_id"]

        w = _make_worker(q, handlers={"chat": lambda p: {"success": True, "result": "summary text"}})
        w.run_one()

        r2 = client.get(f"/task/{task_id}")
        assert r2.json()["status"] == "done"
        r3 = client.get(f"/result/{task_id}")
        assert r3.status_code == 200


# ── Step C: Concurrent workers ────────────────────────────────────────────────

class TestConcurrentWorkers:
    def test_two_workers_no_double_processing(self):
        q = _make_queue()
        processed = []
        lock = threading.Lock()

        def handler(p):
            with lock:
                processed.append(p.get("n"))
            time.sleep(0.002)
            return {"success": True}

        ids = [q.enqueue("chat", {"n": i}) for i in range(20)]
        w1 = _make_worker(q, handlers={"chat": handler})
        w2 = _make_worker(q, handlers={"chat": handler})

        t1 = w1.run_in_thread(sleep=0)
        t2 = w2.run_in_thread(sleep=0)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if all(q.status(i) in ("done", "failed") for i in ids):
                break
            time.sleep(0.05)

        w1.stop()
        w2.stop()
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)

        assert len(processed) == 20
        assert sorted(processed) == list(range(20))

    def test_two_workers_all_tasks_complete(self):
        q = _make_queue()
        ids = [q.enqueue("docx", {}) for _ in range(10)]
        w1 = _make_worker(q, handlers={"docx": lambda p: {"success": True}})
        w2 = _make_worker(q, handlers={"docx": lambda p: {"success": True}})

        t1 = w1.run_in_thread(sleep=0.01)
        t2 = w2.run_in_thread(sleep=0.01)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if all(q.status(i) == "done" for i in ids):
                break
            time.sleep(0.05)

        w1.stop()
        w2.stop()
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)

        for i in ids:
            assert q.status(i) == "done"


# ── Step D: Worker resilience ─────────────────────────────────────────────────

class TestWorkerResilience:
    def test_handler_crash_does_not_stop_loop(self):
        q = _make_queue()
        good1 = q.enqueue("chat", {"n": 1})
        bad = q.enqueue("chat", {"n": 2})
        good2 = q.enqueue("chat", {"n": 3})

        call_count = [0]

        def handler(p):
            call_count[0] += 1
            if p.get("n") == 2:
                raise RuntimeError("simulated crash")
            return {"success": True}

        w = _make_worker(q, handlers={"chat": handler})
        w.run_loop(max_idle=1, sleep=0)

        assert q.status(good1) == "done"
        assert q.status(bad) == "failed"
        assert q.status(good2) == "done"
        assert call_count[0] == 3

    def test_worker_continues_after_unknown_type(self):
        q = _make_queue()
        bad = q.enqueue("unknown", {})
        good = q.enqueue("chat", {})

        w = _make_worker(q, handlers={"chat": lambda p: {"success": True}})
        w.run_loop(max_idle=1, sleep=0)

        assert q.status(bad) == "failed"
        assert q.status(good) == "done"

    def test_all_tasks_resolved_despite_mixed_failures(self):
        q = _make_queue()
        ids = []
        expected = {}

        for i in range(10):
            tid = q.enqueue("chat", {"n": i})
            ids.append(tid)
            expected[tid] = "failed" if i % 3 == 0 else "done"

        def handler(p):
            if p.get("n", 0) % 3 == 0:
                raise ValueError("divisible by 3")
            return {"success": True}

        w = _make_worker(q, handlers={"chat": handler})
        w.run_loop(max_idle=1, sleep=0)

        for tid in ids:
            assert q.status(tid) == expected[tid]


# ── Step E: Status polling ────────────────────────────────────────────────────

class TestStatusPolling:
    def test_poll_until_done(self):
        q = _make_queue()
        task_id = q.enqueue("docx", {"prompt": "report"})

        def slow_worker():
            time.sleep(0.05)
            w = _make_worker(q, handlers={"docx": lambda p: {"success": True, "path": "/out/doc.docx"}})
            w.run_one()

        t = threading.Thread(target=slow_worker, daemon=True)
        t.start()

        deadline = time.monotonic() + 2.0
        status = "pending"
        while time.monotonic() < deadline:
            status = q.status(task_id)
            if status == "done":
                break
            time.sleep(0.01)

        t.join(timeout=1.0)
        assert status == "done"

    def test_poll_detects_failure(self):
        q = _make_queue()
        task_id = q.enqueue("docx", {})

        def fail_worker():
            time.sleep(0.02)
            w = _make_worker(q, handlers={"docx": lambda p: (_ for _ in ()).throw(RuntimeError("crash"))})
            w.run_one()

        t = threading.Thread(target=fail_worker, daemon=True)
        t.start()

        deadline = time.monotonic() + 2.0
        status = "pending"
        while time.monotonic() < deadline:
            status = q.status(task_id)
            if status in ("done", "failed"):
                break
            time.sleep(0.01)

        t.join(timeout=1.0)
        assert status == "failed"

    def test_poll_processing_state_visible(self):
        """Status transitions: pending → processing → done."""
        q = _make_queue()
        task_id = q.enqueue("docx", {})
        seen_processing = []

        def slow_handler(p):
            time.sleep(0.15)
            return {"success": True}

        barrier = threading.Event()

        def worker_thread():
            barrier.wait()
            w = _make_worker(q, handlers={"docx": slow_handler})
            w.run_one()

        t = threading.Thread(target=worker_thread, daemon=True)
        t.start()
        barrier.set()

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            s = q.status(task_id)
            if s == "processing":
                seen_processing.append(True)
            if s == "done":
                break
            time.sleep(0.005)

        t.join(timeout=1.0)
        assert q.status(task_id) == "done"
        assert seen_processing, "never observed 'processing' status"


# ── Step F: Real Ollama classification ───────────────────────────────────────

def _ollama_available() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_available(), reason="Ollama not running")
class TestRealOllama:
    def test_keyword_docx_bypasses_ollama(self):
        """keyword fast-path returns docx without touching Ollama."""
        from sync_pipeline import dispatch
        q = _make_queue()
        mock_client = MagicMock()
        mock_client.generate.return_value = {"ok": True, "path": "/out/doc.docx"}

        with patch("doc_agent_api.DocAgentClient", return_value=mock_client):
            result = dispatch("generate a safety report", [], queue=q)

        assert result["queued"] is True
        assert q.qsize() == 1

    def test_real_classify_routes_to_agent_or_clarify(self):
        """No keyword → Ollama classifies; result is queue or clarify."""
        from sync_pipeline import dispatch
        q = _make_queue()

        result = dispatch("what is the risk level of this document?", [], queue=q)
        assert result.get("agent") in ("queue", "clarify")
