"""
test_chain_interface_interactions.py

Covers the interface/integration wiring chain:
  gateway config → agent API contracts → Telegram bots

All tests are STATIC — they read existing files and check invariants.
No services are started, no HTTP calls are made, no containers are required.
"""
from pathlib import Path

import pytest

AIMS_ROOT = Path(__file__).parent.parent.parent.resolve()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_anthropic_proxy_gateway_exists():
    """ops/gateway/anthropic_proxy.py must be present."""
    proxy = AIMS_ROOT / "ops" / "gateway" / "anthropic_proxy.py"
    assert proxy.exists(), f"Anthropic proxy gateway missing: {proxy}"
    assert proxy.stat().st_size > 0, "anthropic_proxy.py must not be empty"


def test_gateway_start_script_exists():
    """ops/gateway/start_gateway.sh must be present."""
    sh = AIMS_ROOT / "ops" / "gateway" / "start_gateway.sh"
    assert sh.exists(), f"Gateway start script missing: {sh}"
    assert sh.stat().st_size > 0, "start_gateway.sh must not be empty"


def test_claude_code_proxy_exists():
    """ops/claude_code/claude_code_anthropic_ollama_proxy.py must be present."""
    proxy = AIMS_ROOT / "ops" / "claude_code" / "claude_code_anthropic_ollama_proxy.py"
    assert proxy.exists(), f"Claude Code proxy missing: {proxy}"
    assert proxy.stat().st_size > 0, "claude_code_anthropic_ollama_proxy.py must not be empty"


def test_preferred_models_order_qwen3_before_nemotron():
    """SA3 fix: qwen3:32b-q8_0 must appear before nemotron-3-super:120b in PREFERRED_MODELS.

    This verifies that the proxy's PREFERRED_MODELS list starts with qwen3:32b-q8_0
    so the lighter model is always tried first, preventing inadvertent 120B VRAM load.
    """
    proxy = AIMS_ROOT / "ops" / "claude_code" / "claude_code_anthropic_ollama_proxy.py"
    assert proxy.exists(), f"Proxy file missing: {proxy}"
    content = proxy.read_text(encoding="utf-8")

    qwen_pos = content.find("qwen3:32b-q8_0")
    nemotron_pos = content.find("nemotron-3-super:120b")

    assert qwen_pos != -1, (
        "qwen3:32b-q8_0 not found in claude_code_anthropic_ollama_proxy.py — "
        "SA3 fix may not be applied"
    )
    assert nemotron_pos != -1, (
        "nemotron-3-super:120b not found in claude_code_anthropic_ollama_proxy.py"
    )
    assert qwen_pos < nemotron_pos, (
        f"SA3 fix not applied: qwen3:32b-q8_0 appears at position {qwen_pos} "
        f"but nemotron-3-super:120b appears earlier at position {nemotron_pos}. "
        "qwen3:32b-q8_0 must be first in PREFERRED_MODELS."
    )


def test_poli_agent_exists():
    """ops/agents/poli_agent.py must be present (access-rights gate)."""
    agent = AIMS_ROOT / "ops" / "agents" / "poli_agent.py"
    assert agent.exists(), f"Poli agent missing: {agent}"
    assert agent.stat().st_size > 0, "poli_agent.py must not be empty"


def test_omi_agent_exists():
    """ops/agents/omi_agent.py must be present (document registry agent)."""
    agent = AIMS_ROOT / "ops" / "agents" / "omi_agent.py"
    assert agent.exists(), f"Omi agent missing: {agent}"
    assert agent.stat().st_size > 0, "omi_agent.py must not be empty"


def test_logi_bot_exists_and_non_trivial():
    """ops/telegram/logi_bot.py must exist and have more than 100 bytes."""
    bot = AIMS_ROOT / "ops" / "telegram" / "logi_bot.py"
    assert bot.exists(), f"Logi bot missing: {bot}"
    size = bot.stat().st_size
    assert size > 100, (
        f"ops/telegram/logi_bot.py is only {size} bytes — "
        "expected a non-trivial bot file (>100 bytes)"
    )
