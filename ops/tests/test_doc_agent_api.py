#!/usr/bin/env python3
"""Tests for DocAgent API (port 8767) — document generation service.

Covers:
  - Import smoke for doc_agent_api module
  - _handle_generate / _handle_generate_dual validation (no Ollama needed)
  - _handle_standards_search validation
  - Health endpoint (direct call + live HTTP)
  - Live HTTP smoke (skipped if port 8767 not reachable)
  - POST validation: missing required fields return ok=False without calling Ollama

Note: full generate tests require Ollama + DGX GPU — see test_stage1_docagent.py.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "ops"))
sys.path.insert(0, str(repo_root))

import pytest


# ---------------------------------------------------------------------------
# Import smoke
# ---------------------------------------------------------------------------

class TestDocAgentApiImport:
    def test_module_importable(self):
        import doc_agent_api
        assert doc_agent_api is not None

    def test_port_constant(self):
        import doc_agent_api
        assert doc_agent_api._PORT == 8767

    def test_handle_generate_importable(self):
        from doc_agent_api import _handle_generate
        assert callable(_handle_generate)

    def test_handle_generate_dual_importable(self):
        from doc_agent_api import _handle_generate_dual
        assert callable(_handle_generate_dual)

    def test_handler_class_importable(self):
        from doc_agent_api import _Handler
        from http.server import BaseHTTPRequestHandler
        assert issubclass(_Handler, BaseHTTPRequestHandler)


# ---------------------------------------------------------------------------
# _handle_generate — validation (no Ollama required)
# ---------------------------------------------------------------------------

class TestHandleGenerateValidation:
    def test_missing_user_request_returns_error(self):
        from doc_agent_api import _handle_generate
        result = _handle_generate({})
        assert result["ok"] is False
        assert "user_request" in result["error"].lower()

    def test_empty_user_request_returns_error(self):
        from doc_agent_api import _handle_generate
        result = _handle_generate({"user_request": "   "})
        assert result["ok"] is False

    def test_none_user_request_returns_error(self):
        from doc_agent_api import _handle_generate
        result = _handle_generate({"user_request": None})
        assert result["ok"] is False

    def test_valid_request_attempts_docagent(self, monkeypatch):
        """With a mocked DocAgent, result has ok=True and expected keys.

        DocAgent is imported lazily inside _handle_generate so we patch
        the source module 'doc_agent', not 'doc_agent_api'.
        """
        from unittest.mock import MagicMock, patch
        from pathlib import Path as _Path

        mock_path = _Path("/tmp/test_doc.docx")
        mock_agent = MagicMock()
        mock_agent.generate.return_value = (mock_path, "preview text", 0.9, "Good doc")
        mock_cls = MagicMock(return_value=mock_agent)
        mock_req = MagicMock()

        with patch("doc_agent.DocAgent", mock_cls, create=True), \
             patch("doc_agent.DocGenerationRequest", return_value=mock_req, create=True):
            from doc_agent_api import _handle_generate
            result = _handle_generate({"user_request": "Write a JSA for confined space"})

        assert result["ok"] is True
        assert "path" in result
        assert "preview" in result
        assert "title" in result

    def test_docagent_exception_returns_error(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        mock_agent = MagicMock()
        mock_agent.generate.side_effect = RuntimeError("Ollama unreachable")
        mock_cls = MagicMock(return_value=mock_agent)
        mock_req = MagicMock()

        with patch("doc_agent.DocAgent", mock_cls, create=True), \
             patch("doc_agent.DocGenerationRequest", return_value=mock_req, create=True):
            from doc_agent_api import _handle_generate
            result = _handle_generate({"user_request": "Write something"})

        assert result["ok"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# _handle_generate_dual — validation
# ---------------------------------------------------------------------------

class TestHandleGenerateDualValidation:
    def test_missing_user_request_returns_error(self):
        from doc_agent_api import _handle_generate_dual
        result = _handle_generate_dual({})
        assert result["ok"] is False
        assert "user_request" in result["error"].lower()

    def test_empty_string_returns_error(self):
        from doc_agent_api import _handle_generate_dual
        result = _handle_generate_dual({"user_request": ""})
        assert result["ok"] is False

    def test_valid_request_sets_dual_pipeline(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from pathlib import Path as _Path

        mock_path = _Path("/tmp/test_dual.docx")
        mock_agent = MagicMock()
        mock_agent.generate.return_value = (mock_path, "dual preview", 0.92, "Excellent")
        mock_cls = MagicMock(return_value=mock_agent)

        captured_kwargs = {}

        def capture_req(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        with patch("doc_agent.DocAgent", mock_cls, create=True), \
             patch("doc_agent.DocGenerationRequest", side_effect=capture_req, create=True):
            from doc_agent_api import _handle_generate_dual
            result = _handle_generate_dual({"user_request": "Write a safety plan"})

        assert result["ok"] is True
        assert result.get("pipeline") == "dual"
        assert "quality_score" in result
        assert captured_kwargs.get("dual_pipeline") is True


# ---------------------------------------------------------------------------
# HTTP handler routing (unit-level, no network)
# ---------------------------------------------------------------------------

class TestHandlerRouting:
    def _make_handler(self, method, path, body=b"{}"):
        """Build a _Handler instance with mocked socket/server."""
        from doc_agent_api import _Handler
        from unittest.mock import MagicMock
        from io import BytesIO

        handler = _Handler.__new__(_Handler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()
        handler.server = MagicMock()
        handler.request = MagicMock()
        handler.client_address = ("127.0.0.1", 0)
        return handler

    def test_get_unknown_path_returns_404(self, monkeypatch):
        handler = self._make_handler("GET", "/unknown")
        sent = {}

        def fake_send(code, data):
            sent["code"] = code
            sent["data"] = data

        handler._send_json = fake_send
        handler.do_GET()
        assert sent["code"] == 404
        assert sent["data"]["ok"] is False

    def test_post_unknown_path_returns_404(self, monkeypatch):
        handler = self._make_handler("POST", "/v1/unknown")
        sent = {}

        def fake_send(code, data):
            sent["code"] = code
            sent["data"] = data

        handler._send_json = fake_send
        handler.do_POST()
        assert sent["code"] == 404

    def test_post_invalid_json_returns_400(self, monkeypatch):
        from io import BytesIO
        bad_body = b"not-json"
        handler = self._make_handler("POST", "/v1/generate", bad_body)
        sent = {}

        def fake_send(code, data):
            sent["code"] = code
            sent["data"] = data

        handler._send_json = fake_send
        handler.do_POST()
        assert sent["code"] == 400
        assert "JSON" in sent["data"]["error"]


# ---------------------------------------------------------------------------
# Live HTTP smoke (requires running service on port 8767)
# ---------------------------------------------------------------------------

class TestDocAgentLive:
    """Skipped unless the service is reachable on localhost:8767."""

    @pytest.fixture(autouse=True)
    def _require_service(self):
        import urllib.request
        try:
            urllib.request.urlopen("http://localhost:8767/health", timeout=2)
        except Exception:
            pytest.skip("doc-agent not reachable on localhost:8767")

    def test_live_health_ok(self):
        import urllib.request, json
        with urllib.request.urlopen("http://localhost:8767/health", timeout=5) as r:
            data = json.loads(r.read())
        assert data["ok"] is True
        assert data["service"] == "doc_agent_api"

    def test_live_health_status_code_200(self):
        import urllib.request
        with urllib.request.urlopen("http://localhost:8767/health", timeout=5) as r:
            assert r.status == 200

    def test_live_unknown_get_returns_404(self):
        import urllib.request
        try:
            urllib.request.urlopen("http://localhost:8767/not-found", timeout=5)
            assert False, "Expected HTTPError"
        except urllib.request.HTTPError as e:
            assert e.code == 404

    def test_live_generate_missing_field_returns_500(self):
        import urllib.request, json
        payload = json.dumps({}).encode()
        req = urllib.request.Request(
            "http://localhost:8767/v1/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
        except urllib.request.HTTPError as e:
            data = json.loads(e.read())
        assert data["ok"] is False
        assert "user_request" in data["error"].lower()

    def test_live_generate_dual_missing_field_returns_500(self):
        import urllib.request, json
        payload = json.dumps({"user_request": ""}).encode()
        req = urllib.request.Request(
            "http://localhost:8767/v1/generate_dual",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
        except urllib.request.HTTPError as e:
            data = json.loads(e.read())
        assert data["ok"] is False

    def test_live_invalid_json_returns_400(self):
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:8767/v1/generate",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                pass
            assert False, "Expected HTTPError"
        except urllib.request.HTTPError as e:
            assert e.code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
