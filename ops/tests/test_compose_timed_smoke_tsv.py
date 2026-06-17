"""
Parse TSV produced by ops/scripts/compose_timed_smoke_test.sh.

Run after a smoke pass:
  SMOKE_TSV=logs/container_timed_YYYYMMDD_HHMMSS.tsv pytest ops/tests/test_compose_timed_smoke_tsv.py -q

Without SMOKE_TSV, tests are skipped.
"""

from __future__ import annotations

import csv
import os
import unittest
from pathlib import Path

try:
    import pytest
    _pytest_available = True
except ImportError:
    pytest = None  # type: ignore[assignment]
    _pytest_available = False

TSV_PATH = os.environ.get("SMOKE_TSV", "").strip()

if _pytest_available and pytest is not None:
    pytestmark = pytest.mark.skipif(not TSV_PATH, reason="set env SMOKE_TSV=/path/to/container_timed_*.tsv")


def _rows():
    path = Path(TSV_PATH)
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _skip_if_no_pytest_or_tsv():
    if not _pytest_available:
        raise unittest.SkipTest("pytest not installed")
    if not TSV_PATH:
        raise unittest.SkipTest("set env SMOKE_TSV=/path/to/container_timed_*.tsv")


def test_tsv_has_expected_columns():
    _skip_if_no_pytest_or_tsv()
    rows = _rows()
    assert rows, f"empty or missing TSV: {TSV_PATH}"
    for key in ("service", "container", "up_sec", "wait_state_ok", "probe_ok"):
        assert key in rows[0], f"missing column {key!r}"


def test_compose_up_succeeded_for_all_services():
    """Every row should have compose exit column empty or not 'compose up failed' in notes."""
    _skip_if_no_pytest_or_tsv()
    rows = _rows()
    for r in rows:
        notes = (r.get("notes") or "").lower()
        assert "compose up failed" not in notes, r


def test_core_http_services_probed():
    """Strict check: Qdrant + Omi API must be running and answer HTTP (stable contract)."""
    _skip_if_no_pytest_or_tsv()
    rows = _rows()
    required = {"axiomsphere-qdrant", "axiomsphere-omi-api"}
    by_c = {r.get("container"): r for r in rows}
    for c in required:
        assert c in by_c, f"missing row for {c}"
        r = by_c[c]
        assert r.get("wait_state_ok") == "1", r
        assert r.get("probe_ok") == "1", r
