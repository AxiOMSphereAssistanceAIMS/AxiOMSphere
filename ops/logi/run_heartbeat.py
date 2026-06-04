"""Logi — Heartbeat writer for monitored runs.

Writes a heartbeat JSON file for an existing monitored run so the watchdog
does not classify it as STALE or HUNG.

Usage:
    python3 ops/logi/run_heartbeat.py --run-id <monitored_run_id> [--extra key=value ...]

The script locates the run JSON from the default watchdog directory and updates
the heartbeat file in place.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_DIR = ROOT / "aims_workspace" / "model_improvement_loop" / "watchdog"


def _load_run(run_id: str) -> dict:
    path = WATCHDOG_DIR / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Run file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_heartbeat(run: dict, extra: dict) -> Path:
    now = datetime.now(timezone.utc).isoformat()
    hb_path = ROOT / run["heartbeat_file"]
    hb_path.parent.mkdir(parents=True, exist_ok=True)
    hb = {
        "monitored_run_id": run["monitored_run_id"],
        "action_id": run["action_id"],
        "status": run["status"],
        "last_heartbeat_at": now,
        "slot_id": run["slot_id"],
    }
    hb.update(extra)
    hb_path.write_text(json.dumps(hb, indent=2, ensure_ascii=False), encoding="utf-8")
    # Update the run JSON
    run["last_heartbeat_at"] = now
    run["status"] = "HEARTBEAT_OK"
    run_path = WATCHDOG_DIR / f"{run['monitored_run_id']}.json"
    run_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    return hb_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a watchdog heartbeat for a monitored run")
    parser.add_argument("--run-id", required=True, help="monitored_run_id")
    parser.add_argument("--extra", nargs="*", default=[], metavar="KEY=VALUE",
                        help="Additional key=value fields to embed in the heartbeat")
    args = parser.parse_args()

    extra: dict = {}
    for kv in args.extra:
        if "=" in kv:
            k, v = kv.split("=", 1)
            extra[k] = v
        else:
            extra[kv] = True

    run = _load_run(args.run_id)
    hb_path = _write_heartbeat(run, extra)
    print(f"[heartbeat] written → {hb_path}")
    print(f"[heartbeat] run_id={args.run_id} status=HEARTBEAT_OK at={run['last_heartbeat_at']}")


if __name__ == "__main__":
    main()
