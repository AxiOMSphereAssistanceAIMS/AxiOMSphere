#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.ft.traini.autopilot.raw_material_pair_preparation import (  # noqa: E402
    DEFAULT_CURSOR_PATH,
    discover_codex_session_handoffs,
    prepare_pairs_from_raw_material,
    write_pair_preparation_manifests,
)
from ops.ft.traini.autopilot.raw_material_pair_preparation_gate import run_raw_material_pair_preparation_gate  # noqa: E402
from ops.ft.traini.autopilot.quarantine_retention_cleanup import cleanup as cleanup_quarantine  # noqa: E402


def default_out_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "aims_workspace" / "agent_architecture_status" / f"traini_raw_material_review_5h_{stamp}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight Traini raw material review every 5 hours.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-manifests", action="store_true")
    parser.add_argument("--since-last-cursor", action="store_true")
    parser.add_argument("--raw-zone", action="append", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--max-records", type=int, default=500)
    parser.add_argument("--drain-until-empty", action="store_true", default=True,
                        help="Continue batches in one invocation until no unprocessed raw records remain.")
    parser.add_argument("--cleanup-quarantine", action="store_true", default=True,
                        help="Apply the 7-day quarantine retention policy after extraction batches.")
    args = parser.parse_args()

    out_dir = args.out_dir or default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    codex_session_handoff = discover_codex_session_handoffs(
        output_path=out_dir / "codex_session_handoff_records.jsonl",
        max_items=args.max_records,
    )
    batches = []
    cursor_mode = args.since_last_cursor
    while True:
        batch_index = len(batches) + 1
        batch_out = out_dir if batch_index == 1 else out_dir / f"batch_{batch_index:04d}"
        result = prepare_pairs_from_raw_material(
            args.raw_zone,
            since_last_cursor=cursor_mode,
            max_records=args.max_records,
        )
        paths: dict[str, str] = {}
        if args.write_manifests or args.dry_run:
            paths = write_pair_preparation_manifests(
                result,
                batch_out,
                cursor_path=DEFAULT_CURSOR_PATH,
                write_cursor=args.write_manifests and not args.dry_run,
            )
        gate = {"status": "SKIPPED"}
        if paths:
            gate = run_raw_material_pair_preparation_gate(
                Path(paths["accepted_candidates"]),
                Path(paths["rejected_candidates"]),
                Path(paths["agent_skill_learning_candidates"]),
                check_redis=False,
            )
            (batch_out / "raw_material_pair_preparation_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        batches.append({"batch_index": batch_index, "result": result.manifest(), "paths": paths, "gate": gate})
        if args.dry_run or not args.drain_until_empty or result.records_seen < args.max_records:
            break
        cursor_mode = True

    quarantine_cleanup = cleanup_quarantine(None, now=datetime.now(timezone.utc), apply=False) if args.dry_run else cleanup_quarantine(None, now=datetime.now(timezone.utc), apply=args.cleanup_quarantine, out=out_dir / "quarantine_retention_cleanup.json")
    response = {
        "stage": "traini_raw_material_review_5h",
        "status": "PASS" if gate.get("status") in {"PASS", "SKIPPED"} else "FAIL",
        "dry_run": args.dry_run,
        "write_manifests": args.write_manifests,
        "since_last_cursor": args.since_last_cursor,
        "cursor_path": str(DEFAULT_CURSOR_PATH),
        "result": batches[-1]["result"],
        "paths": batches[-1]["paths"],
        "gate": batches[-1]["gate"],
        "batches": batches,
        "drain_until_empty": args.drain_until_empty,
        "total_records_seen": sum(int(batch["result"].get("records_seen") or 0) for batch in batches),
        "quarantine_cleanup": quarantine_cleanup,
        "codex_session_handoff": codex_session_handoff,
        "safety": {
            "training_started": False,
            "merge_started": False,
            "gguf_started": False,
            "promotion_executed": False,
            "redis_tuning_task_created": False,
            "slot120_unblocked": False,
        },
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
