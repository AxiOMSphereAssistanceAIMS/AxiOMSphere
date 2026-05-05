#!/usr/bin/env python3
"""Test suite for Repairman Automation API.

Verifies:
1. Automation policy flags are correctly defined
2. HTTP endpoints enforce service token authentication
3. Task triggering respects automation policy
4. Model switching is protected
"""
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "ops" / "telegram"))
sys.path.insert(0, str(repo_root / "ops"))
sys.path.insert(0, str(repo_root))

import pytest


class TestAutomationPolicy:
    """Test automation policy flags."""

    def test_automation_flags_exist(self):
        """Verify all automation flags are defined."""
        from ops.telegram.repairman_bot import (
            AUTO_INSPECT, AUTO_STATUS, AUTO_CURRENT,
            AUTO_REPAIR, AUTO_FIX, AUTO_MODEL
        )
        assert isinstance(AUTO_INSPECT, bool)
        assert isinstance(AUTO_STATUS, bool)
        assert isinstance(AUTO_CURRENT, bool)
        assert isinstance(AUTO_REPAIR, bool)
        assert isinstance(AUTO_FIX, bool)
        assert isinstance(AUTO_MODEL, bool)

    def test_automation_flags_default_values(self):
        """Verify automation flags are enabled by default."""
        from ops.telegram.repairman_bot import (
            AUTO_INSPECT, AUTO_STATUS, AUTO_CURRENT,
            AUTO_REPAIR, AUTO_FIX, AUTO_MODEL
        )
        assert AUTO_INSPECT is True, "inspect should be automatic (read-only)"
        assert AUTO_STATUS is True, "status should be automatic (informational)"
        assert AUTO_CURRENT is True, "current should be automatic (retry threshold)"
        assert AUTO_REPAIR is True, "repair should be automatic (concept unchanged)"
        assert AUTO_FIX is True, "fix should be automatic (operability restoration)"
        assert AUTO_MODEL is True, "model should be automatic (system reliability)"


class TestRepairmanAPI:
    """Test repairman_api HTTP service."""

    def test_api_imports_service_auth(self):
        """Verify repairman_api imports verify_service_token."""
        import ops.telegram.repairman_api as m
        assert hasattr(m, "verify_service_token") or "verify_service_token" in dir(m)

    def test_trigger_endpoint_has_auth(self):
        """Verify /trigger endpoint has Depends(verify_service_token)."""
        import inspect
        from ops.telegram.repairman_api import trigger_task

        source = inspect.getsource(trigger_task)
        assert "Depends(verify_service_token)" in source, \
            "trigger_task() should have _auth: None = Depends(verify_service_token) parameter"

    def test_switch_model_endpoint_has_auth(self):
        """Verify /switch_model endpoint has Depends(verify_service_token)."""
        import inspect
        from ops.telegram.repairman_api import switch_model

        source = inspect.getsource(switch_model)
        assert "Depends(verify_service_token)" in source, \
            "switch_model() should have _auth: None = Depends(verify_service_token) parameter"

    def test_status_endpoint_no_auth(self):
        """Verify /status endpoint does NOT require auth (informational)."""
        import inspect
        from ops.telegram.repairman_api import get_status

        source = inspect.getsource(get_status)
        assert "Depends(verify_service_token)" not in source, \
            "get_status() should NOT require authentication (informational endpoint)"

    def test_health_endpoint_no_auth(self):
        """Verify /health endpoint does NOT require auth."""
        import inspect
        from ops.telegram.repairman_api import health

        source = inspect.getsource(health)
        assert "Depends(verify_service_token)" not in source, \
            "health() should NOT require authentication"


class TestRepairmanBotUpdates:
    """Test repairman_bot.py updates."""

    def test_run_repairman_has_auto_triggered_param(self):
        """Verify run_repairman() has auto_triggered parameter."""
        import inspect
        from ops.telegram.repairman_bot import run_repairman

        sig = inspect.signature(run_repairman)
        assert "auto_triggered" in sig.parameters, \
            "run_repairman() should have auto_triggered parameter"
        assert sig.parameters["auto_triggered"].default is False, \
            "auto_triggered should default to False"

    def test_help_text_includes_auto_markers(self):
        """Verify help text includes [AUTO] markers."""
        from ops.telegram.repairman_bot import help_text

        text = help_text()
        assert "[AUTO]" in text, "help_text should include [AUTO] markers"
        assert "LogiOrchestrator" in text or "ArgusAgent" in text, \
            "help_text should mention automated triggering sources"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
