"""Tests for ops/agents/argus_agent.py — runtime_names.py migration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import inspect

from core.runtime_names import QUEUE_PENDING, QUEUE_PROCESSING, RESTARTABLE_SERVICES


class TestArgusAgentImports:
    def test_imports_queue_constants_from_runtime_names(self):
        import ops.agents.argus_agent as aa

        source = inspect.getsource(aa)
        assert "from core.runtime_names import QUEUE_PENDING, QUEUE_PROCESSING" in source, \
            "argus_agent must import QUEUE_PENDING, QUEUE_PROCESSING from core.runtime_names"

    def test_no_hardcoded_queue_strings_in_module(self):
        import ops.agents.argus_agent as aa

        source = inspect.getsource(aa)
        assert '"queue:pending"' not in source, \
            "argus_agent must not hardcode 'queue:pending' — use QUEUE_PENDING"
        assert '"queue:processing"' not in source, \
            "argus_agent must not hardcode 'queue:processing' — use QUEUE_PROCESSING"


class TestCheckTaskQueue:
    def test_check_task_queue_uses_queue_constants(self):
        from ops.agents.argus_agent import _check_task_queue

        source = inspect.getsource(_check_task_queue)
        assert "QUEUE_PENDING" in source, \
            "_check_task_queue must use QUEUE_PENDING constant"
        assert "QUEUE_PROCESSING" in source, \
            "_check_task_queue must use QUEUE_PROCESSING constant"

    def test_check_task_queue_sums_both_queues(self):
        from ops.agents.argus_agent import _check_task_queue

        source = inspect.getsource(_check_task_queue)
        assert "pending" in source and "processing" in source, \
            "_check_task_queue must read both pending and processing queues"


class TestWatchedContainers:
    def test_watched_containers_imported(self):
        from ops.agents.argus_agent import WATCHED_CONTAINERS

        assert len(WATCHED_CONTAINERS) > 0

    def test_watched_containers_no_axiomsphere_prefix(self):
        from ops.agents.argus_agent import WATCHED_CONTAINERS

        for name in WATCHED_CONTAINERS:
            assert not name.startswith("axiomsphere-"), \
                f"'{name}' is a container_name — WATCHED_CONTAINERS must use service names"

    def test_watched_containers_are_valid_services(self):
        from ops.agents.argus_agent import WATCHED_CONTAINERS

        for name in WATCHED_CONTAINERS:
            assert name in RESTARTABLE_SERVICES, \
                f"'{name}' in WATCHED_CONTAINERS is not a known compose service name"

    def test_key_services_are_watched(self):
        from ops.agents.argus_agent import WATCHED_CONTAINERS

        # Verify the core services that argus currently monitors
        key_services = {"axi-bot", "omi-api", "qdrant", "task-registry"}
        for svc in key_services:
            assert svc in WATCHED_CONTAINERS, \
                f"'{svc}' should be in WATCHED_CONTAINERS"
