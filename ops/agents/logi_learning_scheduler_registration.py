"""Register Logi learning/cleanup ticks with the existing scheduler stack.

Recurring cadence is provided by the existing aims-scheduler crontab. Each cron
tick submits a one-shot task to the existing Redis scheduler via
AgentSchedulerAdapter, so the Redis scheduler remains the execution layer.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION_ROOT = ROOT / "aims_workspace" / "logi_session_learning" / "scheduler"
REGISTRY_PATH = REGISTRATION_ROOT / "registered_learning_ticks.json"
REPORT_PATH = ROOT / "aims_workspace" / "logi_session_learning" / "progress" / "scheduler_registration_report.md"
DEFAULT_CRONTAB_PATH = ROOT / "ops" / "scheduler" / "crontab"
CRON_BEGIN = "# BEGIN LOGI LEARNING REDIS SCHEDULER TICKS"
CRON_END = "# END LOGI LEARNING REDIS SCHEDULER TICKS"


@dataclass(frozen=True)
class LearningSchedulerJob:
    job_id: str
    enabled: bool
    command: str
    argv: list[str]
    working_directory: str
    cadence: str
    cron_expression: str
    max_runtime_seconds: int
    overlap_policy: str
    retry_policy: dict[str, int]
    purpose: str


def default_jobs(root: Path = ROOT) -> list[LearningSchedulerJob]:
    workdir = str(root)
    return [
        LearningSchedulerJob(
            job_id="logi_continuous_session_learning_tick",
            enabled=True,
            command=(
                "python3 ops/scripts/import_codex_legacy_sessions_for_logi.py && "
                "python3 ops/scripts/logi_continuous_session_learning.py scheduler-tick --max-items 10"
            ),
            argv=[
                "sh",
                "-lc",
                "python3 ops/scripts/import_codex_legacy_sessions_for_logi.py && "
                "python3 ops/scripts/logi_continuous_session_learning.py scheduler-tick --max-items 10",
            ],
            working_directory=workdir,
            cadence="every_10_minutes",
            cron_expression="*/10 * * * *",
            max_runtime_seconds=300,
            overlap_policy="skip_if_running",
            retry_policy={"max_attempts": 2, "backoff_seconds": 60},
            purpose=(
                "Import old Codex session tails, then discover/process pending session "
                "summaries/raw logs and convert them into learning artifacts."
            ),
        ),
        LearningSchedulerJob(
            job_id="logi_session_learning_cleanup_tick",
            enabled=True,
            command="python3 ops/scripts/logi_continuous_session_learning.py cleanup-scheduler-tick --max-items 20",
            argv=["python3", "ops/scripts/logi_continuous_session_learning.py", "cleanup-scheduler-tick", "--max-items", "20"],
            working_directory=workdir,
            cadence="every_30_minutes",
            cron_expression="*/30 * * * *",
            max_runtime_seconds=300,
            overlap_policy="skip_if_running",
            retry_policy={"max_attempts": 2, "backoff_seconds": 60},
            purpose=(
                "Build/process cleanup pending items after LEARNING_CYCLE_CLOSED, "
                "respecting cleanup policy."
            ),
        ),
        LearningSchedulerJob(
            job_id="logi_raw_verified_consumption_cleanup_tick",
            enabled=True,
            command="python3 ops/scripts/logi_raw_lifecycle.py auto-delete-verified --dry-run",
            argv=["python3", "ops/scripts/logi_raw_lifecycle.py", "auto-delete-verified", "--dry-run"],
            working_directory=workdir,
            cadence="every_30_minutes",
            cron_expression="*/30 * * * *",
            max_runtime_seconds=300,
            overlap_policy="skip_if_running",
            retry_policy={"max_attempts": 2, "backoff_seconds": 60},
            purpose=(
                "Dry-run verified-consumption raw cleanup. Execute mode is intentionally "
                "not scheduled until backfill reports and lifecycle dry-run are reviewed."
            ),
        ),
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_path() -> Path:
    return Path(os.environ.get("LOGI_LEARNING_SCHEDULER_REGISTRY_PATH", REGISTRY_PATH))


def _report_path() -> Path:
    return Path(os.environ.get("LOGI_LEARNING_SCHEDULER_REPORT_PATH", REPORT_PATH))


def _crontab_path() -> Path:
    return Path(os.environ.get("LOGI_LEARNING_SCHEDULER_CRONTAB_PATH", DEFAULT_CRONTAB_PATH))


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _jobs_payload(jobs: list[LearningSchedulerJob]) -> list[dict]:
    return [asdict(job) for job in jobs]


def _load_registered_jobs() -> list[dict]:
    data = _read_json(_registry_path())
    return list(data.get("jobs") or [])


def _job_diff(existing: dict | None, desired: dict) -> bool:
    if not existing:
        return True
    comparable = [
        "enabled",
        "command",
        "working_directory",
        "cadence",
        "cron_expression",
        "max_runtime_seconds",
        "overlap_policy",
        "retry_policy",
    ]
    return any(existing.get(k) != desired.get(k) for k in comparable)


def _merge_jobs(existing: list[dict], desired: list[dict], enabled: bool | None = None) -> tuple[list[dict], list[str], bool]:
    by_id = {item.get("job_id"): dict(item) for item in existing if item.get("job_id")}
    changed = False
    updated: list[str] = []
    for job in desired:
        merged = dict(job)
        if enabled is not None:
            merged["enabled"] = enabled
        current = by_id.get(job["job_id"])
        if _job_diff(current, merged):
            changed = True
            updated.append(job["job_id"])
        by_id[job["job_id"]] = {**(current or {}), **merged, "updated_at": _now()}
    ordered = [by_id[job["job_id"]] for job in desired]
    return ordered, updated, changed


def _cron_line(job: dict) -> str:
    repo = job["working_directory"]
    return (
        f"{job['cron_expression']} cd {repo} && "
        f"TASK_SCHEDULER_REDIS_URL=${{TASK_SCHEDULER_REDIS_URL:-${{AIMS_REDIS_URL:-redis://localhost:6379}}}} "
        f"PYTHONPATH={repo}:{repo}/ops "
        f"python3 ops/scripts/register_logi_learning_scheduler_ticks.py "
        f"--enqueue-job {job['job_id']} >> /var/log/scheduler.log 2>&1"
    )


def _render_cron_block(jobs: list[dict]) -> str:
    lines = [CRON_BEGIN]
    for job in jobs:
        prefix = "" if job.get("enabled", True) else "# disabled: "
        lines.append(prefix + _cron_line(job))
    lines.append(CRON_END)
    return "\n".join(lines)


def _replace_marker_block(text: str, block: str) -> tuple[str, bool]:
    if CRON_BEGIN in text and CRON_END in text:
        before, rest = text.split(CRON_BEGIN, 1)
        _, after = rest.split(CRON_END, 1)
        new_text = before.rstrip() + "\n\n" + block + after
    else:
        new_text = text.rstrip() + "\n\n" + block + "\n"
    return new_text, new_text != text


def write_scheduler_report(status: dict) -> str:
    path = _report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs = status.get("jobs") or []
    lines = [
        "# Logi Learning Scheduler Registration",
        "",
        "## Status",
        f"- status: {status.get('status')}",
        f"- changed: {status.get('changed')}",
        "",
        "## Existing Scheduler Inventory",
        "- Reused ops/scheduler/crontab as the existing recurring trigger surface.",
        "- Reused ops.scheduler.agent_scheduler_adapter.AgentSchedulerAdapter for Redis task submission.",
        "- Reused ops/scripts/logi_continuous_session_learning.py for learning and cleanup work.",
        "",
        "## Jobs Registered",
    ]
    for job in jobs:
        lines.extend([
            f"- job_id: {job.get('job_id')}",
            f"  cadence: {job.get('cadence')}",
            f"  enabled: {job.get('enabled')}",
            f"  command: {job.get('command')}",
        ])
    lines.extend([
        "",
        "## Idempotency",
        "Registration updates jobs by job_id and rewrites one marked crontab block; duplicate jobs are not appended.",
        "",
        "## Commands",
        "- python3 ops/scripts/register_logi_learning_scheduler_ticks.py --status",
        "- python3 ops/scripts/register_logi_learning_scheduler_ticks.py --register",
        "- python3 ops/scripts/register_logi_learning_scheduler_ticks.py --verify",
        "",
        "## Cadence",
        "- learning: every 10 minutes",
        "- cleanup: every 30 minutes",
        "",
        "## Verification",
        f"- commands_valid: {status.get('commands_valid')}",
        f"- jobs_present: {status.get('jobs_present')}",
        "",
        "## Known Gaps",
        "- Live Redis enqueue requires the existing Redis scheduler to be reachable at runtime.",
        "",
        "## Next Actions",
        "- Run --register on the deployment host, then restart/reload the existing aims-scheduler crontab if required.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def validate_jobs(jobs: list[dict]) -> tuple[bool, list[str]]:
    expected = {job.job_id: asdict(job) for job in default_jobs()}
    errors: list[str] = []
    by_id = {job.get("job_id"): job for job in jobs}
    for job_id, desired in expected.items():
        found = by_id.get(job_id)
        if not found:
            errors.append(f"missing job: {job_id}")
            continue
        if found.get("command") != desired["command"]:
            errors.append(f"command mismatch: {job_id}")
        if found.get("working_directory") != desired["working_directory"]:
            errors.append(f"working_directory mismatch: {job_id}")
        if found.get("overlap_policy") != "skip_if_running":
            errors.append(f"overlap_policy mismatch: {job_id}")
    return not errors, errors


def _scheduler_execution_command(job: dict) -> list[str]:
    """Return a scheduler-daemon-safe command.

    The Redis scheduler daemon may run in a compose container whose cwd is not
    the repo root. Keep the human-readable job command stable, but enqueue a
    shell wrapper that chooses the mounted repo path before running it.
    """
    repo = job.get("working_directory") or str(ROOT)
    command = job.get("command") or " ".join(job.get("argv") or [])
    return [
        "sh",
        "-lc",
        (
            f"if [ -d /workspace/ops ]; then cd /workspace; "
            f"elif [ -d {repo}/ops ]; then cd {repo}; "
            "elif [ -d /ops/scripts ]; then cd /; "
            f"else cd {repo}; fi; {command}"
        ),
    ]


async def _redis_available() -> tuple[bool, str]:
    redis_url = (
        os.environ.get("TASK_SCHEDULER_REDIS_URL")
        or os.environ.get("AIMS_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://localhost:6379"
    )
    try:
        import redis.asyncio as aioredis
        client = await aioredis.from_url(redis_url, decode_responses=True)
        try:
            pong = await client.ping()
            return bool(pong), redis_url
        finally:
            await client.close()
    except Exception as exc:
        return False, f"{redis_url} ({type(exc).__name__}: {exc})"


def registration_status() -> dict:
    jobs = _load_registered_jobs()
    valid, errors = validate_jobs(jobs)
    crontab = _crontab_path()
    crontab_text = crontab.read_text(encoding="utf-8") if crontab.exists() else ""
    marker_present = CRON_BEGIN in crontab_text and CRON_END in crontab_text
    status = "PASSED" if valid and marker_present else "NEEDS_REGISTRATION"
    redis_ok, redis_detail = asyncio.run(_redis_available())
    payload = {
        "status": status,
        "mode": "SCHEDULER_LEARNING_TICKS_STATUS",
        "jobs": jobs or _jobs_payload(default_jobs()),
        "jobs_present": len(jobs),
        "commands_valid": valid,
        "validation_errors": errors,
        "scheduler": {
            "available": True,
            "adapter": "ops.scheduler.agent_scheduler_adapter.AgentSchedulerAdapter",
            "queue": "scheduler:tasks:pending",
            "redis_connected": redis_ok,
            "redis": redis_detail,
            "crontab_path": str(crontab),
            "crontab_marker_present": marker_present,
        },
        "report_path": str(_report_path()),
    }
    payload["report_path"] = write_scheduler_report(payload)
    return payload


def register_jobs(*, dry_run: bool = False, enabled: bool | None = None) -> dict:
    desired = _jobs_payload(default_jobs())
    existing = _load_registered_jobs()
    merged, updated, changed_registry = _merge_jobs(existing, desired, enabled=enabled)
    block = _render_cron_block(merged)
    crontab = _crontab_path()
    old_text = crontab.read_text(encoding="utf-8") if crontab.exists() else ""
    new_text, changed_cron = _replace_marker_block(old_text, block)
    changed = changed_registry or changed_cron
    if not dry_run:
        _write_json(_registry_path(), {"updated_at": _now(), "jobs": merged})
        crontab.parent.mkdir(parents=True, exist_ok=True)
        crontab.write_text(new_text, encoding="utf-8")
    payload = {
        "status": "PASSED",
        "mode": "SCHEDULER_LEARNING_TICKS_REGISTER",
        "changed": changed,
        "would_register": len(merged) if dry_run else 0,
        "registered_or_updated": updated,
        "duplicates_created": 0,
        "jobs": merged,
        "crontab_path": str(crontab),
        "registry_path": str(_registry_path()),
        "dry_run": dry_run,
        "commands_valid": validate_jobs(merged)[0],
        "jobs_present": len(merged),
    }
    payload["report_path"] = write_scheduler_report(payload)
    return payload


def set_jobs_enabled(enabled: bool, dry_run: bool = False) -> dict:
    result = register_jobs(dry_run=dry_run, enabled=enabled)
    result["mode"] = "SCHEDULER_LEARNING_TICKS_ENABLE" if enabled else "SCHEDULER_LEARNING_TICKS_DISABLE"
    return result


def verify_jobs() -> dict:
    status = registration_status()
    valid, errors = validate_jobs(status.get("jobs") or [])
    crontab_ok = bool(status.get("scheduler", {}).get("crontab_marker_present"))
    passed = valid and crontab_ok
    status.update({
        "status": "PASSED" if passed else "FAILED",
        "mode": "SCHEDULER_LEARNING_TICKS_VERIFY",
        "jobs_present": len(_load_registered_jobs()),
        "commands_valid": valid,
        "verification_errors": errors + ([] if crontab_ok else ["crontab marker block missing"]),
    })
    status["report_path"] = write_scheduler_report(status)
    return status


async def enqueue_job_async(job_id: str) -> dict:
    jobs = _load_registered_jobs() or _jobs_payload(default_jobs())
    job = next((j for j in jobs if j.get("job_id") == job_id), None)
    if not job:
        return {"status": "FAILED", "error_class": "UNKNOWN_JOB", "job_id": job_id}
    if not job.get("enabled", True):
        return {"status": "SKIPPED", "reason": "job disabled", "job_id": job_id}
    try:
        from ops.scheduler.agent_scheduler_adapter import AgentSchedulerAdapter
        async with AgentSchedulerAdapter() as adapter:
            task_id = await adapter.submit(
                task_type=job_id,
                command=_scheduler_execution_command(job),
                created_by="logi_learning_scheduler_registration",
                priority=45,
                resource_key=job_id,
                display_name=job_id,
                description=job.get("purpose", "")[:1000],
                is_retryable=True,
                max_retries=int((job.get("retry_policy") or {}).get("max_attempts", 2)),
            )
        return {
            "status": "PASSED",
            "mode": "SCHEDULER_LEARNING_TICKS_ENQUEUE",
            "job_id": job_id,
            "scheduler_task_id": task_id,
            "queue": "scheduler:tasks:pending",
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "mode": "SCHEDULER_LEARNING_TICKS_ENQUEUE",
            "job_id": job_id,
            "error_class": "SCHEDULER_ENQUEUE_FAILED",
            "detail": f"{type(exc).__name__}: {exc}",
        }


def enqueue_job(job_id: str) -> dict:
    return asyncio.run(enqueue_job_async(job_id))


def format_status_for_terminal(payload: dict) -> str:
    lines = [
        f"STATUS: {payload.get('status')}",
        f"MODE: {payload.get('mode')}",
    ]
    if "changed" in payload:
        lines.append(f"CHANGED: {str(payload.get('changed')).lower()}")
    if "would_register" in payload:
        lines.append(f"WOULD_REGISTER: {payload.get('would_register')}")
    if "duplicates_created" in payload:
        lines.append(f"DUPLICATES_CREATED: {payload.get('duplicates_created')}")
    if "jobs_present" in payload:
        lines.append(f"JOBS_PRESENT: {payload.get('jobs_present')}")
    if "commands_valid" in payload:
        lines.append(f"COMMANDS_VALID: {str(payload.get('commands_valid')).lower()}")
    lines.append("JOBS:")
    for job in payload.get("jobs") or []:
        lines.extend([
            f"- job_id: {job.get('job_id')}",
            f"  enabled: {job.get('enabled')}",
            f"  cadence: {job.get('cadence')}",
            f"  command: {job.get('command')}",
        ])
    scheduler = payload.get("scheduler") or {}
    if scheduler:
        lines.extend([
            "SCHEDULER:",
            f"  available: {scheduler.get('available')}",
            f"  adapter: {scheduler.get('adapter')}",
            f"  queue: {scheduler.get('queue')}",
            f"  redis_connected: {scheduler.get('redis_connected')}",
        ])
    if payload.get("registered_or_updated"):
        lines.append("REGISTERED_OR_UPDATED:")
        lines.extend(f"- {item}" for item in payload["registered_or_updated"])
    if payload.get("verification_errors"):
        lines.append("VERIFICATION_ERRORS:")
        lines.extend(f"- {item}" for item in payload["verification_errors"])
    if payload.get("report_path"):
        lines.append(f"REPORT_PATH: {payload.get('report_path')}")
    return "\n".join(lines)


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register Logi learning ticks with the existing scheduler")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--register", action="store_true")
    group.add_argument("--disable", action="store_true")
    group.add_argument("--enable", action="store_true")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--enqueue-job")
    args = parser.parse_args(argv)

    if args.status:
        payload = registration_status()
    elif args.dry_run:
        payload = register_jobs(dry_run=True)
    elif args.register:
        payload = register_jobs(dry_run=False)
    elif args.disable:
        payload = set_jobs_enabled(False)
    elif args.enable:
        payload = set_jobs_enabled(True)
    elif args.verify:
        payload = verify_jobs()
    else:
        payload = enqueue_job(args.enqueue_job)

    print(format_status_for_terminal(payload))
    return 0 if payload.get("status") in {"PASSED", "NEEDS_REGISTRATION", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(cli_main())
