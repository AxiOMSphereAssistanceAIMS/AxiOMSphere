#!/usr/bin/env python3
"""
Phase 4 — Omi AgentSchedulerAdapter wiring tests (12 tests).

Validates that Omi's heavy task types are correctly wired to the scheduler:

  1.  omi_docs_standards_dry_run is in argus _ALLOWED_TASK_TYPES (already added Phase 2)
  2.  omi_ocr_pipeline_run is in argus _ALLOWED_TASK_TYPES (Phase 4 addition)
  3.  submit() returns task_id in format omi_docs_standards_dry_run_<12hex>
  4.  submit() returns task_id in format omi_ocr_pipeline_run_<12hex>
  5.  submitted standards dry_run metadata has created_by="omi"
  6.  submitted standards dry_run metadata has no model_slot (cpu-only)
  7.  submitted standards dry_run metadata has vram_sensitive=False
  8.  submitted ocr_pipeline metadata has created_by="omi"
  9.  submitted ocr_pipeline metadata has resource_key set (exclusive)
  10. omi task types appear in task_scheduler _KNOWN_TYPE_DISPLAY_NAMES
  11. submit() calls set_task_metadata and schedule_task exactly once each
  12. Two submits of same type yield distinct task IDs
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scheduler.agent_scheduler_adapter import AgentSchedulerAdapter
from ops.scheduler.task_models import TaskMetadata, TaskStatus


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_adapter() -> AgentSchedulerAdapter:
    adapter = AgentSchedulerAdapter.__new__(AgentSchedulerAdapter)
    adapter._redis_url = "redis://localhost:6379"
    adapter._redis = AsyncMock()
    queue = MagicMock()
    queue.set_task_metadata = AsyncMock()
    queue.schedule_task = AsyncMock()
    adapter._queue = queue
    return adapter


async def _capture_submit(adapter, **kwargs):
    task_id = await adapter.submit(**kwargs)
    meta: TaskMetadata = adapter._queue.set_task_metadata.call_args[0][1]
    return task_id, meta


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — Allowlist presence
# ─────────────────────────────────────────────────────────────────────────────

class TestOmiAllowlistPresence:

    def setup_method(self):
        import sys as _sys
        _sys.modules.setdefault("argus_code_agent", MagicMock())
        from ops.argus.argus_orchestrator import _ALLOWED_TASK_TYPES
        self.allowed = _ALLOWED_TASK_TYPES

    def test_docs_standards_dry_run_allowed(self):
        assert "omi_docs_standards_dry_run" in self.allowed

    def test_ocr_pipeline_run_allowed(self):
        assert "omi_ocr_pipeline_run" in self.allowed


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — Task ID format
# ─────────────────────────────────────────────────────────────────────────────

class TestOmiTaskIdFormat:

    @pytest.mark.asyncio
    async def test_standards_dry_run_id_format(self):
        adapter = _make_adapter()
        task_id = await adapter.submit(
            task_type="omi_docs_standards_dry_run",
            command=["python", "ops/agents/omi_docs_standards_runner.py", "--dry-run"],
            created_by="omi",
        )
        prefix, suffix = task_id.rsplit("_", 1)
        assert prefix == "omi_docs_standards_dry_run"
        assert len(suffix) == 12
        int(suffix, 16)  # valid hex

    @pytest.mark.asyncio
    async def test_ocr_pipeline_run_id_format(self):
        adapter = _make_adapter()
        task_id = await adapter.submit(
            task_type="omi_ocr_pipeline_run",
            command=["python", "ops/evals/autonomous_launch/phase_06_ocr_pipeline.py"],
            created_by="omi",
        )
        assert task_id.startswith("omi_ocr_pipeline_run_")
        assert len(task_id.split("_")[-1]) == 12

    @pytest.mark.asyncio
    async def test_two_submits_produce_distinct_ids(self):
        adapter = _make_adapter()
        id1 = await adapter.submit(
            task_type="omi_ocr_pipeline_run",
            command=["python", "ocr.py"],
            created_by="omi",
        )
        id2 = await adapter.submit(
            task_type="omi_ocr_pipeline_run",
            command=["python", "ocr.py"],
            created_by="omi",
        )
        assert id1 != id2


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — Metadata correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestOmiMetadataCorrectness:

    @pytest.mark.asyncio
    async def test_standards_dry_run_created_by_omi(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="omi_docs_standards_dry_run",
            command=["python", "standards_runner.py", "--dry-run"],
            created_by="omi",
        )
        assert meta.created_by == "omi"

    @pytest.mark.asyncio
    async def test_standards_dry_run_no_model_slot(self):
        """Standards dry-run is cpu-only — no GPU slot required."""
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="omi_docs_standards_dry_run",
            command=["python", "standards_runner.py", "--dry-run"],
            created_by="omi",
        )
        assert meta.model_slot is None

    @pytest.mark.asyncio
    async def test_standards_dry_run_not_vram_sensitive(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="omi_docs_standards_dry_run",
            command=["python", "standards_runner.py", "--dry-run"],
            created_by="omi",
            vram_sensitive=False,
        )
        assert meta.vram_sensitive is False

    @pytest.mark.asyncio
    async def test_ocr_pipeline_created_by_omi(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="omi_ocr_pipeline_run",
            command=["python", "phase_06_ocr_pipeline.py"],
            created_by="omi",
            resource_key="ocr_pipeline_exclusive",
        )
        assert meta.created_by == "omi"

    @pytest.mark.asyncio
    async def test_ocr_pipeline_resource_key(self):
        """OCR pipeline uses an exclusive resource key to prevent concurrent runs."""
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="omi_ocr_pipeline_run",
            command=["python", "phase_06_ocr_pipeline.py"],
            created_by="omi",
            resource_key="ocr_pipeline_exclusive",
        )
        assert meta.resource_key == "ocr_pipeline_exclusive"


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — Display names and dispatch contract
# ─────────────────────────────────────────────────────────────────────────────

class TestOmiDisplayNamesAndDispatch:

    def test_omi_types_in_display_names(self):
        from ops.scheduler.task_scheduler import _KNOWN_TYPE_DISPLAY_NAMES
        assert "omi_docs_standards_dry_run" in _KNOWN_TYPE_DISPLAY_NAMES
        assert "omi_ocr_pipeline_run" in _KNOWN_TYPE_DISPLAY_NAMES

    @pytest.mark.asyncio
    async def test_set_task_metadata_called_once_per_submit(self):
        adapter = _make_adapter()
        await adapter.submit(
            task_type="omi_docs_standards_dry_run",
            command=["python", "standards_runner.py"],
            created_by="omi",
        )
        adapter._queue.set_task_metadata.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schedule_task_called_once_per_submit(self):
        adapter = _make_adapter()
        await adapter.submit(
            task_type="omi_ocr_pipeline_run",
            command=["python", "ocr.py"],
            created_by="omi",
        )
        adapter._queue.schedule_task.assert_awaited_once()
