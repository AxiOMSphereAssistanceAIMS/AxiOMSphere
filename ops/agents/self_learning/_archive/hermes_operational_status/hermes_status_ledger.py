from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_event(out_dir: Path, event: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "hermes_activity_ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def tail_events(out_dir: Path, n: int = 20) -> list[dict[str, Any]]:
    ledger = out_dir / "hermes_activity_ledger.jsonl"
    if not ledger.exists():
        return []
    lines = ledger.read_text(encoding="utf-8").splitlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
