#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


ALLOWED_SOURCE_TYPES = {"REAL", "TEST_FIXTURE", "MOCK"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    st = str(out.get("source_type") or "REAL").upper()
    if st not in ALLOWED_SOURCE_TYPES:
        st = "REAL"
    out["source_type"] = st
    return out


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(_normalize_entry(item))
    return rows


def _save_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _quarantine_mock_rejected_case(rows: list[dict[str, Any]], out_dir: Path) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in rows:
        rid = str(row.get("rejection_id") or row.get("case_id") or "")
        if rid == "mock_rejected_case_001":
            removed.append(row)
            continue
        kept.append(row)
    if removed:
        qpath = out_dir / "quarantined_mock_rejections.json"
        existing = _load_json(qpath, [])
        if not isinstance(existing, list):
            existing = []
        existing.extend(removed)
        _write_json(qpath, existing)
    return kept, len(removed)


def analyze(out_dir: Path, include_test_fixtures: bool) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / "rejection_ledger.jsonl"
    ledger = _load_ledger(ledger_path)
    cleaned, quarantined_n = _quarantine_mock_rejected_case(ledger, out_dir)
    if quarantined_n:
        _save_ledger(ledger_path, cleaned)
    ledger = cleaned

    real_rows = [r for r in ledger if r.get("source_type") == "REAL"]
    fixture_rows = [r for r in ledger if r.get("source_type") in {"MOCK", "TEST_FIXTURE"}]

    included = list(ledger if include_test_fixtures else real_rows)
    summary = {
        "generated_at": _now(),
        "include_test_fixtures": include_test_fixtures,
        "real_rejections": len(real_rows),
        "mock_rejections_ignored": len(fixture_rows) + quarantined_n if not include_test_fixtures else 0,
        "test_fixture_rejections": len(fixture_rows),
        "total_included": len(included),
        "quarantined_mock_rejected_case_001": quarantined_n,
    }
    _write_json(out_dir / "rejection_summary.json", summary)
    _write_json(out_dir / "rejection_included.json", included)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="aims_workspace/hermes/rejection_tracking")
    ap.add_argument("--include-test-fixtures", action="store_true")
    args = ap.parse_args()

    summary = analyze(Path(args.out), include_test_fixtures=args.include_test_fixtures)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

