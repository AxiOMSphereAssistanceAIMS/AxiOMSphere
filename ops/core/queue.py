"""AIMS task queue — Redis-backed with in-memory fallback for testing.

Supports both legacy API (pop/status/qsize with set-based processing tracking)
and modern API (dequeue with BRPOPLPUSH for crash-safe delivery).

Queue layout (Redis):
  queue:pending       — LIST (lpush / brpop) — FIFO
  queue:processing    — SET (legacy) or LIST (modern) — task IDs being worked
  result:{task_id}    — STRING (JSON, TTL 1h)

In-memory MemoryBackend mirrors the same interface so tests need no Redis process.

Usage (legacy):
    q = TaskQueue(_backend=MemoryBackend())  # in-memory (tests / dev)
    task_id = q.enqueue("docx", {"prompt": "..."})
    task = q.pop()                           # worker calls this
    q.complete(task["id"], {"path": "/out/doc.docx"})
    status = q.status(task_id)               # pending | processing | done | failed

Usage (modern):
    q = TaskQueue(redis_url="redis://aims-redis:6379")
    task_id = q.enqueue("quality_check", {"doc_id": 42})
    task = q.dequeue(block_sec=5)        # None on timeout
    q.complete(task["id"], {"score": 0.91})
    q.fail(task["id"], "timeout")
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional


_QUEUE_PENDING = "queue:pending"
_QUEUE_PROCESSING = "queue:processing"
_RESULTS_PREFIX = "result:"
_RESULT_TTL = 3600  # 1 hour


# ── In-memory backend (tests / dev) ──────────────────────────────────────────

class MemoryBackend:
    """Thread-safe enough for single-threaded tests; not for production."""

    def __init__(self) -> None:
        self._pending: List[str] = []       # JSON strings, FIFO (append right, pop left)
        self._processing: Dict[str, str] = {}  # task_id → JSON
        self._results: Dict[str, str] = {}  # task_id → JSON

    # ── push / pop ────────────────────────────────────────────────────────────

    def lpush(self, key: str, value: str) -> None:
        if key == _QUEUE_PENDING:
            self._pending.append(value)

    def rpop(self, key: str) -> Optional[str]:
        if key == _QUEUE_PENDING and self._pending:
            return self._pending.pop(0)
        return None

    def lrange(self, key: str) -> List[str]:
        if key == _QUEUE_PENDING:
            return list(self._pending)
        return []

    # ── processing set ────────────────────────────────────────────────────────

    def sadd(self, key: str, value: str) -> None:
        if key == _QUEUE_PROCESSING:
            self._processing[value] = value

    def srem(self, key: str, value: str) -> None:
        if key == _QUEUE_PROCESSING:
            self._processing.pop(value, None)

    def smembers(self, key: str) -> set:
        if key == _QUEUE_PROCESSING:
            return set(self._processing.keys())
        return set()

    # ── results ───────────────────────────────────────────────────────────────

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._results[key] = value

    def get(self, key: str) -> Optional[str]:
        return self._results.get(key)

    def qsize(self) -> int:
        return len(self._pending)


# ── Redis backend (production) ────────────────────────────────────────────────

class RedisBackend:
    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._r = None  # lazy-connect on first use

    def _client(self):
        if self._r is None:
            import redis  # type: ignore
            self._r = redis.from_url(self._url, decode_responses=True)
        return self._r

    def _reset_client(self) -> None:
        """Discard broken connection so next _client() call reconnects."""
        try:
            if self._r is not None:
                self._r.close()
        except Exception:
            pass
        self._r = None

    def lpush(self, key: str, value: str) -> None:
        self._client().lpush(key, value)

    def rpop(self, key: str) -> Optional[str]:
        return self._client().rpop(key)

    def lrange(self, key: str) -> List[str]:
        return self._client().lrange(key, 0, -1)

    def brpoplpush(self, src: str, dst: str, timeout: int) -> Optional[str]:
        """Atomically pop from src and push to dst. Returns None on timeout."""
        import redis as _redis_mod  # type: ignore
        try:
            return self._client().brpoplpush(src, dst, timeout=timeout)
        except _redis_mod.exceptions.ConnectionError:
            self._reset_client()
            return self._client().brpoplpush(src, dst, timeout=timeout)

    def sadd(self, key: str, value: str) -> None:
        self._client().sadd(key, value)

    def srem(self, key: str, value: str) -> None:
        self._client().srem(key, value)

    def smembers(self, key: str) -> set:
        return self._client().smembers(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._client().setex(key, ttl, value)

    def get(self, key: str) -> Optional[str]:
        return self._client().get(key)

    def qsize(self) -> int:
        try:
            return self._client().llen(_QUEUE_PENDING)
        except Exception:
            return -1

    def lrem(self, key: str, count: int, value: str) -> None:
        self._client().lrem(key, count, value)

    def pipeline(self):
        return self._client().pipeline()


# ── TaskQueue ─────────────────────────────────────────────────────────────────

class TaskQueue:
    """AIMS task queue supporting both legacy and modern APIs.

    Args:
        redis_url: Redis connection string (used when _backend is None).
        _backend:  Override backend — pass MemoryBackend() for tests.
    """

    def __init__(
        self,
        redis_url: str = "",
        *,
        _backend=None,
    ) -> None:
        if _backend is not None:
            self._b = _backend
        else:
            url = redis_url or os.environ.get("AIMS_REDIS_URL", "redis://aims-redis:6379")
            self._b = RedisBackend(url)

    # ── Legacy API (pop/status) ────────────────────────────────────────────────

    def enqueue(self, task_type: str, payload: Dict[str, Any]) -> str:
        """Push a task onto the pending queue. Returns task_id."""
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "type": task_type,
            "payload": payload,
            "created_at": time.time(),
            "status": "pending",
        }
        self._b.lpush(_QUEUE_PENDING, json.dumps(task))
        return task_id

    def pop(self) -> Optional[Dict[str, Any]]:
        """Pop the next pending task (FIFO). Returns None if queue empty.

        Legacy API — use dequeue() for modern crash-safe behavior.
        """
        raw = self._b.rpop(_QUEUE_PENDING)
        if raw is None:
            return None
        task = json.loads(raw)
        task["status"] = "processing"
        self._b.sadd(_QUEUE_PROCESSING, task["id"])
        return task

    def complete(self, task_id: str, result: Any) -> None:
        """Mark task done and store result."""
        self._b.srem(_QUEUE_PROCESSING, task_id)
        self._b.setex(
            f"{_RESULTS_PREFIX}{task_id}",
            _RESULT_TTL,
            json.dumps({"status": "done", "result": result, "finished_at": time.time()}),
        )

    def fail(self, task_id: str, error: str) -> None:
        """Mark task failed."""
        self._b.srem(_QUEUE_PROCESSING, task_id)
        self._b.setex(
            f"{_RESULTS_PREFIX}{task_id}",
            _RESULT_TTL,
            json.dumps({"status": "failed", "error": error, "finished_at": time.time()}),
        )

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return result dict or None if task is still pending/unknown."""
        raw = self._b.get(f"{_RESULTS_PREFIX}{task_id}")
        if raw is None:
            return None
        return json.loads(raw)

    def status(self, task_id: str) -> str:
        """Return 'pending' | 'processing' | 'done' | 'failed' | 'not_found'."""
        result = self.get_result(task_id)
        if result is not None:
            return result.get("status", "done")
        processing = self._b.smembers(_QUEUE_PROCESSING)
        if task_id in processing:
            return "processing"
        pending_raw = self._b.lrange(_QUEUE_PENDING)
        for raw in pending_raw:
            try:
                if json.loads(raw).get("id") == task_id:
                    return "pending"
            except Exception:
                pass
        return "not_found"

    def qsize(self) -> int:
        """Number of tasks currently in the pending queue."""
        return self._b.qsize()

    # ── Modern API (dequeue/BRPOPLPUSH) ───────────────────────────────────────

    def dequeue(self, block_sec: float = 5.0) -> Optional[Dict[str, Any]]:
        """Pop a task from pending → processing. Returns None on timeout.

        Modern crash-safe API using BRPOPLPUSH. Automatically reconnects once
        on ConnectionError (server closes idle connections).
        """
        result = self._b.brpoplpush(_QUEUE_PENDING, _QUEUE_PROCESSING, timeout=int(block_sec))
        if result is None:
            return None
        return json.loads(result)

    def requeue_stale(self, max_age_sec: float = 300.0) -> int:
        """Move stale processing tasks back to pending (watchdog recovery)."""
        items = self._b.lrange(_QUEUE_PROCESSING)
        now = time.time()
        requeued = 0
        for raw in items:
            try:
                task = json.loads(raw)
                age = now - task.get("created_at", now)
                if age > max_age_sec:
                    pipe = self._b.pipeline()
                    pipe.lrem(_QUEUE_PROCESSING, 1, raw)
                    pipe.lpush(_QUEUE_PENDING, raw)
                    pipe.execute()
                    requeued += 1
            except Exception:
                pass
        return requeued

    def _remove_from_processing(self, task_id: str) -> None:
        items = self._b.lrange(_QUEUE_PROCESSING)
        for raw in items:
            try:
                task = json.loads(raw)
                if task.get("id") == task_id:
                    self._b.lrem(_QUEUE_PROCESSING, 1, raw)
                    return
            except Exception:
                pass
