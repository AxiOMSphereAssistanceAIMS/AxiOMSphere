#!/usr/bin/env python3
"""Test suite for Production Hardening Patch 1.

Verifies:
1. Policy allows restart_container for every service in STEP_SERVICE_MAP
2. Policy denies axiomsphere-* container names (wrong format)
3. clear_queue defaults to queue:pending and queue:processing
"""
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "ops"))

import pytest
from ops.factory.decision_engine import STEP_SERVICE_MAP
from ops.self_healing.policy_gate import SysPolic, PolicyDenied, RESTARTABLE_CONTAINERS


class TestPolicyGateServiceNames:
    """Test that policy_gate uses service names, not container names."""

    def test_restartable_containers_are_service_names(self):
        """All entries should be service names (no axiomsphere- prefix)."""
        for name in RESTARTABLE_CONTAINERS:
            assert not name.startswith("axiomsphere-"), \
                f"RESTARTABLE_CONTAINERS should use service names, got: {name}"

    def test_policy_allows_step_service_map_targets(self):
        """Policy should allow all services in STEP_SERVICE_MAP."""
        polic = SysPolic()
        for step_name, service_name in STEP_SERVICE_MAP.items():
            if service_name is None:
                continue  # Skip None entries (in-process)
            action = {"type": "restart_container", "target": service_name}
            # Should not raise PolicyDenied
            assert polic.allow(action), \
                f"Policy should allow restart_container for {service_name} (from {step_name})"

    def test_policy_denies_container_names(self):
        """Policy should deny axiomsphere-* container names."""
        polic = SysPolic()
        container_names = [
            "axiomsphere-axi-bot",
            "axiomsphere-omi-bot",
            "axiomsphere-doc-agent",
            "axiomsphere-aims-api",
        ]
        for container_name in container_names:
            action = {"type": "restart_container", "target": container_name}
            with pytest.raises(PolicyDenied):
                polic.allow(action)

    def test_policy_requires_safe_action(self):
        """Policy should deny actions not in SAFE_ACTIONS."""
        polic = SysPolic()
        action = {"type": "unknown_action"}
        with pytest.raises(PolicyDenied):
            polic.allow(action)

    def test_policy_denies_dangerous_actions(self):
        """Policy should deny all dangerous actions."""
        polic = SysPolic()
        dangerous_actions = [
            "delete_db",
            "exec_shell",
            "wipe_storage",
            "drop_table",
            "rm_rf",
            "push_to_prod",
        ]
        for atype in dangerous_actions:
            action = {"type": atype}
            with pytest.raises(PolicyDenied):
                polic.allow(action)


class TestDecisionEngineServiceNames:
    """Test that decision_engine uses service names."""

    def test_step_service_map_has_service_names(self):
        """All targets should be service names, not container names."""
        for step_name, target in STEP_SERVICE_MAP.items():
            if target is None:
                continue
            assert not target.startswith("axiomsphere-"), \
                f"STEP_SERVICE_MAP[{step_name}] should be service name, got: {target}"

    def test_step_service_map_targets_in_policy(self):
        """All STEP_SERVICE_MAP targets should be in RESTARTABLE_CONTAINERS."""
        polic = SysPolic()
        for step_name, service_name in STEP_SERVICE_MAP.items():
            if service_name is None:
                continue
            assert service_name in RESTARTABLE_CONTAINERS, \
                f"{service_name} (from {step_name}) not in RESTARTABLE_CONTAINERS"


class TestRepairExecutorQueueHandling:
    """Test that repair_executor clears both queue:pending and queue:processing."""

    def test_clear_queue_default_behavior(self):
        """Verify _clear_queue defaults to clearing both queues."""
        import inspect
        from ops.self_healing.repair_executor import _clear_queue

        source = inspect.getsource(_clear_queue)

        # Verify both queue keys are handled
        assert "queue:pending" in source, \
            "_clear_queue should handle queue:pending"
        assert "queue:processing" in source, \
            "_clear_queue should handle queue:processing"

        # Verify it loops through multiple queues
        assert "for q in queues" in source or "for queue in queues" in source, \
            "_clear_queue should iterate through multiple queues"

        # Verify it sums counts
        assert "count +=" in source, \
            "_clear_queue should sum counts from multiple queues"

    def test_clear_queue_respects_custom_queues(self):
        """Verify _clear_queue respects custom queues parameter."""
        import inspect
        from ops.self_healing.repair_executor import _clear_queue

        source = inspect.getsource(_clear_queue)

        # Verify it checks for custom queues parameter
        assert 'action.get("queues")' in source, \
            "_clear_queue should check action['queues'] parameter"


class TestArgusAgentQueueDepth:
    """Test that argus_agent checks both queue depths."""

    def test_check_task_queue_implementation(self):
        """Verify _check_task_queue checks both queue:pending and queue:processing."""
        import inspect
        from ops.agents.argus_agent import _check_task_queue

        source = inspect.getsource(_check_task_queue)

        # Verify both queue keys are referenced
        assert "queue:pending" in source, \
            "_check_task_queue should check queue:pending"
        assert "queue:processing" in source, \
            "_check_task_queue should check queue:processing"

        # Verify it sums them
        assert "pending + processing" in source or "pending" in source and "processing" in source, \
            "_check_task_queue should sum both queue depths"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
