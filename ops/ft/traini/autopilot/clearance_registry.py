"""Append-only versioned independent-clearance decision registry."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ClearanceRegistry:
    """Persist decisions separately from producer candidate records.

    A decision is immutable for a `(pair_id, candidate_hash)` tuple; a later
    candidate version gets a new row rather than overwriting history.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, decision: dict[str, Any]) -> dict[str, Any]:
        required = ("pair_id", "candidate_hash", "clearance_version", "decision", "reviewer_identity")
        missing = [key for key in required if not decision.get(key)]
        if missing:
            raise ValueError(f"missing clearance fields: {','.join(missing)}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for line in self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []:
            existing = json.loads(line)
            if (existing.get("pair_id"), existing.get("candidate_hash")) == (decision.get("pair_id"), decision.get("candidate_hash")):
                return {**existing, "duplicate_suppressed": True}
        row = {**decision, "registry_event": "CLEARANCE_RECORDED", "approved_for_training": decision.get("decision") == "ADMIT"}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row
