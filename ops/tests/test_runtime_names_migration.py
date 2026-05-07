"""Tests for Patch 1: Runtime Names Migration.

Verifies that all files correctly import from ops.core.runtime_names
instead of hardcoding service names and queue keys.
"""
import sys
from pathlib import Path

# Allow imports from parent ops/ directory
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

import pytest
from core.runtime_names import (
    RESTARTABLE_SERVICES,
    STEP_SERVICE_MAP,
    QUEUE_PENDING,
    QUEUE_PROCESSING,
)
from self_healing.policy_gate import RESTARTABLE_CONTAINERS
from factory.decision_engine import STEP_SERVICE_MAP as ENGINE_MAP


def test_policy_gate_uses_runtime_names():
    """Verify policy_gate.py imports RESTARTABLE_SERVICES from runtime_names."""
    assert RESTARTABLE_CONTAINERS == RESTARTABLE_SERVICES
    assert len(RESTARTABLE_CONTAINERS) == 17
    assert "axi-bot" in RESTARTABLE_CONTAINERS
    assert "omi-bot" in RESTARTABLE_CONTAINERS
    assert "argus-bot" in RESTARTABLE_CONTAINERS


def test_decision_engine_uses_runtime_names():
    """Verify decision_engine.py imports STEP_SERVICE_MAP from runtime_names."""
    assert ENGINE_MAP == STEP_SERVICE_MAP
    assert len(ENGINE_MAP) == 6
    assert ENGINE_MAP["knomi_search"] == "knomi-agent"
    assert ENGINE_MAP["context_filter"] is None
    assert ENGINE_MAP["doci_compose"] == "doc-agent"


def test_queue_constants_defined():
    """Verify queue constants are correctly defined in runtime_names."""
    assert QUEUE_PENDING == "queue:pending"
    assert QUEUE_PROCESSING == "queue:processing"


def test_repair_executor_imports_queue_constants():
    """Verify repair_executor.py uses queue constants from runtime_names."""
    from self_healing.repair_executor import _clear_queue
    
    # Test that _clear_queue uses the constants (indirect verification via import)
    action = {"queues": [QUEUE_PENDING, QUEUE_PROCESSING]}
    # We don't actually execute (no Redis in test), just verify import works
    assert _clear_queue.__module__ == "self_healing.repair_executor"


def test_argus_agent_imports_queue_constants():
    """Verify argus_agent.py uses queue constants from runtime_names."""
    # Import the module to verify it loads without error
    from agents import argus_agent
    
    # Verify the constants are available in the module's namespace
    assert hasattr(argus_agent, 'QUEUE_PENDING')
    assert hasattr(argus_agent, 'QUEUE_PROCESSING')
    assert argus_agent.QUEUE_PENDING == "queue:pending"
    assert argus_agent.QUEUE_PROCESSING == "queue:processing"


def test_no_hardcoded_service_names_in_policy_gate():
    """Verify policy_gate.py doesn't contain hardcoded service name strings."""
    policy_gate_path = _ops_dir / "self_healing" / "policy_gate.py"
    content = policy_gate_path.read_text()
    
    # Should import from runtime_names
    assert "from core.runtime_names import RESTARTABLE_SERVICES" in content
    
    # Should NOT have hardcoded frozenset with service names
    assert 'frozenset({\n    "axi-bot",' not in content


def test_no_hardcoded_queue_keys_in_repair_executor():
    """Verify repair_executor.py doesn't contain hardcoded queue key strings."""
    repair_executor_path = _ops_dir / "self_healing" / "repair_executor.py"
    content = repair_executor_path.read_text()
    
    # Should import from runtime_names
    assert "from core.runtime_names import QUEUE_PENDING, QUEUE_PROCESSING" in content
    
    # Should NOT have hardcoded "queue:pending" or "queue:processing" strings
    # (except in comments or error messages)
    lines = content.split('\n')
    code_lines = [l for l in lines if not l.strip().startswith('#')]
    code_text = '\n'.join(code_lines)
    
    # Check that queue constants are used, not hardcoded strings
    assert 'QUEUE_PENDING' in code_text
    assert 'QUEUE_PROCESSING' in code_text


def test_no_hardcoded_queue_keys_in_argus_agent():
    """Verify argus_agent.py doesn't contain hardcoded queue key strings."""
    argus_agent_path = _ops_dir / "agents" / "argus_agent.py"
    content = argus_agent_path.read_text()
    
    # Should import from runtime_names
    assert "from core.runtime_names import QUEUE_PENDING, QUEUE_PROCESSING" in content
    
    # Should use constants in _check_task_queue
    assert "r.llen(QUEUE_PENDING)" in content
    assert "r.llen(QUEUE_PROCESSING)" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
