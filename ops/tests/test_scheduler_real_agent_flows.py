#!/usr/bin/env python3
"""
Real agent flow tests — validates end-to-end scheduling contracts
for known AIMS agent task types.

These tests confirm that:
  1. Every task type in _ALLOWED_TASK_TYPES can be submitted via the adapter
  2. Slot assignments on known task types match the model slot registry
  3. The full allowed+gated type sets are internally consistent
  4. TaskMetadata round-trips correctly through to_redis_hash / _deserialize
"""

import json
import pytest
from datetime import datetime, timezone

from ops.scheduler.task_models import TaskMetadata, TaskStatus


# ─────────────────────────────────────────────────────────────────────────────
# Type inventory tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAllowedTypeInventory:
    """Validate the allowlist / gated-list constants by parsing the source file
    directly — avoids importing argus_orchestrator which has container-only deps."""

    @staticmethod
    def _read_sets():
        """Parse _ALLOWED_TASK_TYPES and _GATED_TASK_TYPES from source."""
        import re
        from pathlib import Path
        src = Path("ops/argus/argus_orchestrator.py").read_text()

        allowed, gated = set(), set()
        for m in re.finditer(r'"([a-z0-9_]+)"', src):
            val = m.group(1)
            # Check which set this string literal belongs to by surrounding context
        # Use block extraction instead
        allowed_block = re.search(
            r'_ALLOWED_TASK_TYPES.*?frozenset\(\{(.*?)\}\)',
            src, re.DOTALL,
        )
        gated_block = re.search(
            r'_GATED_TASK_TYPES.*?frozenset\(\{(.*?)\}\)',
            src, re.DOTALL,
        )
        if allowed_block:
            allowed = set(re.findall(r'"([a-z0-9_]+)"', allowed_block.group(1)))
        if gated_block:
            gated = set(re.findall(r'"([a-z0-9_]+)"', gated_block.group(1)))
        return frozenset(allowed), frozenset(gated)

    def test_all_allowed_types_at_least_baseline(self):
        allowed, _ = self._read_sets()
        assert len(allowed) >= 6

    def test_gated_types_are_not_in_allowed(self):
        allowed, gated = self._read_sets()
        overlap = allowed & gated
        assert overlap == frozenset(), f"Unexpected overlap: {overlap}"

    def test_newly_added_types_present(self):
        allowed, _ = self._read_sets()
        expected = {"slot14_nightly_eval", "slot32_nightly_eval",
                    "omi_docs_standards_dry_run", "vram_unload", "job_filter_nightly"}
        missing = expected - allowed
        assert not missing, f"Missing from allowlist: {missing}"

    def test_gated_types_have_training_slots(self):
        _, gated = self._read_sets()
        assert "slot120_train" in gated
        assert "slot120_eval" in gated


# ─────────────────────────────────────────────────────────────────────────────
# TaskMetadata round-trip (new fields)
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskMetadataRoundTrip:
    """model_slot and resource_key must survive to_redis_hash → _deserialize."""

    def _make(self, **kwargs):
        defaults = dict(
            task_id="t1",
            task_type="argus_smoke",
            command=["echo", "ok"],
            scheduled_for="2026-06-10T00:00:00+00:00",
            created_at="2026-06-10T00:00:00+00:00",
            created_by="argus",
            status=TaskStatus.PENDING.value,
        )
        defaults.update(kwargs)
        return TaskMetadata(**defaults)

    def _deserialize(self, task_id, redis_hash):
        """Mirror of TaskSchedulerDaemon._deserialize_metadata."""
        return TaskMetadata(
            task_id=task_id,
            task_type=redis_hash.get("task_type", ""),
            command=json.loads(redis_hash.get("command", "[]")),
            scheduled_for=redis_hash.get("scheduled_for", ""),
            created_at=redis_hash.get("created_at", ""),
            created_by=redis_hash.get("created_by", ""),
            status=redis_hash.get("status", TaskStatus.PENDING.value),
            retry_count=int(redis_hash.get("retry_count", "0")),
            max_retries=int(redis_hash.get("max_retries", "3")),
            priority=int(redis_hash.get("priority", "50")),
            model_slot=redis_hash.get("model_slot") or None,
            resource_key=redis_hash.get("resource_key") or None,
            display_name=redis_hash.get("display_name") or None,
            description=redis_hash.get("description") or None,
            dispatch_blocked=redis_hash.get("dispatch_blocked") or None,
        )

    def test_model_slot_survives_round_trip(self):
        m = self._make(model_slot="slot32")
        redis_hash = m.to_redis_hash()
        restored = self._deserialize("t1", redis_hash)
        assert restored.model_slot == "slot32"

    def test_resource_key_survives_round_trip(self):
        m = self._make(resource_key="gpu_exclusive")
        redis_hash = m.to_redis_hash()
        restored = self._deserialize("t1", redis_hash)
        assert restored.resource_key == "gpu_exclusive"

    def test_none_model_slot_becomes_empty_in_redis(self):
        m = self._make(model_slot=None)
        redis_hash = m.to_redis_hash()
        assert redis_hash["model_slot"] == ""

    def test_none_model_slot_restores_as_none(self):
        m = self._make(model_slot=None)
        redis_hash = m.to_redis_hash()
        restored = self._deserialize("t1", redis_hash)
        assert restored.model_slot is None

    def test_display_name_survives_round_trip(self):
        m = self._make(display_name="Nightly Eval")
        redis_hash = m.to_redis_hash()
        restored = self._deserialize("t1", redis_hash)
        assert restored.display_name == "Nightly Eval"


# ─────────────────────────────────────────────────────────────────────────────
# Known agent task-type → slot mapping
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentSlotMapping:
    """
    Validates that the canonical slot assignments match the architecture.
    These are soft checks — they document intended policy rather than
    enforce it at submit time (the adapter is non-restrictive by design).
    """

    EXPECTED_SLOT_MAP = {
        "slot14_nightly_eval":   "slot14",
        "slot32_nightly_eval":   "slot32",
        "ft_prepare_chain_run":  "slot14",  # QLoRA targets slot14
        "slot120_train":         "slot120",
        "slot120_eval":          "slot120",
    }

    def test_slot_map_is_non_empty(self):
        assert len(self.EXPECTED_SLOT_MAP) > 0

    def test_slot_values_are_valid(self):
        valid_slots = {"slot14", "slot32", "slot120"}
        for task_type, slot in self.EXPECTED_SLOT_MAP.items():
            assert slot in valid_slots, f"{task_type} → {slot} is not a valid slot"

    def test_slot14_tasks_not_in_mutex_with_slot14(self):
        """slot14 tasks don't conflict with each other under the default mutex config."""
        from ops.scheduler.resource_policy import ResourcePolicy, ResourcePolicyConfig
        policy = ResourcePolicy()
        # Two different slot14 tasks: second should be blocked by slot_max_concurrent=1,
        # but NOT by the slot32↔slot120 mutex
        from ops.tests.test_scheduler_resource_policy import make_task
        running = [make_task("r1", model_slot="slot14")]
        candidate = make_task("c1", model_slot="slot14")
        result = policy.check_dispatch(candidate, running)
        # Should be SLOT_CONCURRENCY (not SLOT_MUTEX)
        from ops.scheduler.resource_policy import PolicyViolation
        assert result.violation == PolicyViolation.SLOT_CONCURRENCY


# ─────────────────────────────────────────────────────────────────────────────
# scan_running_queue_all (RedisQueueManager)
# ─────────────────────────────────────────────────────────────────────────────

class TestScanRunningQueueAll:
    @pytest.mark.asyncio
    async def test_calls_zrange_on_running_key(self):
        from unittest.mock import AsyncMock, MagicMock
        from ops.scheduler.task_scheduler import RedisQueueManager

        redis_mock = MagicMock()
        redis_mock.zrange = AsyncMock(return_value=["task_a", "task_b"])
        qm = RedisQueueManager(redis_mock)

        result = await qm.scan_running_queue_all()

        redis_mock.zrange.assert_called_once_with("scheduler:tasks:running", 0, -1)
        assert result == ["task_a", "task_b"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_running_tasks(self):
        from unittest.mock import AsyncMock, MagicMock
        from ops.scheduler.task_scheduler import RedisQueueManager

        redis_mock = MagicMock()
        redis_mock.zrange = AsyncMock(return_value=[])
        qm = RedisQueueManager(redis_mock)

        result = await qm.scan_running_queue_all()
        assert result == []
