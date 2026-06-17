"""
test_chain_skill_lifecycle.py

Covers the skill lifecycle chain:
  skill registry → agent wiring → selector → per-agent smoke evals

All tests are STATIC — they read existing files and check invariants.
No services are started, no HTTP calls are made, no containers are required.
"""
import yaml
from pathlib import Path

import pytest

AIMS_ROOT = Path(__file__).parent.parent.parent.resolve()
EVALS_DIR = AIMS_ROOT / "ops" / "evals"

# Agents that must have at least one dedicated eval smoke file in ops/evals/
MAIN_AGENTS = ["axi", "argus", "logi", "repairman", "poli"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_skill_registry_exists_and_valid():
    """ops/agents/agent_skill_registry.yaml must parse as valid YAML."""
    reg = AIMS_ROOT / "ops" / "agents" / "agent_skill_registry.yaml"
    assert reg.exists(), f"Agent skill registry missing: {reg}"
    with reg.open() as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), "Registry must be a YAML mapping at the top level"
    assert len(data) > 0, "Registry must not be empty"


def test_imported_full_stack_skill_selector_exists():
    """ops/logi/imported_full_stack_skill_selector.py must be present (SA14 selector check)."""
    sel = AIMS_ROOT / "ops" / "logi" / "imported_full_stack_skill_selector.py"
    assert sel.exists(), f"Skill selector missing: {sel}"
    assert sel.stat().st_size > 0, "imported_full_stack_skill_selector.py must not be empty"


def test_per_agent_self_learning_loop_smoke_exists():
    """ops/evals/aims_per_agent_self_learning_loop_smoke.py must be present."""
    smoke = EVALS_DIR / "aims_per_agent_self_learning_loop_smoke.py"
    assert smoke.exists(), f"Self-learning loop smoke file missing: {smoke}"
    assert smoke.stat().st_size > 0, "Smoke file must not be empty"


def test_skill_candidate_workflow_smoke_exists():
    """ops/evals/aims_skill_candidate_workflow_smoke.py must be present."""
    smoke = EVALS_DIR / "aims_skill_candidate_workflow_smoke.py"
    assert smoke.exists(), f"Skill candidate workflow smoke missing: {smoke}"
    assert smoke.stat().st_size > 0, "Smoke file must not be empty"


@pytest.mark.parametrize("agent", MAIN_AGENTS)
def test_per_agent_eval_smoke_file_exists(agent):
    """Each main agent must have at least one dedicated eval smoke file in ops/evals/."""
    evals_files = list(EVALS_DIR.glob("*.py"))
    # A file qualifies if the agent name appears in its filename (e.g. axi_runtime_skill_smoke.py,
    # argus_autoheal_policy_eligibility_smoke.py, aims_repairman_hermes_skill_loop_smoke.py)
    matching = [
        f for f in evals_files
        if agent in f.stem.lower()
    ]
    assert matching, (
        f"No eval smoke file found for agent '{agent}' in {EVALS_DIR}. "
        f"Expected at least one file containing '{agent}' in its name."
    )


def test_repairman_rules_learned_exists():
    """aims_workspace/repairman_memory/rules_learned.md must be present."""
    rules = AIMS_ROOT / "aims_workspace" / "repairman_memory" / "rules_learned.md"
    assert rules.exists(), (
        f"Repairman rules_learned.md missing at {rules}. "
        "CLAUDE.md mandates loading this file at start of every repair session."
    )
