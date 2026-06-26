from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def copy_optional_file(source: str | Path | None, destination: str | Path) -> str | None:
    if not source:
        return None
    src = Path(source)
    if not src.exists():
        return None
    dst = Path(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def read_text_file(path: str | Path | None) -> str:
    if not path:
        return ""
    target = Path(path)
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8", errors="replace")


def build_wrapper_metadata(
    *,
    agent_name: str,
    target_slot: str,
    task_prompt: str,
    command: list[str],
    started_at_utc: str,
    finished_at_utc: str | None = None,
    exit_code: int | None = None,
    session_log_path: str | None = None,
    start_status_path: str | None = None,
    end_status_path: str | None = None,
    diff_path: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "learning_capture_wrapper_v1",
        "agent_name": agent_name,
        "target_slot": target_slot,
        "task_prompt": task_prompt,
        "command": list(command),
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "exit_code": exit_code,
        "session_log_path": session_log_path,
        "start_status_path": start_status_path,
        "end_status_path": end_status_path,
        "diff_path": diff_path,
    }


def write_json(path: str | Path, data: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(target)
