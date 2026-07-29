#!/usr/bin/env python3
"""Read-only AIMS MCP bridge for Logi, Knomi, Argus, and closure status."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.logi.closed_loop import run_closed_loop


mcp = FastMCP("aims")


def _url(name: str, default: str) -> str:
    return os.environ.get(name, default).rstrip("/")


@mcp.tool()
def aims_connections() -> str:
    """Return configured internal AIMS service bindings without calling them."""
    return json.dumps(
        {
            "doc_agent": _url("DOC_AGENT_API_URL", "http://localhost:8767"),
            "omi": _url("OMI_API_URL", "http://localhost:8765"),
            "task_registry": _url("TASK_REGISTRY_URL", "http://localhost:8765"),
            "qdrant": _url("QDRANT_BASE_URL", "http://localhost:6333"),
            "knomi": _url("KNOMI_API_URL", "http://localhost:8768"),
            "argus": _url("ARGUS_API_URL", "http://localhost:8770"),
        },
        ensure_ascii=False,
    )


@mcp.tool()
def knomi_search(query: str, top_k: int = 5) -> str:
    """Search the internal Knomi service. This tool is read-only."""
    top_k = max(1, min(int(top_k), 20))
    response = httpx.post(
        f"{_url('KNOMI_API_URL', 'http://localhost:8768')}/search",
        json={"query": query, "top_k": top_k},
        timeout=20,
    )
    response.raise_for_status()
    return json.dumps(response.json(), ensure_ascii=False)


@mcp.tool()
def argus_health() -> str:
    """Read the internal Argus health endpoint."""
    response = httpx.get(f"{_url('ARGUS_API_URL', 'http://localhost:8770')}/health", timeout=10)
    response.raise_for_status()
    return json.dumps(response.json(), ensure_ascii=False)


@mcp.tool()
def closed_loop_preflight() -> str:
    """Inspect closed-loop readiness without applying benefit, cleanup, or certification."""
    report = run_closed_loop(ROOT, apply_benefit=False)
    return json.dumps(
        {
            "status": report["status"],
            "blockers": report["blockers"],
            "sessions_total": report["sessions_total"],
            "stale_session_count": report["stale_session_gate"]["count"],
            "certification_started": False,
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
