"""Evidence-only reconciliation for stale incomplete session packages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .stale_session_reaper import classify_stale_session


def reconcile_stale_packages(session_dirs: list[Path], live_pids: set[int] | None = None) -> dict[str, Any]:
    results = []
    for session_dir in session_dirs:
        row = classify_stale_session(session_dir, live_pids or set())
        if row["decision"] == "HOLD_STALE_NO_LIVE_PID":
            row["resulting_disposition"] = "STALE_INCOMPLETE_EVIDENCE_PRESERVED"
            row["terminal_status_fabricated"] = False
            row["manual_review_required"] = True
        elif row["decision"] == "ACTIVE_DO_NOT_TOUCH":
            row["resulting_disposition"] = "STALE_REQUIRES_MANUAL_REVIEW"
            row["manual_review_required"] = True
        else:
            row["resulting_disposition"] = row["decision"]
            row["manual_review_required"] = False
        results.append(row)
    return {"session_count": len(results), "results": results, "mutation_performed": False, "deletion_performed": False}
