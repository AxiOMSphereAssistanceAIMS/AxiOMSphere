from __future__ import annotations

from pathlib import Path

from ops.skill_task_registry import TaskRegistry
from ops.task_registry_api import TaskRegistryClient


def test_task_registry_cancel_transitions_pending_task(tmp_path: Path) -> None:
    db = tmp_path / "aims_tasks.db"
    reg = TaskRegistry(db)
    task_id = reg.register("repairman follow-up", source="argus", chat_id="argus")

    assert reg.cancel(task_id, reason="operator cancelled") is True
    task = reg.get(task_id)
    assert task is not None
    assert task.status == "cancelled"
    assert "operator cancelled" in task.error
    assert reg.start(task_id, assigned_to="repairman") is False


def test_task_registry_client_cancel_uses_cancel_status() -> None:
    client = TaskRegistryClient("http://localhost:8765")

    def fake_request(method: str, path: str, body: dict | None = None) -> dict:
        assert method == "PATCH"
        assert path.endswith("/cancel")
        assert body == {"reason": "operator cancelled"}
        return {"task_id": "task_123", "status": "cancelled"}

    client._request = fake_request  # type: ignore[method-assign]
    assert client.cancel("task_123", reason="operator cancelled") is True
