#!/usr/bin/env python3
"""Test suite for Production Hardening Patch 2 — Service Token Authentication.

Verifies:
1. All protected endpoints have Depends(verify_service_token) in their signature
2. verify_service_token raises HTTP 401 with wrong/missing Authorization header
3. verify_service_token passes (returns None) with correct token
4. service_headers() returns correct Authorization header dict
"""
import inspect
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "ops"))
sys.path.insert(0, str(repo_root))

from core.service_auth import SERVICE_TOKEN, verify_service_token, service_headers


class TestServiceAuthModule:
    """Test the core service_auth module."""

    def test_service_token_from_env(self):
        """SERVICE_TOKEN should default to 'aims-service-token' if not in env."""
        assert SERVICE_TOKEN is not None
        assert isinstance(SERVICE_TOKEN, str)
        assert len(SERVICE_TOKEN) > 0

    def test_verify_service_token_rejects_missing_header(self):
        """verify_service_token should raise HTTP 401 if Authorization header is missing."""
        with pytest.raises(HTTPException) as exc_info:
            verify_service_token(authorization=None)
        assert exc_info.value.status_code == 401
        assert "service token required" in exc_info.value.detail

    def test_verify_service_token_rejects_wrong_token(self):
        """verify_service_token should raise HTTP 401 if Authorization header is wrong."""
        with pytest.raises(HTTPException) as exc_info:
            verify_service_token(authorization="Bearer wrong-token")
        assert exc_info.value.status_code == 401
        assert "service token required" in exc_info.value.detail

    def test_verify_service_token_rejects_missing_bearer_prefix(self):
        """verify_service_token should raise HTTP 401 if Bearer prefix is missing."""
        with pytest.raises(HTTPException) as exc_info:
            verify_service_token(authorization=SERVICE_TOKEN)
        assert exc_info.value.status_code == 401

    def test_verify_service_token_accepts_correct_header(self):
        """verify_service_token should return None (not raise) with correct Authorization header."""
        result = verify_service_token(authorization=f"Bearer {SERVICE_TOKEN}")
        assert result is None

    def test_service_headers_returns_dict(self):
        """service_headers() should return a dict with Authorization key."""
        headers = service_headers()
        assert isinstance(headers, dict)
        assert "Authorization" in headers

    def test_service_headers_has_bearer_format(self):
        """service_headers() should return 'Bearer <token>' format."""
        headers = service_headers()
        auth = headers["Authorization"]
        assert auth.startswith("Bearer ")
        assert auth == f"Bearer {SERVICE_TOKEN}"


class TestMainyRepairAgentProtection:
    """Test that mainy_repair_agent.py /execute endpoint is protected."""

    def test_execute_endpoint_has_depends_decorator(self):
        """Verify execute() function has Depends(verify_service_token) in signature."""
        from ops.agents.mainy_repair_agent import execute

        source = inspect.getsource(execute)
        assert "Depends(verify_service_token)" in source, \
            "execute() should have _auth: None = Depends(verify_service_token) parameter"

    def test_execute_has_imports(self):
        """Verify mainy_repair_agent imports verify_service_token."""
        import ops.agents.mainy_repair_agent as m
        # If import failed, this would have raised an exception during module import
        assert hasattr(m, "verify_service_token") or "verify_service_token" in dir(m)


class TestTrainiAgentProtection:
    """Test that traini_agent.py endpoints are protected."""

    def test_trigger_ft_has_depends_decorator(self):
        """Verify trigger_ft() has Depends(verify_service_token) in signature."""
        from ops.agents.traini_agent import trigger_ft

        source = inspect.getsource(trigger_ft)
        assert "Depends(verify_service_token)" in source, \
            "trigger_ft() should have _auth: None = Depends(verify_service_token) parameter"

    def test_promote_model_has_depends_decorator(self):
        """Verify promote_model() has Depends(verify_service_token) in signature."""
        from ops.agents.traini_agent import promote_model

        source = inspect.getsource(promote_model)
        assert "Depends(verify_service_token)" in source, \
            "promote_model() should have _auth: None = Depends(verify_service_token) parameter"


class TestKnomiAgentProtection:
    """Test that knomi_agent.py /reindex endpoint is protected."""

    def test_reindex_has_depends_decorator(self):
        """Verify reindex() has Depends(verify_service_token) in signature."""
        from ops.agents.knomi_agent import reindex

        source = inspect.getsource(reindex)
        assert "Depends(verify_service_token)" in source, \
            "reindex() should have _auth: None = Depends(verify_service_token) parameter"


class TestArgusAgentProtection:
    """Test that argus_agent.py /refresh endpoint is protected."""

    def test_force_refresh_has_depends_decorator(self):
        """Verify force_refresh() has Depends(verify_service_token) in signature."""
        from ops.agents.argus_agent import force_refresh

        source = inspect.getsource(force_refresh)
        assert "Depends(verify_service_token)" in source, \
            "force_refresh() should have _auth: None = Depends(verify_service_token) parameter"


class TestPoliAgentProtection:
    """Test that poli_agent.py /check endpoint is protected."""

    def test_check_has_depends_decorator(self):
        """Verify check() has Depends(verify_service_token) in signature."""
        from ops.agents.poli_agent import check

        source = inspect.getsource(check)
        assert "Depends(verify_service_token)" in source, \
            "check() should have _auth: None = Depends(verify_service_token) parameter"


class TestCallerHelperProtection:
    """Test that caller helpers pass service tokens."""

    def test_supervisor_agent_imports_service_headers(self):
        """Verify supervisor_agent imports service_headers."""
        import ops.agents.supervisor_agent as m
        # The import should work if added correctly
        assert hasattr(m, "service_headers") or "service_headers" in dir(m)

    def test_supervisor_agent_call_helper_uses_headers(self):
        """Verify supervisor_agent._call() passes headers=service_headers()."""
        from ops.agents.supervisor_agent import _call

        source = inspect.getsource(_call)
        assert "headers=service_headers()" in source, \
            "_call() should pass headers=service_headers() to httpx.post()"

    def test_tool_registry_mcp_imports_service_headers(self):
        """Verify tool_registry_mcp imports service_headers."""
        import ops.tool_registry_mcp as m
        assert hasattr(m, "service_headers") or "service_headers" in dir(m)

    def test_tool_registry_mcp_http_helper_uses_headers_get(self):
        """Verify tool_registry_mcp._http() passes headers for GET requests."""
        from ops.tool_registry_mcp import _http

        source = inspect.getsource(_http)
        # Check that both GET and POST paths pass headers
        assert source.count("headers=service_headers()") >= 2, \
            "_http() should pass headers=service_headers() to both GET and POST requests"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
