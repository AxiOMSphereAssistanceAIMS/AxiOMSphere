#!/usr/bin/env python3
"""
BP-12 / BP-13 — Doci + Knomi scheduler adoption tests.

Validates that the two remaining deferred bypass paths are registered
correctly in the scheduler allowlist and display-name table.

Tests
─────
A. doci_doc_generation_batch in _ALLOWED_TASK_TYPES
B. knomi_reindex in _ALLOWED_TASK_TYPES
C. doci_doc_generation_batch NOT in _GATED_TASK_TYPES (CPU-only, no gate needed)
D. knomi_reindex NOT in _GATED_TASK_TYPES
E. doci_doc_generation_batch has display name in _KNOWN_TYPE_DISPLAY_NAMES
F. knomi_reindex has display name in _KNOWN_TYPE_DISPLAY_NAMES
G. doci display name contains "Doci"
H. knomi display name contains "Knomi"
I. Total _ALLOWED_TASK_TYPES count is 17 (15 prior + doci + knomi)
J. submit() for doci_doc_generation_batch returns correctly-prefixed task_id
K. submit() for knomi_reindex returns correctly-prefixed task_id
L. Doci task metadata has cpu_only = True (vram_sensitive = False)
M. Knomi task metadata has cpu_only = True (vram_sensitive = False)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scheduler.agent_scheduler_adapter import AgentSchedulerAdapter
from ops.scheduler.task_models import TaskMetadata


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_adapter() -> AgentSchedulerAdapter:
    adapter = AgentSchedulerAdapter.__new__(AgentSchedulerAdapter)
    adapter._redis_url = "redis://localhost:6379"
    adapter._redis = AsyncMock()
    queue = MagicMock()
    queue.set_task_metadata = AsyncMock()
    queue.schedule_task = AsyncMock()
    adapter._queue = queue
    return adapter


async def _capture_submit(adapter: AgentSchedulerAdapter, **kwargs) -> tuple[str, TaskMetadata]:
    task_id = await adapter.submit(**kwargs)
    call_args = adapter._queue.set_task_metadata.call_args
    captured_meta: TaskMetadata = call_args[0][1]
    return task_id, captured_meta


# ── Group 1 — Allowlist presence (A–D) ───────────────────────────────────────

class TestAllowlistPresence:
    def setup_method(self):
        import sys as _sys
        _sys.modules.setdefault("argus_code_agent", MagicMock())
        from ops.argus.argus_orchestrator import _ALLOWED_TASK_TYPES, _GATED_TASK_TYPES
        self.allowed = _ALLOWED_TASK_TYPES
        self.gated = _GATED_TASK_TYPES

    def test_A_doci_batch_in_allowed(self):
        assert "doci_doc_generation_batch" in self.allowed

    def test_B_knomi_reindex_in_allowed(self):
        assert "knomi_reindex" in self.allowed

    def test_C_doci_batch_not_gated(self):
        assert "doci_doc_generation_batch" not in self.gated

    def test_D_knomi_reindex_not_gated(self):
        assert "knomi_reindex" not in self.gated


# ── Group 2 — Display names (E–H) ────────────────────────────────────────────

class TestDisplayNames:
    def setup_method(self):
        from ops.scheduler.task_scheduler import _KNOWN_TYPE_DISPLAY_NAMES
        self.names = _KNOWN_TYPE_DISPLAY_NAMES

    def test_E_doci_batch_has_display_name(self):
        assert "doci_doc_generation_batch" in self.names

    def test_F_knomi_reindex_has_display_name(self):
        assert "knomi_reindex" in self.names

    def test_G_doci_display_name_mentions_doci(self):
        assert "Doci" in self.names["doci_doc_generation_batch"]

    def test_H_knomi_display_name_mentions_knomi(self):
        assert "Knomi" in self.names["knomi_reindex"]


# ── Group 3 — Registry count (I) ─────────────────────────────────────────────

class TestRegistryCount:
    def setup_method(self):
        import sys as _sys
        _sys.modules.setdefault("argus_code_agent", MagicMock())
        from ops.argus.argus_orchestrator import _ALLOWED_TASK_TYPES
        self.allowed = _ALLOWED_TASK_TYPES

    def test_I_allowed_task_types_total_17(self):
        assert len(self.allowed) == 17, (
            f"Expected 17 allowed task types, got {len(self.allowed)}: {sorted(self.allowed)}"
        )


# ── Group 4 — Adapter submit (J–M) ───────────────────────────────────────────

class TestAdapterSubmit:
    @pytest.mark.asyncio
    async def test_J_doci_submit_returns_prefixed_task_id(self):
        adapter = _make_adapter()
        task_id, _ = await _capture_submit(
            adapter,
            task_type="doci_doc_generation_batch",
            created_by="doci",
            command=["python", "ops/agents/doci_agent.py", "--batch"],
        )
        assert task_id.startswith("doci_doc_generation_batch_")

    @pytest.mark.asyncio
    async def test_K_knomi_submit_returns_prefixed_task_id(self):
        adapter = _make_adapter()
        task_id, _ = await _capture_submit(
            adapter,
            task_type="knomi_reindex",
            created_by="knomi",
            command=["python", "ops/agents/knomi_agent.py", "--reindex"],
        )
        assert task_id.startswith("knomi_reindex_")

    @pytest.mark.asyncio
    async def test_L_doci_metadata_cpu_only(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="doci_doc_generation_batch",
            created_by="doci",
            command=["python", "ops/agents/doci_agent.py", "--batch"],
        )
        assert meta.vram_sensitive is False

    @pytest.mark.asyncio
    async def test_M_knomi_metadata_cpu_only(self):
        adapter = _make_adapter()
        _, meta = await _capture_submit(
            adapter,
            task_type="knomi_reindex",
            created_by="knomi",
            command=["python", "ops/agents/knomi_agent.py", "--reindex"],
        )
        assert meta.vram_sensitive is False
