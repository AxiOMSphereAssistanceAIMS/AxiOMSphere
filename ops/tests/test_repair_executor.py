"""Tests for ops/self_healing/repair_executor.py — runtime_names.py migration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import inspect
from unittest.mock import MagicMock, patch, patch as mock_patch

from core.runtime_names import QUEUE_PENDING, QUEUE_PROCESSING


class TestRepairExecutorImports:
    def test_imports_queue_constants_from_runtime_names(self):
        import ops.self_healing.repair_executor as re_mod

        source = inspect.getsource(re_mod)
        assert "from core.runtime_names import QUEUE_PENDING, QUEUE_PROCESSING" in source, \
            "repair_executor must import QUEUE_PENDING, QUEUE_PROCESSING from core.runtime_names"

    def test_no_hardcoded_queue_strings(self):
        import ops.self_healing.repair_executor as re_mod

        source = inspect.getsource(re_mod)
        assert '"queue:pending"' not in source, \
            "repair_executor must not hardcode 'queue:pending' — use QUEUE_PENDING"
        assert '"queue:processing"' not in source, \
            "repair_executor must not hardcode 'queue:processing' — use QUEUE_PROCESSING"


class TestClearQueueHandler:
    def test_clear_queue_uses_queue_pending_constant(self):
        from ops.self_healing.repair_executor import _clear_queue

        source = inspect.getsource(_clear_queue)
        assert "QUEUE_PENDING" in source
        assert "QUEUE_PROCESSING" in source

    def test_clear_queue_iterates_multiple_queues(self):
        from ops.self_healing.repair_executor import _clear_queue

        source = inspect.getsource(_clear_queue)
        assert "for q in queues" in source or "for queue in queues" in source

    def test_clear_queue_with_mock_redis(self):
        from ops.self_healing.repair_executor import _clear_queue

        mock_r = MagicMock()
        mock_r.llen.return_value = 5
        mock_r.delete.return_value = 1
        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.return_value = mock_r

        with patch.dict(sys.modules, {"redis": mock_redis_mod}):
            result = _clear_queue({"redis_host": "localhost", "redis_port": 6379})

        assert "cleared" in result
        deleted_keys = [c for call in mock_r.delete.call_args_list for c in call.args]
        assert QUEUE_PENDING in deleted_keys, "clear_queue must delete QUEUE_PENDING"
        assert QUEUE_PROCESSING in deleted_keys, "clear_queue must delete QUEUE_PROCESSING"

    def test_clear_queue_respects_custom_queues_param(self):
        from ops.self_healing.repair_executor import _clear_queue

        mock_r = MagicMock()
        mock_r.llen.return_value = 0
        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.return_value = mock_r

        with patch.dict(sys.modules, {"redis": mock_redis_mod}):
            _clear_queue({
                "redis_host": "localhost",
                "queues": ["queue:failed"],
            })

        deleted_keys = [c for call in mock_r.delete.call_args_list for c in call.args]
        assert "queue:failed" in deleted_keys


class TestPauseResumeWorker:
    def test_pause_worker_uses_queue_pending_default(self):
        from ops.self_healing.repair_executor import _pause_worker

        source = inspect.getsource(_pause_worker)
        assert "QUEUE_PENDING" in source, \
            "_pause_worker default queue must reference QUEUE_PENDING constant"

    def test_pause_resume_with_mock_redis(self):
        from ops.self_healing.repair_executor import _pause_worker, _resume_worker

        mock_r = MagicMock()
        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.return_value = mock_r
        with patch.dict(sys.modules, {"redis": mock_redis_mod}):
            pause_result = _pause_worker({"redis_host": "localhost"})
            resume_result = _resume_worker({"redis_host": "localhost"})

        assert "pause" in pause_result.lower()
        assert "resume" in resume_result.lower() or "cleared" in resume_result.lower()
