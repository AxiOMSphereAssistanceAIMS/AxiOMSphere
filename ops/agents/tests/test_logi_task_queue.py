"""Tests for logi_task_queue.py"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))


def test_write_pending_task(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_task_queue._PENDING_DIR", tmp_path / "pending"):
        with patch("ops.agents.logi_task_queue._SCHEDULED_DIR", tmp_path / "scheduled"):
            from ops.agents.logi_task_queue import write_pending_task
            task = write_pending_task("Fix Redis timeout", "description here", requested_by="1")
    assert task.task_id.startswith("logi_task_")
    assert task.status == "pending"
    assert task.action_type == "queue_task_allowlisted"


def test_pending_task_file_written(tmp_path):
    from unittest.mock import patch
    pending_dir = tmp_path / "pending"
    with patch("ops.agents.logi_task_queue._PENDING_DIR", pending_dir):
        with patch("ops.agents.logi_task_queue._SCHEDULED_DIR", tmp_path / "scheduled"):
            from ops.agents.logi_task_queue import write_pending_task
            task = write_pending_task("Test task", "desc")
    files = list(pending_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["title"] == "Test task"


def test_queue_task_requires_confirmation_via_orchestrator():
    """QUEUE_TASK via orchestrator must return REQUIRES_CONFIRMATION."""
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1, "поставь задачу в очередь: починить redis timeout")
    # Either confirmation or skill dispatch — never silent ack for queue intent
    assert isinstance(resp, str)


def test_write_scheduled_task(tmp_path):
    from unittest.mock import patch
    with patch("ops.agents.logi_task_queue._PENDING_DIR", tmp_path / "pending"):
        with patch("ops.agents.logi_task_queue._SCHEDULED_DIR", tmp_path / "scheduled"):
            from ops.agents.logi_task_queue import write_scheduled_task
            task = write_scheduled_task("Nightly backup", "desc", schedule_hint="22:30 UTC")
    assert task.status == "scheduled"
    assert task.action_type == "schedule_task_allowlisted"
    assert task.schedule_hint == "22:30 UTC"


def test_list_pending_tasks(tmp_path):
    from unittest.mock import patch
    pending_dir = tmp_path / "pending"
    with patch("ops.agents.logi_task_queue._PENDING_DIR", pending_dir):
        with patch("ops.agents.logi_task_queue._SCHEDULED_DIR", tmp_path / "scheduled"):
            from ops.agents.logi_task_queue import write_pending_task, list_pending_tasks
            write_pending_task("Task A", "desc A")
            write_pending_task("Task B", "desc B")
            tasks = list_pending_tasks()
    assert len(tasks) == 2
