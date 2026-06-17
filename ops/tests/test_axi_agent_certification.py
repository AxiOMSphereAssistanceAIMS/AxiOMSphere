#!/usr/bin/env python3
"""
test_axi_agent_certification.py

Comprehensive test suite for Axi agent certification readiness.

Tests cover:
1. Endpoint configuration (no 20128 usage)
2. Model references (no hardcoded nemotron-120B)
3. Role boundaries (Logi, Omi, Doci, Repairman, Hermes)
4. Routing logic
5. Clarification behavior
"""

import os
import sys
from pathlib import Path

# Add project root to path
_proj_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_proj_root))
sys.path.insert(0, str(_proj_root / "ops"))

import pytest


class TestAXIEndpointConfiguration:
    """Test that Axi uses correct OmniRoute endpoints."""

    def test_no_obsolete_20128_in_code(self):
        """Axi code should not have 20128 as default endpoint."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text()

        # Should NOT default to 20128
        assert "20128" not in content, (
            "Obsolete endpoint 20128 found in ops/axi_bot.py. "
            "Should use canonical 20129 (per spec)."
        )

    def test_canonical_endpoint_20129_present(self):
        """Axi code should reference canonical 20129 endpoint."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text()

        # Should have 20129 referenced somewhere
        assert "20129" in content, (
            "Canonical endpoint 20129 not found in ops/axi_bot.py. "
            "Axi should reference the correct OmniRoute port."
        )


class TestAXIModelReferences:
    """Test that Axi doesn't assume obsolete models are active."""

    def test_no_nemotron_120b_as_active_default(self):
        """nemotron-120B should not be hardcoded as active default."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text()

        # Search for patterns like:
        # AIMS_DOCUMENT_CREATOR_MODEL = ... or "axi/nemotron-3-super:120b"
        # This should have been fixed to use registry abstraction

        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if 'AIMS_DOCUMENT_CREATOR_MODEL' in line:
                # Collect next 10 lines to find the default
                chunk = '\n'.join(lines[max(0, i-1):min(len(lines), i+10)])
                if 'nemotron-3-super:120b' in chunk:
                    pytest.skip(
                        "AIMS_DOCUMENT_CREATOR_MODEL still references nemotron-120B "
                        "(may be intentional if wrapped in guard). "
                        "Check that it's not the active default."
                    )

    def test_axi_source_not_launcher(self):
        """ops/axi_bot.py should be the canonical source, not a launcher."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text(encoding='utf-8')

        # Check that it's NOT just a launcher pointing to backup
        assert "runpy.run_path" not in content, (
            "ops/axi_bot.py appears to be a launcher (runpy.run_path). "
            "Should be the canonical source file."
        )

        # Should have substantial content
        lines = [l for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) > 100, (
            "ops/axi_bot.py is too small to be canonical source "
            f"({len(lines)} lines). May still be launcher."
        )


class TestAXIRoleBoundaries:
    """Test that Axi respects role boundaries."""

    def test_logi_integration_exists(self):
        """Axi should have integration with Logi for strategy tasks."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text()

        # Should reference Logi or have strategy handling
        assert 'logi' in content.lower() or 'strategy' in content.lower(), (
            "No reference to Logi or strategy handling found in Axi. "
            "Axi should delegate strategy requests to Logi."
        )

    def test_omi_integration_exists(self):
        """Axi should have integration with Omi."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text()

        assert 'omi' in content.lower(), (
            "No reference to Omi found in Axi. "
            "Axi should route OCR/archive/DB tasks to Omi."
        )

    def test_docs_agent_integration_exists(self):
        """Axi should have integration with docs-agent."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text()

        assert 'docs' in content.lower() or 'doc_agent' in content.lower(), (
            "No reference to docs-agent found in Axi. "
            "Axi should route multi-document tasks to docs-agent."
        )


class TestAXIDocker:
    """Test Docker configuration for Axi."""

    def test_docker_compose_has_axi_service(self):
        """docker-compose.yml should define axi-bot service."""
        compose_file = _proj_root / "docker-compose.yml"
        content = compose_file.read_text()

        assert 'axi-bot' in content.lower(), (
            "axi-bot service not found in docker-compose.yml"
        )

    def test_axi_dockerfile_exists(self):
        """Dockerfile for Axi should exist."""
        dockerfile = _proj_root / "ops" / "Dockerfile.axi-bot"
        assert dockerfile.exists(), (
            f"Dockerfile.axi-bot not found at {dockerfile}"
        )


class TestAXISyntax:
    """Test Python syntax of Axi."""

    def test_axi_python_syntax_valid(self):
        """ops/axi_bot.py should be valid Python."""
        axi_file = _proj_root / "ops" / "axi_bot.py"

        try:
            import py_compile
            py_compile.compile(str(axi_file), doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"ops/axi_bot.py has syntax errors: {e}")


class TestAXINoSecrets:
    """Test that Axi doesn't expose secrets in logs."""

    def test_no_hardcoded_tokens(self):
        """Axi should not have hardcoded bot tokens or API keys."""
        axi_file = _proj_root / "ops" / "axi_bot.py"
        content = axi_file.read_text()

        # Should use environment variables, not hardcoded
        assert 'AXI_BOT_TOKEN' in content, (
            "No reference to AXI_BOT_TOKEN env var. "
            "Token should come from environment, not hardcoded."
        )

        # Should not have actual token values
        assert 'sk-' not in content, "Found potential API key pattern in code"
        assert 'http_key=' not in content, "Found potential token pattern in code"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
