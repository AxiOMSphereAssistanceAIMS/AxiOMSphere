"""
test_chain_bot_pipeline.py

Covers the bot pipeline management chain:
  bot source files → docker-compose wiring → systemd service unit

All tests are STATIC — they read existing files and check invariants.
No services are started, no HTTP calls are made, no containers are required.
"""
from pathlib import Path

import pytest

AIMS_ROOT = Path(__file__).parent.parent.parent.resolve()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_axi_bot_exists_and_non_trivial():
    """ops/axi_bot.py must exist and be a substantial file (>1000 bytes)."""
    bot = AIMS_ROOT / "ops" / "axi_bot.py"
    assert bot.exists(), f"axi_bot.py missing: {bot}"
    size = bot.stat().st_size
    assert size > 1000, (
        f"ops/axi_bot.py is only {size} bytes — expected a substantial bot file (>1000 bytes)"
    )


def test_argus_bot_exists():
    """ops/argus/argus_bot.py must be present."""
    bot = AIMS_ROOT / "ops" / "argus" / "argus_bot.py"
    assert bot.exists(), f"argus_bot.py missing: {bot}"
    assert bot.stat().st_size > 0, "argus_bot.py must not be empty"


def test_logi_bot_exists():
    """ops/telegram/logi_bot.py must be present."""
    bot = AIMS_ROOT / "ops" / "telegram" / "logi_bot.py"
    assert bot.exists(), f"logi_bot.py missing: {bot}"
    assert bot.stat().st_size > 0, "logi_bot.py must not be empty"


def test_docker_compose_contains_axi_bot_service():
    """docker-compose.yml must define the axi-bot service."""
    compose = AIMS_ROOT / "docker-compose.yml"
    assert compose.exists(), f"docker-compose.yml missing: {compose}"
    content = compose.read_text(encoding="utf-8")
    assert "axi-bot" in content, (
        "docker-compose.yml does not reference 'axi-bot' — "
        "the Axi bot service must be wired in compose"
    )


def test_docker_compose_contains_argus_bot_service():
    """docker-compose.yml must define the argus-bot service."""
    compose = AIMS_ROOT / "docker-compose.yml"
    assert compose.exists(), f"docker-compose.yml missing: {compose}"
    content = compose.read_text(encoding="utf-8")
    assert "argus-bot" in content, (
        "docker-compose.yml does not reference 'argus-bot' — "
        "the Argus bot service must be wired in compose"
    )


def test_docker_compose_has_telegram_bots_profile():
    """docker-compose.yml must contain the telegram-bots profile."""
    compose = AIMS_ROOT / "docker-compose.yml"
    assert compose.exists(), f"docker-compose.yml missing: {compose}"
    content = compose.read_text(encoding="utf-8")
    assert "telegram-bots" in content, (
        "docker-compose.yml does not contain 'telegram-bots' profile — "
        "required for selective bot startup"
    )


def test_aims_bots_service_unit_exists():
    """ops/scripts/aims-bots.service systemd unit must exist (SA2 autostart fix)."""
    svc = AIMS_ROOT / "ops" / "scripts" / "aims-bots.service"
    assert svc.exists(), (
        f"aims-bots.service missing at {svc}. "
        "SA2 requires this service unit for bot autostart on reboot."
    )
    assert svc.stat().st_size > 0, "aims-bots.service must not be empty"
