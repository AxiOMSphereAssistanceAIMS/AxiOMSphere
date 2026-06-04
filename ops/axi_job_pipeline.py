"""
axi_job_pipeline.py
───────────────────
Job filter and cross-handoff pipeline utilities for the Axi bot.
Extracted from axi_bot.py (Phase C Task 2 refactor).

Note: The job pipeline in axi_bot.py consists primarily of Telegram job-queue
callbacks (_job_flush_pending_analyze, _job_axi_deliver_cross_handoffs,
_job_docfill_vram_monitor) that depend on bot state and the Application scheduler.
Those remain in axi_bot.py.

This module holds any pure (non-Telegram) job pipeline utilities that can be
called independently — currently a placeholder for future extraction.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("axi")

# ── Cross-handoff delivery helpers ─────────────────────────────────────────────

def _queue_to_omi_batch_inbox(
    file_path: "Path | str",
    *,
    chat_id: int | None = None,
    intent: str = "analyze",
    source: str = "axi_handoff",
) -> bool:
    """Queue a file to the Omi batch inbox directory.

    Returns True on success, False on failure.
    This is the sync counterpart to the async cross-handoff delivery.
    """
    try:
        import shutil
        inbox_dir = Path(os.environ.get("OMI_BATCH_INBOX", "/data/omi_batch/inbox"))
        inbox_dir.mkdir(parents=True, exist_ok=True)
        src = Path(file_path)
        if not src.exists():
            log.warning("_queue_to_omi_batch_inbox: source not found: %s", src)
            return False
        dst = inbox_dir / src.name
        shutil.copy2(str(src), str(dst))
        log.info("queued to omi inbox: %s (chat=%s intent=%s)", dst, chat_id, intent)
        return True
    except Exception as e:
        log.warning("_queue_to_omi_batch_inbox error: %s", e)
        return False
