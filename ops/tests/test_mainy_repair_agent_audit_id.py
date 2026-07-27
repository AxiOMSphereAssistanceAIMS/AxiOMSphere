from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def _client():
    from ops.agents.mainy_repair_agent import app
    return TestClient(app)


def _auth_headers() -> dict:
    from ops.core.service_auth import service_headers
    return service_headers()


def _payload(audit_id: str) -> dict:
    return {
        "action": {"type": "noop"},
        "audit_id": audit_id,
        "authorized_by": "test",
    }


def test_empty_audit_id_rejected():
    client = _client()
    resp = client.post("/execute", json=_payload(""), headers=_auth_headers())
    assert resp.status_code == 403
    assert "audit_id" in resp.json()["detail"]


def test_non_uuid_audit_id_rejected():
    client = _client()
    resp = client.post("/execute", json=_payload("yes"), headers=_auth_headers())
    assert resp.status_code == 403
    assert "audit_id" in resp.json()["detail"]


def test_valid_uuid_audit_id_passes_the_guard():
    client = _client()
    with patch("ops.agents.mainy_repair_agent._executor") as mock_executor:
        mock_executor.execute.return_value = {"ok": True, "action": "noop", "detail": "done"}
        resp = client.post(
            "/execute",
            json=_payload("3fa85f64-5717-4562-b3fc-2c963f66afa6"),
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
