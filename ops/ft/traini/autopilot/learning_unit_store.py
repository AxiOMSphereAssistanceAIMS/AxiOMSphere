"""Append-only LearningUnit and hold stores."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ops.ft.traini.autopilot.learning_unit import LearningUnit, validate_learning_unit


class LearningUnitStore:
    def __init__(self, path: Path, hold_path: Path | None = None) -> None:
        self.path = path
        self.hold_path = hold_path or path.with_name("learning_unit_hold_store.jsonl")

    def append(self, unit: LearningUnit, *, disposition: str = "CREATED", reason: str | None = None) -> dict[str, Any]:
        # Append-only and idempotent: a repeated observation of the same
        # immutable unit is recorded as a suppressed duplicate, never a
        # second learning row.
        for existing_path in (self.path, self.hold_path):
            if existing_path.exists():
                for line in existing_path.read_text(encoding="utf-8").splitlines():
                    try:
                        existing = json.loads(line).get("learning_unit", {})
                    except json.JSONDecodeError:
                        continue
                    if existing.get("learning_unit_id") == unit.learning_unit_id:
                        return {"learning_unit": unit.to_dict(), "disposition": "DUPLICATE_SUPPRESSED", "validation_errors": [], "reason": "immutable id already persisted"}
        errors = validate_learning_unit(unit)
        row = {"learning_unit": unit.to_dict(), "disposition": disposition, "validation_errors": errors, "reason": reason}
        target = self.path if not errors and disposition == "CREATED" else self.hold_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row
