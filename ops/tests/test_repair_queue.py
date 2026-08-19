from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from ops.agents.failure_to_repair.repair_queue import (RepairQueueItem, enqueue_repair_item, load_repair_queue,
                                                       restart_existing_repair_item)


def _item(**kwargs) -> RepairQueueItem:
    base = dict(
        repair_id="repair_1",
        event_id="event_1",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="QUEUED",
        repair_class="STORAGE_ORPHAN_ARTIFACT_CLEANUP",
        tool="repairman",
        source_path="/tmp/result.json",
        run_id="run_1",
        slot="slot32",
        reason="unsafe_orphan_artifacts_present",
        attempts=0,
        max_attempts=3,
        evidence_dir="/tmp/evidence",
        verification=["storage_prep_recheck"],
    )
    base.update(kwargs)
    return RepairQueueItem(**base)


def test_repair_queue_deduplicates_same_run_reason(tmp_path: Path) -> None:
    queue_path = tmp_path / "repair_queue.jsonl"
    item = _item()
    first, inserted_first = enqueue_repair_item(item, path=queue_path)
    second, inserted_second = enqueue_repair_item(_item(repair_id="repair_2"), path=queue_path)

    assert inserted_first is True
    assert inserted_second is False
    assert first.repair_id == "repair_1"
    assert second.repair_id == "repair_2"
    assert len(load_repair_queue(queue_path)) == 1


def test_failed_item_allows_new_entry(tmp_path: Path) -> None:
    queue_path = tmp_path / "repair_queue.jsonl"
    queue_path.write_text(
        "\n".join(
            [
                '{"repair_id":"repair_a","event_id":"event_1","created_at":"2026-07-09T00:00:00+00:00","status":"FAILED","repair_class":"STORAGE_ORPHAN_ARTIFACT_CLEANUP","tool":"repairman","source_path":"/tmp/result.json","run_id":"run_1","slot":"slot32","reason":"unsafe_orphan_artifacts_present","attempts":1,"max_attempts":3,"evidence_dir":"/tmp/evidence","verification":[]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _, inserted = enqueue_repair_item(_item(repair_id="repair_2"), path=queue_path)
    assert inserted is True
    assert len(load_repair_queue(queue_path)) == 2


def test_restart_cas_has_one_winner_under_concurrency(tmp_path: Path) -> None:
    queue_path = tmp_path / "repair_queue.jsonl"
    stalled = _item(status="STALLED", attempts=0, max_attempts=2)
    enqueue_repair_item(stalled, path=queue_path)

    def restart():
        return restart_existing_repair_item(
            repair_id="repair_1", expected_status="STALLED", idempotency_key="case:permit",
            restart_record={"restart_id": "r1"}, path=queue_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: restart(), range(2)))
    assert sorted(result["status"] for result in results) == ["RECONCILED_IDEMPOTENT", "RESTARTED_EXISTING_LINEAGE"]
    rows = load_repair_queue(queue_path)
    assert rows[0]["attempts"] == 1
    assert rows[0]["status"] == "QUEUED"
