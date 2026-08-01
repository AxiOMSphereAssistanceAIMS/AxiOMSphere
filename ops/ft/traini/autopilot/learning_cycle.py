"""Bounded evidence-only LearningUnit extraction/routing cycle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .engineering_contract_learning_unit_extractor import extract_engineering_units
from .job_filter_repair_unit_extractor import extract_job_filter_repair_unit
from .learning_unit_route_classifier import classify_unit
from .learning_unit_store import LearningUnitStore
from .route_store import persist_route_decisions


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def run_learning_cycle(records: Iterable[Any], evidence_root: Path, *, cycle_id: str) -> dict[str, Any]:
    """Process each source exactly once per `(source_id, source_hash)`.

    This cycle is intentionally downstream of operational source closeout and
    upstream of model-pair admission. It never creates training tasks.
    """
    evidence_root.mkdir(parents=True, exist_ok=True)
    source_ledger = evidence_root / "learning_value_assessment_ledger.jsonl"
    prior = {(r.get("source_id"), r.get("source_hash")) for r in _read_jsonl(source_ledger)}
    unit_store = LearningUnitStore(evidence_root / "learning_unit_store.jsonl", evidence_root / "learning_unit_hold_store.jsonl")
    unit_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    closeouts: list[dict[str, Any]] = []
    processed = 0
    skipped = 0
    for record in records:
        source_id = str(getattr(record, "record_id", ""))
        source_hash = str(getattr(record, "checksum", ""))
        if (source_id, source_hash) in prior:
            skipped += 1
            continue
        processed += 1
        units = extract_engineering_units(record)
        if not units:
            fallback = extract_job_filter_repair_unit(record)
            if fallback is not None:
                units = [fallback]
        source_row = {"source_id": source_id, "source_hash": source_hash, "cycle_id": cycle_id, "units_found": len(units)}
        with source_ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(source_row, sort_keys=True) + "\n")
        if not units:
            closeouts.append({**source_row, "disposition": "NO_DURABLE_UNIT", "reason": "no bounded engineering-contract learning unit"})
            continue
        for unit in units:
            stored = unit_store.append(unit)
            unit_rows.append({"unit": unit.to_dict(), "store_disposition": stored.get("disposition")})
            route = classify_unit(unit)
            route_rows.append(route)
    route_result = persist_route_decisions(evidence_root / "route_stores", route_rows, cycle_id=cycle_id)
    with (evidence_root / "no_durable_unit_closeouts.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row, sort_keys=True) + "\n" for row in closeouts))
    metrics = {
        "cycle_id": cycle_id,
        "records_discovered": processed,
        "records_skipped_unchanged": skipped,
        "learning_units_observed": len(unit_rows),
        "no_durable_unit_closeouts": len(closeouts),
        "route_counts": route_result["counts"],
        "training_task_created": False,
        "training_started": False,
        "registry_mutated": False,
    }
    (evidence_root / f"cycle_{cycle_id}_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics
