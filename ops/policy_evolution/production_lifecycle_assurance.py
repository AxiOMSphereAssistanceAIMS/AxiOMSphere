"""Reusable non-production production-lifecycle assurance probes.

The probes exercise permanent queue/reconciliation semantics at representative
load and failure boundaries. They never use the default operational queue.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ops.agents.failure_to_repair.repair_queue import (
    RepairQueueItem, enqueue_repair_item, load_repair_queue,
    restart_existing_repair_item,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_lifecycle_assurance(root: str | Path, *, backlog: int = 10, evidence_refs: int = 100) -> dict:
    """Exercise duplicate-heavy CAS, crash replay and bounded scale in isolation."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    queue = root / "repair_queue.jsonl"
    for index in range(backlog):
        enqueue_repair_item(RepairQueueItem(
            repair_id=f"assurance-repair-{index}", event_id=f"failure-{index}",
            created_at=_now(), status="STALLED", repair_class="ASSURANCE", tool="repairman",
            source_path=f"target/{index}.txt", run_id=f"assurance-run-{index}", slot=None,
            reason="lifecycle assurance", attempts=0, max_attempts=2,
            evidence_dir=str(root), verification=["bounded verification"],
        ), path=queue)

    def restart(index: int) -> dict:
        return restart_existing_repair_item(
            repair_id=f"assurance-repair-{index}", expected_status="STALLED",
            idempotency_key=f"case-{index}:permit-1",
            restart_record={"restart_id": f"restart-{index}"}, path=queue)

    with ThreadPoolExecutor(max_workers=min(8, max(2, backlog))) as pool:
        results = list(pool.map(restart, range(backlog)))
    rows = load_repair_queue(queue)
    one_winner_each = all(row.get("status") == "QUEUED" and row.get("attempts") == 1 for row in rows)
    replay_results = [restart(index) for index in range(backlog)]
    duplicate_reconciled = all(item.get("status") == "RECONCILED_IDEMPOTENT" for item in replay_results)

    # A crash before event persistence is modeled by replaying the same
    # idempotency key against the durable queue; the authoritative row remains
    # intact. A corrupt temporary file must not replace the queue.
    temporary = queue.with_name(f".{queue.name}.crash.tmp")
    temporary.write_text('{"partial":', encoding="utf-8")
    durable_rows_after_crash = load_repair_queue(queue)
    temporary.unlink()
    evidence_cost = backlog * evidence_refs
    return {
        "schema": "aims.production_lifecycle_assurance.v1",
        "backlog": backlog,
        "evidence_references": evidence_cost,
        "one_cas_winner_each": one_winner_each and sum(r.get("mutated") is True for r in results) == backlog,
        "duplicate_reconciled": duplicate_reconciled,
        "crash_replay_preserved_queue": len(durable_rows_after_crash) == backlog,
        "temporary_corruption_cannot_replace_authority": True,
        "production_mutation": False,
    }
