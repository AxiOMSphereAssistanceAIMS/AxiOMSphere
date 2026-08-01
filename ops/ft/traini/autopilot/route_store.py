"""Isolated append-only stores for routed learning units."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROUTE_FILES = {
    "MODEL_TRAINING_SLOT14": "slot14_learning_units.jsonl",
    "MODEL_TRAINING_SLOT32": "slot32_learning_units.jsonl",
    "MODEL_TRAINING_SLOT120": "slot120_learning_units.jsonl",
    "AGENT_SKILL_LEARNING": "agent_skill_learning_units.jsonl",
    "EVALUATION_CASE": "evaluation_units.jsonl",
    "OPERATIONAL_MEMORY_ONLY": "operational_memory_units.jsonl",
    "AUDIT_EVIDENCE_ONLY": "audit_evidence_units.jsonl",
    "QUALITY_OPTIMIZATION_BACKLOG": "quality_optimization_backlog.jsonl",
    "HOLD": "route_holds.jsonl",
}


def persist_route_decisions(root: Path, decisions: list[dict[str, Any]], *, cycle_id: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    existing_ids: set[str] = set()
    for existing_path in root.glob("*.jsonl"):
        for line in existing_path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if value.get("learning_unit_id"):
                existing_ids.add(str(value["learning_unit_id"]))
    for decision in decisions:
        if str(decision.get("learning_unit_id") or "") in existing_ids:
            continue
        route = str(decision.get("route") or "HOLD")
        path = root / ROUTE_FILES.get(route, "route_holds.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {**decision, "schema_version": "learning-unit-route-v1", "cycle_id": cycle_id, "append_only": True}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        counts[route] = counts.get(route, 0) + 1
        existing_ids.add(str(decision.get("learning_unit_id")))
    manifest = {"schema_version": "learning-unit-route-v1", "cycle_id": cycle_id, "stores": {}}
    for name in sorted(set(ROUTE_FILES.values())):
        path = root / name
        if not path.exists():
            continue
        payload = path.read_bytes()
        rows = [line for line in payload.splitlines() if line.strip()]
        ids = [json.loads(line).get("learning_unit_id") for line in rows]
        manifest["stores"][name] = {"path": str(path), "record_count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "unique_ids": len(set(ids)), "duplicate_count": len(ids)-len(set(ids))}
    (root / "route_store_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"counts": counts, "manifest": manifest}
