#!/usr/bin/env python3
"""Fail-closed reaper for Codex captures with no terminal status.

Only sessions older than the configured limit are considered. This tool never
sends process signals: a verified live wrapper blocks closure, while a capture
is closed as orphaned only when its manifest PID has no exactly owned process.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _age_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds()
    except ValueError:
        return 0.0


def _owned_process(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Return verified ownership evidence for the manifest PID, never a substring match."""
    try:
        pid = int(manifest.get("pid_launcher") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 1:
        return None
    proc = Path("/proc") / str(pid)
    try:
        cmd_tokens = [token.decode(errors="replace") for token in (proc / "cmdline").read_bytes().split(b"\0") if token]
        stat = (proc / "stat").read_text(encoding="utf-8").split()
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        process_started_epoch = datetime.now(timezone.utc).timestamp() - uptime + (int(stat[21]) / clock_ticks)
        manifest_started = datetime.fromisoformat(str(manifest.get("started_at_utc") or manifest.get("started_at"))).timestamp()
    except (OSError, ValueError, IndexError):
        return None
    allowed_executables = {
        str(manifest.get("launcher_path") or ""),
        str(manifest.get("wrapper_path") or ""),
        str(manifest.get("codex_bin") or manifest.get("codex_binary") or ""),
    }
    token_paths = {str(Path(token).expanduser()) for token in cmd_tokens}
    executable_match = bool({value for value in allowed_executables if value}.intersection(token_paths))
    start_match = abs(process_started_epoch - manifest_started) <= 120
    if not executable_match or not start_match:
        return None
    return {
        "pid": pid,
        "cmd_tokens": cmd_tokens,
        "process_started_epoch": process_started_epoch,
        "manifest_started_epoch": manifest_started,
    }


def reap(root: Path, *, max_age_seconds: int, apply: bool) -> dict[str, Any]:
    raw = root / "aims_workspace/logi/raw_material/codex_sessions"
    results = []
    for session in sorted(p for p in raw.iterdir() if p.is_dir()) if raw.exists() else []:
        manifest_path = session / "session_manifest.json"
        manifest = _json(manifest_path)
        if str(manifest.get("status", "")).upper() != "RUNNING":
            continue
        age = _age_seconds(manifest.get("started_at_utc") or manifest.get("started_at"))
        if age < max_age_seconds:
            continue
        session_id = session.name
        owned = _owned_process(manifest)
        action = "DRY_RUN"
        if apply:
            if owned:
                results.append(
                    {
                        "session_id": session_id,
                        "age_seconds": round(age),
                        "matched_processes": 1,
                        "owned_pid": owned["pid"],
                        "action": "BLOCKED_VERIFIED_PROCESS_STILL_LIVE",
                    }
                )
                continue
            final = {
                "status": "FAILED",
                "exit_code": 124,
                "failure_class": "CAPTURE_WRAPPER",
                "reason": "stale Codex session exceeded max runtime and no verified owned process remained",
                "forced_termination": False,
                "matched_process_count": 0,
                "ended_at_utc": datetime.now(timezone.utc).isoformat(),
                "direct_training_allowed": False,
            }
            _write(session / "final_status.json", final)
            manifest["status"] = "FAILED"
            manifest["exit_code"] = 124
            manifest["reaper_disposition"] = "ORPHANED_CAPTURE_CLOSED"
            _write(manifest_path, manifest)
            action = "ORPHANED_CAPTURE_CLOSED"
        results.append({"session_id": session_id, "age_seconds": round(age), "matched_processes": 1 if owned else 0, "owned_pid": owned["pid"] if owned else None, "action": action})
    return {"status": "PASS", "apply": apply, "max_age_seconds": max_age_seconds, "sessions": results, "count": len(results)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--max-age-seconds", type=int, default=3600)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = reap(args.workspace.resolve(), max_age_seconds=args.max_age_seconds, apply=args.apply)
    _write(args.out, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
