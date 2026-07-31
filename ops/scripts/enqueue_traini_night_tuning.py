#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.scheduler.agent_scheduler_adapter import AgentSchedulerAdapter
from ops.runtime.workspace_contract import resolve_workspace_for_executor


TRAINI_WORKER_CONTAINER = os.getenv("AIMS_TRAINI_WORKER_CONTAINER", "axiomsphere-traini-worker")
NIGHT_WINDOW_TZ = ZoneInfo("Asia/Dubai")
NIGHT_WINDOW_START = time(0, 0)
NIGHT_WINDOW_END = time(8, 0)


def inside_night_window(now: datetime | None = None) -> bool:
    current = (now or datetime.now(timezone.utc)).astimezone(NIGHT_WINDOW_TZ)
    return NIGHT_WINDOW_START <= current.time() < NIGHT_WINDOW_END


def next_night_window_start(now: datetime | None = None) -> datetime:
    current = (now or datetime.now(timezone.utc)).astimezone(NIGHT_WINDOW_TZ)
    if inside_night_window(current):
        return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    target_date = current.date()
    if current.time() >= NIGHT_WINDOW_END:
        target_date = target_date + timedelta(days=1)
    target = datetime.combine(target_date, NIGHT_WINDOW_START, tzinfo=NIGHT_WINDOW_TZ)
    return target.astimezone(timezone.utc)


def _slot32_v4_metadata() -> dict[str, Any]:
    return {
        "candidate": "qwen3-32b-ft-coding-v4-candidate",
        "dataset": "slot32_v4_active_160_pair_dataset",
        "dataset_pair_count": 160,
        "active_profile": "slot32_v4",
        "profile_min_pairs_required": 160,
        "run_scope": "controlled_repair_validation",
        "broad_autonomous_min_pairs_required": 750,
        "readiness_source": "active_profile",
        "if_improves_but_does_not_beat_incumbent": "keep_160_controlled_scope_unless_operator_requests_expansion",
        "if_beats_incumbent": "auto_promote_after_gated_eval_with_rollback_snapshot",
        "promotion_allowed": True,
        "registry_update_allowed": True,
        "auto_promotion_allowed": True,
        "post_eval_rca_required_if_loses": True,
        "failed_scope_pair_recovery_enabled": True,
        "mode": "CONTROLLED_REPAIR_VALIDATION",
    }


def _slot_readiness_args(slot: str) -> str:
    if slot == "32":
        meta = _slot32_v4_metadata()
        return (
            " --run-mode CONTROLLED_REPAIR_VALIDATION"
            f" --active-profile {meta['active_profile']}"
            f" --dataset-pair-count {meta['dataset_pair_count']}"
            f" --profile-min-pairs-required {meta['profile_min_pairs_required']}"
            f" --broad-min-pairs-required {meta['broad_autonomous_min_pairs_required']}"
            " --allow-registry-write"
            " --post-eval-rca-if-loses"
        )
    if slot == "120":
        return (
            " --run-mode FULL_AUTONOMOUS_GENERAL_TUNING"
            " --active-profile slot120_broad"
            " --broad-min-pairs-required 750"
            " --no-auto-promotion"
        )
    return (
        " --run-mode FULL_AUTONOMOUS_GENERAL_TUNING"
        f" --active-profile slot{slot}_broad"
        " --broad-min-pairs-required 750"
        " --no-auto-promotion"
    )


def _build_traini_worker_command(slot: str, *, telegram: bool) -> tuple[list[str], dict[str, Any]]:
    resolution = resolve_workspace_for_executor("redis-scheduler")
    telegram_arg = " --telegram" if telegram else ""
    readiness_args = _slot_readiness_args(slot)
    worker_script = (
        "set -euo pipefail; "
        "cd /workspace; "
        "export AIMS_WORKSPACE=/workspace WORKSPACE=/workspace AIMS_WORKSPACE_DIR=/workspace; "
        "export PYTHONPATH=/workspace:/workspace/ops:${PYTHONPATH:-}; "
        f"NIGHT_QWEN32_AUTORUN=${{NIGHT_QWEN32_AUTORUN:-1}} bash ops/scripts/traini_worker_night_tuning_entrypoint.sh --slot {slot}{readiness_args}{telegram_arg}"
    )
    command = ["docker", "exec", TRAINI_WORKER_CONTAINER, "bash", "-lc", worker_script]
    return command, {
        "executor_runtime": "redis-scheduler",
        "workdir": resolution.selected_workdir,
        "pythonpath": resolution.pythonpath,
        "workdir_strategy": "runtime_resolver",
        "traini_worker_container": TRAINI_WORKER_CONTAINER,
    }


def build_task_payload(slot: str, *, telegram: bool = True) -> dict[str, Any]:
    slot = str(slot)
    command, command_meta = _build_traini_worker_command(slot, telegram=telegram)
    scheduled_for = next_night_window_start()
    task_type = f"traini_slot{slot}_night_tuning"
    registration_metadata = _slot32_v4_metadata() if slot == "32" else {}
    if slot == "32":
        task_type = "traini_slot32_v4_night_tuning"
    description = (
        "Traini-owned conditional night tuning. The task must pass pair gates, "
        "night-window gates, resource guards, eval and promotion gates inside Traini."
    )
    if registration_metadata:
        description = f"{description} registration_metadata={json.dumps(registration_metadata, sort_keys=True)}"
    return {
        "task_type": task_type,
        "command": command,
        "created_by": "traini_ready_for_tuning" if slot == "32" else "traini_cron",
        "scheduled_for": scheduled_for,
        "priority": 90 if slot in {"32", "120"} else 70,
        "vram_sensitive": True,
        "model_slot": f"slot{slot}",
        "resource_key": f"traini:slot{slot}:night_tuning",
        "executor_runtime": command_meta["executor_runtime"],
        "workdir": command_meta["workdir"],
        "pythonpath": command_meta["pythonpath"],
        "workdir_strategy": command_meta["workdir_strategy"],
        "traini_worker_container": command_meta["traini_worker_container"],
        "display_name": f"Traini: slot{slot} night tuning",
        "description": description,
        "is_retryable": False,
        "max_retries": 0,
        **registration_metadata,
        "registration_metadata": registration_metadata,
    }


async def _enqueue(slot: str, *, telegram: bool) -> dict[str, Any]:
    redis_url = (
        os.getenv("TASK_SCHEDULER_REDIS_URL")
        or os.getenv("AIMS_REDIS_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379"
    )
    payload = build_task_payload(slot, telegram=telegram)
    if str(slot) == "32":
        existing = await _find_existing_active_slot32_v4_task(redis_url)
        if existing is not None:
            return {
                "status": "EXISTING_ACTIVE_TASK_REUSED",
                "duplicate_task_created": False,
                "task_id": existing.get("task_id"),
                "slot": "slot32",
                "redis_url": redis_url,
                "existing_task": existing,
                "payload_not_submitted": {
                    **payload,
                    "scheduled_for": payload["scheduled_for"].isoformat(),
                },
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        parity = _run_slot32_runtime_parity_probe_before_submit()
        if parity.get("parity_status") != "PASS":
            return {
                "status": "RUNTIME_PARITY_PROBE_FAILED",
                "duplicate_task_created": False,
                "task_created": False,
                "slot": "slot32",
                "redis_url": redis_url,
                "parity_probe": parity,
                "payload_not_submitted": {
                    **payload,
                    "scheduled_for": payload["scheduled_for"].isoformat(),
                },
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
    submit_keys = {
        "task_type",
        "command",
        "created_by",
        "scheduled_for",
        "priority",
        "vram_sensitive",
        "model_slot",
        "resource_key",
        "executor_runtime",
        "workdir",
        "pythonpath",
        "workdir_strategy",
        "display_name",
        "description",
        "is_retryable",
        "max_retries",
        "timeout_seconds",
    }
    submit_payload = {key: value for key, value in payload.items() if key in submit_keys}
    async with AgentSchedulerAdapter(redis_url=redis_url) as adapter:
        task_id = await adapter.submit(**submit_payload)
    return {
        "status": "ENQUEUED",
        "task_id": task_id,
        "slot": f"slot{slot}",
        "redis_url": redis_url,
        "payload": {
            **payload,
            "scheduled_for": payload["scheduled_for"].isoformat(),
        },
        "inside_allowed_night_window": inside_night_window(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


async def _find_existing_active_slot32_v4_task(redis_url: str) -> dict[str, Any] | None:
    import redis.asyncio as aioredis

    client = await aioredis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
        async for key in client.scan_iter("scheduler:task:*"):
            task_type = await client.hget(key, "task_type")
            model_slot = await client.hget(key, "model_slot")
            status = await client.hget(key, "status")
            description = await client.hget(key, "description") or ""
            if (
                model_slot == "slot32"
                and status in {"PENDING", "RUNNING"}
                and (
                    task_type in {"traini_slot32_v4_night_tuning", "traini_slot32_v4_controlled_repair_validation"}
                    or "slot32_v4_active_160_pair_dataset" in description
                )
            ):
                return {
                    "redis_key": key,
                    "task_id": await client.hget(key, "task_id"),
                    "task_type": task_type,
                    "status": status,
                    "scheduled_for": await client.hget(key, "scheduled_for"),
                    "resource_key": await client.hget(key, "resource_key"),
                }
    finally:
        await client.close()
    return None


def _run_slot32_runtime_parity_probe_before_submit() -> dict[str, Any]:
    command = [
        "docker",
        "exec",
        TRAINI_WORKER_CONTAINER,
        "bash",
        "-lc",
        (
            "cd /workspace && "
            "bash ops/scripts/traini_worker_night_tuning_entrypoint.sh "
            "--parity-probe "
            "--slot 32 "
            "--run-mode CONTROLLED_REPAIR_VALIDATION "
            "--active-profile slot32_v4 "
            "--dataset-pair-count 160 "
            "--profile-min-pairs-required 160 "
            "--broad-min-pairs-required 750 "
            "--allow-registry-write "
            "--post-eval-rca-if-loses"
        ),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    try:
        readiness = json.loads(completed.stdout)
    except Exception:
        readiness = None
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "readiness": readiness,
        "training_disabled_for_probe": True,
        "old_strict_manifest_selected": bool(
            readiness
            and readiness.get("old_stationary_manifest_used") is True
            or '"materialization_manifest"' in completed.stdout
        ),
        "parity_status": (
            "PASS"
            if completed.returncode == 0
            and readiness
            and readiness.get("training_allowed") is True
            and readiness.get("run_mode") == "CONTROLLED_REPAIR_VALIDATION"
            and readiness.get("profile") == "slot32_v4"
            and readiness.get("source_of_truth") == "active_profile"
            and readiness.get("old_stationary_manifest_used") is False
            else "FAIL"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enqueue Traini night tuning into Redis Scheduler.")
    parser.add_argument("--slot", default="32", choices=["14", "32", "120"])
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--proof", action="store_true", help="Build and validate payload without mutating Redis.")
    parser.add_argument("--dry-run", action="store_true", help="Alias for --proof.")
    parser.add_argument("--out")
    args = parser.parse_args()

    if args.proof or args.dry_run:
        payload = build_task_payload(args.slot, telegram=not args.no_telegram)
        command_text = " ".join(payload["command"])
        result = {
            "status": "PROOF",
            "mutated_redis": False,
            "task_type": payload["task_type"],
            "model_slot": payload["model_slot"],
            "resource_key": payload["resource_key"],
            "expected_candidate": payload.get("candidate"),
            "resolved_redis_execution_workdir": payload["workdir"],
            "executor_runtime": payload["executor_runtime"],
            "workdir_strategy": payload["workdir_strategy"],
            "command_contains_bad_host_only_cd": (
                "cd /home/axi_omi_sphere/aims-workspace &&" in command_text
                or "PYTHONPATH=/home/axi_omi_sphere/aims-workspace" in command_text
            ),
            "command_has_workdir_fallback": "WORKDIR_NOT_FOUND" in command_text,
            "payload": {
                **payload,
                "scheduled_for": payload["scheduled_for"].isoformat(),
            },
            "inside_allowed_night_window": inside_night_window(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        rc = 0
    else:
        try:
            result = asyncio.run(_enqueue(args.slot, telegram=not args.no_telegram))
        except Exception as exc:
            result = {
                "status": "SCHEDULER_UNAVAILABLE",
                "slot": f"slot{args.slot}",
                "error": str(exc),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "next_action": "start_or_fix Redis Scheduler; do not bypass with direct training launch",
            }
            rc = 2
        else:
            rc = 0

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
