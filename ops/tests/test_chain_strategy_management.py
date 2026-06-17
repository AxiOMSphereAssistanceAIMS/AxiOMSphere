"""
test_chain_strategy_management.py

Covers the strategy management chain:
  logi strategic planning → agent tasks → execution artifacts

All tests are STATIC — they read existing files and check invariants.
No services are started, no HTTP calls are made, no containers are required.
"""
import yaml
from pathlib import Path

import pytest

AIMS_ROOT = Path(__file__).parent.parent.parent.resolve()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_strategic_planning_module_exists():
    """ops/logi/strategic_planning.py must be present (SA12 strategy management)."""
    sp = AIMS_ROOT / "ops" / "logi" / "strategic_planning.py"
    assert sp.exists(), f"Strategic planning module missing: {sp}"
    assert sp.stat().st_size > 0, "strategic_planning.py must not be empty"


def test_conversational_orchestrator_exists():
    """ops/logi/conversational_orchestrator.py must be present."""
    path = AIMS_ROOT / "ops" / "logi" / "conversational_orchestrator.py"
    assert path.exists(), f"Conversational orchestrator missing: {path}"
    assert path.stat().st_size > 0, "conversational_orchestrator.py must not be empty"


def test_learning_loop_consumer_exists():
    """ops/logi/learning_loop_consumer.py must be present."""
    path = AIMS_ROOT / "ops" / "logi" / "learning_loop_consumer.py"
    assert path.exists(), f"Learning loop consumer missing: {path}"
    assert path.stat().st_size > 0, "learning_loop_consumer.py must not be empty"


def test_agent_architecture_status_has_subdirs():
    """aims_workspace/agent_architecture_status/ must contain planning artifact subdirs."""
    arch_dir = AIMS_ROOT / "aims_workspace" / "agent_architecture_status"
    assert arch_dir.exists(), f"agent_architecture_status directory missing: {arch_dir}"
    subdirs = [d for d in arch_dir.iterdir() if d.is_dir()]
    assert len(subdirs) >= 1, (
        f"No planning artifact subdirectories found in {arch_dir}. "
        "Strategy management requires at least one architecture status artifact."
    )


def test_agent_skill_registry_exists():
    """ops/agents/agent_skill_registry.yaml must be present."""
    reg = AIMS_ROOT / "ops" / "agents" / "agent_skill_registry.yaml"
    assert reg.exists(), f"Agent skill registry missing: {reg}"
    assert reg.stat().st_size > 0, "agent_skill_registry.yaml must not be empty"


def test_agent_skill_registry_valid_yaml_with_entries():
    """agent_skill_registry.yaml must parse as valid YAML with at least 5 top-level entries."""
    reg = AIMS_ROOT / "ops" / "agents" / "agent_skill_registry.yaml"
    assert reg.exists(), f"Registry file missing: {reg}"
    with reg.open() as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), "agent_skill_registry.yaml must be a YAML mapping"
    assert len(data) >= 5, (
        f"agent_skill_registry.yaml has only {len(data)} top-level keys — expected >= 5. "
        f"Found: {list(data.keys())}"
    )
