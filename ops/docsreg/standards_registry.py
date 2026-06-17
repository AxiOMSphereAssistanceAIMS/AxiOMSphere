from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("docsreg_standards_registry")

ROOT = Path(__file__).resolve().parents[2]


def _candidate_db_paths() -> tuple[Path, ...]:
    env_path = os.environ.get("AIMS_STANDARDS_DB_PATH", "").strip()
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend(
        [
            ROOT / "data" / "aims_registry.db",
            ROOT / "aims_workspace" / "aims_registry.db",
            Path("/data/aims_registry.db"),
        ]
    )
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            ordered.append(path)
    return tuple(ordered)


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    for candidate in _candidate_db_paths():
        if candidate.exists():
            return candidate
    return _candidate_db_paths()[0]


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS standards_index (
            standard_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'registered',
            official_url TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            registered_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (standard_id, domain, source)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_standards_index_domain ON standards_index(domain)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_standards_index_standard_id ON standards_index(standard_id)"
    )
    conn.commit()


def register_standard(
    standard_id: str,
    *,
    domain: str,
    source: str,
    title: str = "",
    status: str = "registered",
    official_url: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO standards_index (
                standard_id, domain, title, source, status,
                official_url, notes, metadata_json,
                registered_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(standard_id, domain, source) DO UPDATE SET
                title=excluded.title,
                status=excluded.status,
                official_url=excluded.official_url,
                notes=excluded.notes,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                standard_id,
                domain,
                title,
                source,
                status,
                official_url,
                notes,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        conn.commit()


def register_standards(
    standards: Iterable[str],
    *,
    domain: str,
    source: str,
    metadata_by_standard: dict[str, dict[str, Any]] | None = None,
    db_path: str | Path | None = None,
    status: str = "registered",
) -> None:
    metadata_by_standard = metadata_by_standard or {}
    for standard_id in standards:
        meta = metadata_by_standard.get(standard_id, {})
        register_standard(
            standard_id,
            domain=domain,
            source=source,
            title=str(meta.get("title", "")),
            status=str(meta.get("status", status)),
            official_url=str(meta.get("official_url", "")),
            notes=str(meta.get("notes", "")),
            metadata=meta,
            db_path=db_path,
        )


def list_registered_standards(
    *,
    domain: str | None = None,
    db_path: str | Path | None = None,
) -> list[str]:
    try:
        with _connect(db_path) as conn:
            if domain:
                rows = conn.execute(
                    "SELECT DISTINCT standard_id FROM standards_index WHERE domain LIKE ? ORDER BY standard_id",
                    (domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT standard_id FROM standards_index ORDER BY standard_id"
                ).fetchall()
        return [str(row["standard_id"]) for row in rows]
    except Exception:
        log.exception("list_registered_standards failed")
        return []


def list_registered_standard_records(
    *,
    domain: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    try:
        with _connect(db_path) as conn:
            if domain:
                rows = conn.execute(
                    """
                    SELECT standard_id, domain, title, source, status,
                           official_url, notes, metadata_json,
                           registered_at, updated_at
                    FROM standards_index
                    WHERE domain LIKE ?
                    ORDER BY standard_id
                    """,
                    (domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT standard_id, domain, title, source, status,
                           official_url, notes, metadata_json,
                           registered_at, updated_at
                    FROM standards_index
                    ORDER BY domain, standard_id
                    """
                ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            try:
                payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
            except Exception:
                payload["metadata"] = {}
                payload.pop("metadata_json", None)
            records.append(payload)
        return records
    except Exception:
        log.exception("list_registered_standard_records failed")
        return []

