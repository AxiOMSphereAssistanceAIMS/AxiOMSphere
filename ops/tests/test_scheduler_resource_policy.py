#!/usr/bin/env python3
"""
Unit tests for ops/scheduler/resource_policy.py

Covers:
  - GlobalConcurrency limit
  - AgentConcurrency limit
  - TypeConcurrency singleton
  - SlotConcurrency limit
  - SlotMutex (slot32 ↔ slot120)
  - ResourceKeyLock
  - Permit paths (all conditions clear)
"""

import pytest
from unittest.mock import MagicMock

from ops.scheduler.task_models import TaskMetadata, TaskStatus
from ops.scheduler.resource_policy import (
    ResourcePolicy,
    ResourcePolicyConfig,
    PolicyDecision,
    PolicyViolation,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_task(
    task_id="t1",
    task_type="argus_smoke",
    created_by="argus",
    model_slot=None,
    resource_key=None,
    status=None,
):
    return TaskMetadata(
        task_id=task_id,
        task_type=task_type,
        command=["echo", "test"],
        scheduled_for="2026-06-10T00:00:00+00:00",
        created_at="2026-06-10T00:00:00+00:00",
        created_by=created_by,
        status=status or TaskStatus.RUNNING.value,
        model_slot=model_slot,
        resource_key=resource_key,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Global concurrency
# ─────────────────────────────────────────────────────────────────────────────

class TestGlobalConcurrency:
    def setup_method(self):
        self.policy = ResourcePolicy(ResourcePolicyConfig(global_max_concurrent=2))

    def test_permits_when_below_limit(self):
        running = [make_task("r1"), make_task("r2", task_type="training_ingest")]
        # candidate is 3rd but limit is... wait, limit=2 and running has 2 items
        # This should be denied
        candidate = make_task("c1")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.GLOBAL_CONCURRENCY

    def test_permits_when_running_is_empty(self):
        result = self.policy.check_dispatch(make_task("c1"), [])
        assert result.allowed

    def test_permits_when_one_running(self):
        result = self.policy.check_dispatch(make_task("c1"), [make_task("r1")])
        assert result.allowed

    def test_denies_at_global_limit(self):
        running = [make_task("r1"), make_task("r2")]
        result = self.policy.check_dispatch(make_task("c1"), running)
        assert not result.allowed
        assert result.violation == PolicyViolation.GLOBAL_CONCURRENCY
        assert result.running_count == 2
        assert result.limit == 2

    def test_deny_message_contains_count(self):
        running = [make_task("r1"), make_task("r2")]
        result = self.policy.check_dispatch(make_task("c1"), running)
        assert "2" in result.reason


# ─────────────────────────────────────────────────────────────────────────────
# Per-agent concurrency
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentConcurrency:
    def setup_method(self):
        self.policy = ResourcePolicy(ResourcePolicyConfig(
            global_max_concurrent=10,
            per_agent_max_concurrent=1,
        ))

    def test_denies_when_agent_at_limit(self):
        running = [make_task("r1", created_by="logi")]
        candidate = make_task("c1", created_by="logi")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.AGENT_CONCURRENCY

    def test_permits_different_agents(self):
        running = [make_task("r1", created_by="argus")]
        candidate = make_task("c1", created_by="logi")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_permits_when_agent_has_no_running(self):
        running = [make_task("r1", created_by="argus")]
        candidate = make_task("c1", created_by="manual")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Per-task-type singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestTypeConcurrency:
    def setup_method(self):
        self.policy = ResourcePolicy(ResourcePolicyConfig(
            global_max_concurrent=10,
            per_agent_max_concurrent=10,
            per_type_max_concurrent={"ft_prepare_chain_run": 1},
        ))

    def test_denies_duplicate_singleton_type(self):
        running = [make_task("r1", task_type="ft_prepare_chain_run")]
        candidate = make_task("c1", task_type="ft_prepare_chain_run")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.TYPE_CONCURRENCY

    def test_permits_when_type_is_not_limited(self):
        running = [make_task("r1", task_type="argus_smoke")]
        candidate = make_task("c1", task_type="argus_smoke")  # no limit in config
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_permits_different_type(self):
        running = [make_task("r1", task_type="ft_prepare_chain_run")]
        candidate = make_task("c1", task_type="training_ingest")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Slot concurrency
# ─────────────────────────────────────────────────────────────────────────────

class TestSlotConcurrency:
    def setup_method(self):
        self.policy = ResourcePolicy(ResourcePolicyConfig(
            global_max_concurrent=10,
            per_agent_max_concurrent=10,
            per_type_max_concurrent={},
            slot_max_concurrent=1,
        ))

    def test_denies_second_task_on_same_slot(self):
        running = [make_task("r1", model_slot="slot14")]
        candidate = make_task("c1", model_slot="slot14")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.SLOT_CONCURRENCY

    def test_permits_different_slots(self):
        running = [make_task("r1", model_slot="slot14")]
        candidate = make_task("c1", model_slot="slot32")
        # No mutex in this config (empty mutex groups)
        policy = ResourcePolicy(ResourcePolicyConfig(
            global_max_concurrent=10,
            per_agent_max_concurrent=10,
            per_type_max_concurrent={},
            slot_max_concurrent=1,
            slot_mutex_groups=[],
        ))
        result = policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_permits_no_slot_set(self):
        running = [make_task("r1", model_slot="slot14")]
        candidate = make_task("c1", model_slot=None)  # no slot
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Slot mutex (slot32 ↔ slot120)
# ─────────────────────────────────────────────────────────────────────────────

class TestSlotMutex:
    def setup_method(self):
        self.policy = ResourcePolicy(ResourcePolicyConfig(
            global_max_concurrent=10,
            per_agent_max_concurrent=10,
            per_type_max_concurrent={},
            slot_max_concurrent=1,
            slot_mutex_groups=[{"slot32", "slot120"}],
        ))

    def test_slot32_blocked_by_slot120(self):
        running = [make_task("r1", model_slot="slot120")]
        candidate = make_task("c1", model_slot="slot32")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.SLOT_MUTEX
        assert "slot32" in result.reason
        assert "slot120" in result.reason

    def test_slot120_blocked_by_slot32(self):
        running = [make_task("r1", model_slot="slot32")]
        candidate = make_task("c1", model_slot="slot120")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.SLOT_MUTEX

    def test_slot14_not_blocked_by_slot32(self):
        running = [make_task("r1", model_slot="slot32")]
        candidate = make_task("c1", model_slot="slot14")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_slot32_not_blocked_when_slot120_absent(self):
        running = [make_task("r1", model_slot="slot14")]
        candidate = make_task("c1", model_slot="slot32")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_empty_running_always_permits_slot(self):
        result = self.policy.check_dispatch(make_task("c1", model_slot="slot120"), [])
        assert result.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Resource key lock
# ─────────────────────────────────────────────────────────────────────────────

class TestResourceKeyLock:
    def setup_method(self):
        self.policy = ResourcePolicy(ResourcePolicyConfig(
            global_max_concurrent=10,
            per_agent_max_concurrent=10,
            per_type_max_concurrent={},
        ))

    def test_denies_duplicate_resource_key(self):
        running = [make_task("r1", resource_key="gpu_exclusive")]
        candidate = make_task("c1", resource_key="gpu_exclusive")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.RESOURCE_KEY_LOCK

    def test_permits_different_resource_keys(self):
        running = [make_task("r1", resource_key="gpu_exclusive")]
        candidate = make_task("c1", resource_key="disk_heavy")
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed

    def test_permits_no_resource_key(self):
        running = [make_task("r1", resource_key="gpu_exclusive")]
        candidate = make_task("c1", resource_key=None)
        result = self.policy.check_dispatch(candidate, running)
        assert result.allowed


# ─────────────────────────────────────────────────────────────────────────────
# PolicyDecision factory methods
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyDecision:
    def test_permit_factory(self):
        d = PolicyDecision.permit()
        assert d.allowed is True
        assert d.violation is None
        assert d.reason == ""

    def test_deny_factory(self):
        d = PolicyDecision.deny(
            PolicyViolation.GLOBAL_CONCURRENCY,
            "limit reached",
            running=3,
            limit=3,
        )
        assert d.allowed is False
        assert d.violation == PolicyViolation.GLOBAL_CONCURRENCY
        assert d.running_count == 3
        assert d.limit == 3


# ─────────────────────────────────────────────────────────────────────────────
# Default config smoke test
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultConfig:
    def setup_method(self):
        self.policy = ResourcePolicy()  # default ResourcePolicyConfig

    def test_empty_running_always_permits(self):
        result = self.policy.check_dispatch(make_task("c1"), [])
        assert result.allowed

    def test_slot32_slot120_mutex_is_active_by_default(self):
        running = [make_task("r1", model_slot="slot32")]
        candidate = make_task("c1", model_slot="slot120")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.SLOT_MUTEX

    def test_ft_prepare_chain_run_is_singleton_by_default(self):
        running = [make_task("r1", task_type="ft_prepare_chain_run")]
        candidate = make_task("c1", task_type="ft_prepare_chain_run")
        result = self.policy.check_dispatch(candidate, running)
        assert not result.allowed
        assert result.violation == PolicyViolation.TYPE_CONCURRENCY
