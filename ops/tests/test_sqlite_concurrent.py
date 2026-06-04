"""
Tests for SQLite concurrent access safety via safe_connect().

Verifies WAL mode, busy_timeout, and that 4 concurrent writer threads
can all commit without raising OperationalError (SQLITE_BUSY).
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from sqlite_helpers import safe_connect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tmp_db() -> Path:
    """Return a Path to a fresh temporary SQLite database."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_connection_has_wal_mode() -> None:
    """safe_connect() must enable WAL journal mode."""
    db_path = _make_tmp_db()
    try:
        conn = safe_connect(db_path)
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row is not None, "PRAGMA journal_mode returned no rows"
            assert row[0].upper() == "WAL", (
                f"Expected WAL journal mode, got: {row[0]!r}"
            )
        finally:
            conn.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_connection_has_busy_timeout() -> None:
    """safe_connect() must set busy_timeout >= 5000 ms."""
    db_path = _make_tmp_db()
    try:
        conn = safe_connect(db_path)
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row is not None, "PRAGMA busy_timeout returned no rows"
            timeout_ms = int(row[0])
            assert timeout_ms >= 5000, (
                f"Expected busy_timeout >= 5000 ms, got: {timeout_ms}"
            )
        finally:
            conn.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_concurrent_writers_dont_crash() -> None:
    """4 threads writing concurrently via safe_connect() must not raise errors."""
    db_path = _make_tmp_db()
    errors: list[Exception] = []

    # Create the table before spawning threads.
    setup_conn = safe_connect(db_path)
    setup_conn.execute(
        "CREATE TABLE IF NOT EXISTS writes (thread_id INTEGER, value TEXT)"
    )
    setup_conn.commit()
    setup_conn.close()

    def worker(thread_id: int) -> None:
        try:
            conn = safe_connect(db_path)
            for i in range(10):
                conn.execute(
                    "INSERT INTO writes (thread_id, value) VALUES (?, ?)",
                    (thread_id, f"row-{i}"),
                )
            conn.commit()
            conn.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, (
        f"Concurrent writers raised {len(errors)} error(s): {errors}"
    )

    # Verify all 40 rows were written (4 threads × 10 rows).
    verify_conn = safe_connect(db_path)
    count = verify_conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0]
    verify_conn.close()
    db_path.unlink(missing_ok=True)
    assert count == 40, f"Expected 40 rows, got {count}"
