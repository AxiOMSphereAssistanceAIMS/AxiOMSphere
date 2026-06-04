"""
Общие настройки SQLite: WAL снижает блокировки при одновременном чтении (sync/Omi)
и записи (omi-register) на одном bind-mount файле БД.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def sqlite_connect_wal(path: str | Path, **kwargs: Any) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), **kwargs)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def safe_connect(db_path: str | Path, *, timeout: int = 30) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and busy_timeout for concurrent safety.

    WAL (Write-Ahead Logging) allows concurrent readers with one writer, preventing
    SQLITE_BUSY errors when 6+ services write to aims_registry.db simultaneously.

    Args:
        db_path: Path to the SQLite database file.
        timeout: sqlite3.connect() timeout in seconds (default 30).

    Returns:
        sqlite3.Connection configured for concurrent access.
    """
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
