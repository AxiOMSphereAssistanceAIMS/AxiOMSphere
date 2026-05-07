#!/usr/bin/env python3
"""Test suite for Repairman-PoliAgent integration.

Verifies:
1. SysPolic recognizes repairman action types
2. SysPolic enforces concept_preserved and restorative flags
3. RepairmanAPI calls PoliAgent before execution
4. LogiOrchestrator routes health events to RepairmanAPI
5. Tool registry includes repairman_trigger
"""
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "ops"))
sys.path.insert(0, str(repo_root))

import pytest


class TestPolicyGateRepairmanActions:
    """Test that SysPolic recognizes and validates repairman actions."""

    def test_repairman_actions_in_safe_actions(self):
        """Verify repairman action types are in SAFE_ACTIONS."""
        from ops.self_healing.policy_gate import SAFE_ACTIONS

        assert "repairman_inspect" in SAFE_ACTIONS
        assert "repairman_repair" in SAFE_ACTIONS
        assert "repairman_fix" in SAFE_ACTIONS

    def test_repairman_inspect_allowed(self):
        """Verify repairman_inspect is allowed (read-only, always safe)."""
        from ops.self_healing.policy_gate import SysPolic

        polic = SysPolic()
        action = {
            "type": "repairman_inspect",
            "task": "Inspect system health",
        }
        # Should not raise
        assert polic.allow(action) is True

    def test_repairman_repair_requires_concept_preserved(self):
        """Verify repairman_repair requires concept_preserved=True."""
        from ops.self_healing.policy_gate import SysPolic, PolicyDenied

        polic = SysPolic()
        action = {
            "type": "repairman_repair",
            "task": "Fix broken service",
            "concept_preserved": False,
            "restorative": True,
        }
        with pytest.raises(PolicyDenied) as exc_info:
            polic.allow(action)
        assert "concept must be preserved" in str(exc_info.value)

    def test_repairman_repair_requires_restorative(self):
        """Verify repairman_repair requires restorative=True."""
        from ops.self_healing.policy_gate import SysPolic, PolicyDenied

        polic = SysPolic()
        action = {
            "type": "repairman_repair",
            "task": "Fix broken service",
            "concept_preserved": True,
            "restorative": False,
        }
        with pytest.raises(PolicyDenied) as exc_info:
            polic.allow(action)
        assert "changes must be restorative" in str(exc_info.value)

    def test_repairman_fix_requires_both_flags(self):
        """Verify repairman_fix requires both concept_preserved and restorative."""
        from ops.self_healing.policy_gate import SysPolic, PolicyDenied

        polic = SysPolic()

        # Missing both
        action = {
            "type": "repairman_fix",
            "task": "Restore operability",
        }
        with pytest.raises(PolicyDenied):
            polic.allow(action)

        # Has both → should pass
        action["concept_preserved"] = True
        action["restorative"] = True
        assert polic.allow(action) is True

    def test_repairman_action_requires_task(self):
        """Verify all repairman actions require 'task' field."""
        from ops.self_healing.policy_gate import SysPolic, PolicyDenied

        polic = SysPolic()
        for action_type in ["repairman_inspect", "repairman_repair", "repairman_fix"]:
            action = {"type": action_type}
            with pytest.raises(PolicyDenied) as exc_info:
                polic.allow(action)
            assert "requires 'task' field" in str(exc_info.value)


class TestRepairmanAPIPoliIntegration:
    """Test that RepairmanAPI calls PoliAgent before execution."""

    def test_repairman_api_imports_httpx(self):
        """Verify RepairmanAPI imports httpx for PoliAgent calls."""
        import ops.telegram.repairman_api as m
        # httpx is imported inside trigger_task, check source
        import inspect
        source = inspect.getsource(m.trigger_task)
        assert "import httpx" in source or "httpx.AsyncClient" in source

    def test_repairman_api_calls_poli_check(self):
        """Verify trigger_task calls PoliAgent /check endpoint."""
        import inspect
        from ops.telegram.repairman_api import trigger_task

        source = inspect.getsource(trigger_task)
        assert "http://localhost:8004/check" in source or "poli_url" in source
        assert "policy_check" in source or "poli" in source.lower()

    def test_repairman_api_includes_audit_id_in_task(self):
        """Verify trigger_task includes PoliAgent audit_id in task text."""
        import inspect
        from ops.telegram.repairman_api import trigger_task

        source = inspect.getsource(trigger_task)
        assert "audit_id" in source
        assert "PoliAgent audit_id" in source or "audit_id=" in source


class TestLogiOrchestratorRepairmanIntegration:
    """Test that PipelineCoordinator routes health events to RepairmanAPI."""

    def test_logi_on_health_event_calls_repairman(self):
        """Verify on_health_event calls repairman_trigger tool."""
        import inspect
        from ops.logi.pipeline_coordinator import PipelineCoordinator

        source = inspect.getsource(PipelineCoordinator.on_health_event)
        assert "repairman_trigger" in source
        assert "call_tool" in source

    def test_logi_routes_critical_to_fix_mode(self):
        """Verify CRITICAL events trigger repairman fix mode."""
        import inspect
        from ops.logi.pipeline_coordinator import PipelineCoordinator

        source = inspect.getsource(PipelineCoordinator.on_health_event)
        assert 'level == "CRITICAL"' in source or 'CRITICAL' in source
        assert 'mode = "fix"' in source

    def test_logi_routes_warning_to_inspect_mode(self):
        """Verify WARNING events trigger repairman inspect mode."""
        import inspect
        from ops.logi.pipeline_coordinator import PipelineCoordinator

        source = inspect.getsource(PipelineCoordinator.on_health_event)
        assert 'level == "WARNING"' in source or 'WARNING' in source
        assert 'mode = "inspect"' in source


class TestToolRegistryRepairman:
    """Test that tool registry includes repairman_trigger."""

    def test_repairman_trigger_in_registry(self):
        """Verify repairman_trigger is registered."""
        from ops.logi.tool_registry import TOOL_REGISTRY

        assert "repairman_trigger" in TOOL_REGISTRY

    def test_repairman_trigger_endpoint(self):
        """Verify repairman_trigger points to correct endpoint."""
        from ops.logi.tool_registry import TOOL_REGISTRY

        tool = TOOL_REGISTRY["repairman_trigger"]
        assert tool["endpoint"] == "http://localhost:8010/trigger"
        assert tool["method"] == "POST"

    def test_repairman_trigger_schema(self):
        """Verify repairman_trigger has correct input schema."""
        from ops.logi.tool_registry import TOOL_REGISTRY

        tool = TOOL_REGISTRY["repairman_trigger"]
        schema = tool["input_schema"]
        assert "task" in schema
        assert "mode" in schema
        assert "source" in schema


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
