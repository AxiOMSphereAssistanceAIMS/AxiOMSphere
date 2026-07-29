from __future__ import annotations

import json

from ops.tool_registry_mcp import aims_connections


def test_aims_mcp_connections_are_structured(monkeypatch) -> None:
    monkeypatch.setenv("KNOMI_API_URL", "http://knomi:8002")
    result = json.loads(aims_connections())
    assert result["knomi"] == "http://knomi:8002"
    assert result["argus"].startswith("http://")
