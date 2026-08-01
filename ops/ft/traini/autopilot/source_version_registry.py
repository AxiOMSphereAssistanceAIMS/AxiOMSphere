"""Durable source version and closeout registry for Traini raw material."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(content: str | bytes) -> str:
    value = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def observe_source(
    registry_path: Path,
    *,
    logical_source_id: str,
    source_type: str,
    producer: str,
    source_hash: str,
    cycle_id: str,
    closeout_status: str = "OPEN",
    recheck_condition: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Observe a source idempotently and return its current version record."""
    observed_at = observed_at or _now()
    rows = _read(registry_path)
    history = [row for row in rows if row.get("logical_source_id") == logical_source_id]
    version_history = [row for row in history if row.get("event") == "VERSION_CREATED"]
    if history and history[-1].get("content_hash") == source_hash:
        current = dict(history[-1])
        current.update({"last_seen_at": observed_at, "last_pipeline_cycle": cycle_id})
        _append(registry_path, {**current, "event": "UNCHANGED_OBSERVED"})
        return {**current, "version_created": False, "changed": False}
    version = len(version_history) + 1
    previous = version_history[-1].get("content_hash") if version_history else None
    record = {
        "logical_source_id": logical_source_id,
        "source_version": f"v{version}",
        "content_hash": source_hash,
        "previous_content_hash": previous,
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
        "changed_at": observed_at if previous else None,
        "closeout_status": closeout_status,
        "closeout_at": observed_at if closeout_status in {"CLOSED", "REJECTED", "QUARANTINED"} else None,
        "last_pipeline_cycle": cycle_id,
        "recheck_condition": recheck_condition,
        "source_type": source_type,
        "producer": producer,
        "event": "VERSION_CREATED",
    }
    _append(registry_path, record)
    return {**record, "version_created": True, "changed": previous is not None}


def persist_closeout(closeout_path: Path, version_record: dict[str, Any], *, status: str, reason: str | None = None) -> dict[str, Any]:
    if status not in {"CLOSED", "REJECTED", "QUARANTINED", "CONDITIONAL_HOLD", "RECHECK_ON_CHANGE", "RECHECK_ON_SCHEDULE"}:
        raise ValueError(f"invalid closeout status: {status}")
    row = {
        "logical_source_id": version_record["logical_source_id"],
        "source_version": version_record["source_version"],
        "content_hash": version_record["content_hash"],
        "closeout_status": status,
        "closeout_at": _now(),
        "reason": reason,
        "last_pipeline_cycle": version_record.get("last_pipeline_cycle"),
        "recheck_condition": version_record.get("recheck_condition"),
    }
    _append(closeout_path, row)
    return row
