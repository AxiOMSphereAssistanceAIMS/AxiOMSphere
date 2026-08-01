"""Fail-closed stale session classifier; never fabricates terminal state."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_stale_session(session_dir: Path, live_pids: set[int]) -> dict[str, Any]:
    manifest_path = session_dir / "session_manifest.json"
    final_path = session_dir / "final_status.json"
    transcript_path = session_dir / "transcript.md"
    manifest_hash = _sha256(manifest_path)
    transcript_hash = _sha256(transcript_path)
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {"session_id": session_dir.name, "decision": "QUARANTINED_MALFORMED", "mutation_performed": False}
    pid = manifest.get("pid_child") or manifest.get("pid")
    pid_live = isinstance(pid, int) and pid in live_pids
    if final_path.exists():
        decision = "TERMINAL_EVIDENCE_PRESENT"
    elif pid_live:
        decision = "ACTIVE_DO_NOT_TOUCH"
    else:
        decision = "HOLD_STALE_NO_LIVE_PID"
    return {
        "session_id": session_dir.name,
        "manifest_path": str(manifest_path),
        "final_status_path": str(final_path),
        "manifest_status": manifest.get("status"),
        "pid": pid,
        "pid_live": pid_live,
        "manifest_sha256": manifest_hash,
        "transcript_sha256": transcript_hash,
        "decision": decision,
        "mutation_performed": False,
        "terminal_time_fabricated": False,
        "deletion_performed": False,
    }


def scan_sessions(session_dirs: list[Path], live_pids: set[int] | None = None) -> dict[str, Any]:
    live_pids = live_pids or set()
    rows = [classify_stale_session(path, live_pids) for path in session_dirs]
    return {"sessions_scanned": len(rows), "rows": rows, "mutation_performed": False, "deletion_performed": False}
