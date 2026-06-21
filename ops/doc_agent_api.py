"""
doc_agent_api.py
────────────────
HTTP REST server wrapping DocAgent on port 8767.
Uses stdlib only — no FastAPI / aiohttp dependency.

Endpoints:
    POST /v1/generate       — generate a document (single model)
    POST /v1/generate_dual  — dual pipeline: R1-70B→Qwen72B→Gemini quality gate
    GET  /health            — health check

POST /v1/generate — request body (JSON):
    {
        "user_request": "Write a JSA for confined space entry",
        "title":        "JSA — Confined Space Entry",         # optional
        "source_docs":  [...],                                # optional: [{title, summary, aims_process, iso_clause, file_name}]
        "web_context":  "...",                                # optional
        "out_dir":      "/path/to/output",                   # optional
        "model":        "qwen3:72b-q4_K_M",                    # optional override
        "ollama_base":  "http://192.168.72.225:11434"         # optional override
    }

Response (JSON):
    {
        "ok":      true,
        "path":    "/path/to/generated.docx",
        "preview": "first 800 chars of generated text",
        "title":   "document title"
    }
    or on error:
    {
        "ok":    false,
        "error": "message"
    }

Env vars:
    DOC_AGENT_API_PORT  — port (default: 8767)
    DOC_AGENT_API_HOST  — bind host (default: 0.0.0.0)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

log = logging.getLogger("doc_agent_api")

_PORT = int(os.environ.get("DOC_AGENT_API_PORT", "8767"))
_HOST = os.environ.get("DOC_AGENT_API_HOST", "0.0.0.0")


def _handle_generate(body: dict) -> dict:
    from doc_agent import DocAgent, DocGenerationRequest

    user_request = (body.get("user_request") or "").strip()
    if not user_request:
        return {"ok": False, "error": "user_request is required"}

    out_dir = body.get("out_dir")
    req = DocGenerationRequest(
        user_request=user_request,
        title=body.get("title") or None,
        source_docs=body.get("source_docs") or [],
        web_context=body.get("web_context") or None,
        out_dir=Path(out_dir) if out_dir else None,
        model=body.get("model") or None,
        ollama_base=body.get("ollama_base") or None,
        architecture_context=body.get("architecture_context") or {},
    )

    try:
        agent = DocAgent()
        path, preview, _score, _feedback = agent.generate(req)
        return {
            "ok": True,
            "path": str(path),
            "preview": preview,
            "title": path.stem,
        }
    except Exception as exc:
        log.exception("generate failed")
        return {"ok": False, "error": str(exc)}


def _handle_generate_dual(body: dict) -> dict:
    from doc_agent import DocAgent, DocGenerationRequest

    user_request = (body.get("user_request") or "").strip()
    if not user_request:
        return {"ok": False, "error": "user_request is required"}

    out_dir = body.get("out_dir")
    req = DocGenerationRequest(
        user_request=user_request,
        title=body.get("title") or None,
        source_docs=body.get("source_docs") or [],
        web_context=body.get("web_context") or None,
        out_dir=Path(out_dir) if out_dir else None,
        dual_pipeline=True,
        architecture_context=body.get("architecture_context") or {},
    )

    try:
        agent = DocAgent()
        path, preview, quality_score, quality_feedback = agent.generate(req)
        return {
            "ok": True,
            "path": str(path),
            "preview": preview,
            "title": path.stem,
            "pipeline": "dual",
            "quality_score": quality_score,
            "compliance_pct": int(round(quality_score * 100)),
            "feedback": quality_feedback,
            "scorer_model": "meta/llama-3.1-405b-instruct",
        }
    except Exception as exc:
        log.exception("generate_dual failed")
        return {"ok": False, "error": str(exc)}


def _handle_standards_search(body: dict) -> dict:
    """POST /v1/standards_search — RAG query over indexed international standards."""
    from docagent.standards_rag import query as rag_query

    question = (body.get("question") or body.get("query") or "").strip()
    if not question:
        return {"ok": False, "error": "question is required"}

    try:
        result = rag_query(
            question=question,
            top_k=body.get("top_k", 8),
            filter_doc_type=body.get("doc_type") or None,
            model=body.get("model") or None,
        )
        return {"ok": True, **result.to_dict()}
    except Exception as exc:
        log.exception("standards_search failed")
        return {"ok": False, "error": str(exc)}


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress default access log spam
        log.debug(fmt, *args)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True, "service": "doc_agent_api"})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        _ROUTES = ("/v1/generate", "/v1/generate/",
                   "/v1/generate_dual", "/v1/generate_dual/",
                   "/v1/standards_search", "/v1/standards_search/")
        if self.path not in _ROUTES:
            self._send_json(404, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            self._send_json(400, {"ok": False, "error": f"invalid JSON: {e}"})
            return

        try:
            if self.path.startswith("/v1/generate_dual"):
                result = _handle_generate_dual(body)
            elif self.path.startswith("/v1/standards_search"):
                result = _handle_standards_search(body)
            else:
                result = _handle_generate(body)
        except Exception:
            tb = traceback.format_exc()
            log.error("unhandled exception in do_POST:\n%s", tb)
            result = {"ok": False, "error": "internal server error", "detail": tb[-500:]}
        status = 200 if result.get("ok") else 500
        self._send_json(status, result)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log.info("doc_agent_api starting on %s:%d", _HOST, _PORT)
    server = _ThreadedHTTPServer((_HOST, _PORT), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("doc_agent_api stopped")


# ── HTTP client helper ─────────────────────────────────────────────────────────

class DocAgentClient:
    """
    Thin HTTP client for doc_agent_api.

    Usage:
        client = DocAgentClient()
        result = client.generate("Write a JSA for confined space entry")
        if result["ok"]:
            docx_path = Path(result["path"])
    """

    def __init__(self, base_url: str | None = None) -> None:
        port = int(os.environ.get("DOC_AGENT_API_PORT", "8767"))
        self.base = (base_url or f"http://localhost:{port}").rstrip("/")

    def generate(
        self,
        user_request: str,
        *,
        title: str | None = None,
        source_docs: list[dict] | None = None,
        web_context: str | None = None,
        out_dir: str | None = None,
        architecture_context: dict | None = None,
        model: str | None = None,
        ollama_base: str | None = None,
        timeout: float = 360.0,
    ) -> dict:
        import httpx
        payload = {"user_request": user_request}
        if title:
            payload["title"] = title
        if source_docs:
            payload["source_docs"] = source_docs
        if web_context:
            payload["web_context"] = web_context
        if out_dir:
            payload["out_dir"] = out_dir
        if architecture_context:
            payload["architecture_context"] = architecture_context
        if model:
            payload["model"] = model
        if ollama_base:
            payload["ollama_base"] = ollama_base

        r = httpx.post(f"{self.base}/v1/generate", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def generate_dual(
        self,
        user_request: str,
        *,
        title: str | None = None,
        source_docs: list[dict] | None = None,
        web_context: str | None = None,
        out_dir: str | None = None,
        architecture_context: dict | None = None,
        timeout: float = 1800.0,
    ) -> dict:
        import httpx
        payload: dict = {"user_request": user_request}
        if title:
            payload["title"] = title
        if source_docs:
            payload["source_docs"] = source_docs
        if web_context:
            payload["web_context"] = web_context
        if out_dir:
            payload["out_dir"] = out_dir
        if architecture_context:
            payload["architecture_context"] = architecture_context
        r = httpx.post(f"{self.base}/v1/generate_dual", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def health(self) -> bool:
        import httpx
        try:
            r = httpx.get(f"{self.base}/health", timeout=5.0)
            return r.status_code == 200 and r.json().get("ok", False)
        except Exception:
            return False


if __name__ == "__main__":
    main()
