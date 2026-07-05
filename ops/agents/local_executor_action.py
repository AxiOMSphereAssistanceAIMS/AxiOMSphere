"""
local_executor_action.py

Narrow allowlisted action type: run_local_executor_task

The ONLY execution path allowed from Telegram Logi route.

Rules:
  - Only executes: python3 ops/scripts/aims_local_executor.py <task_json>
  - task_json must be inside aims_workspace/test_tasks/
  - Rejects: path traversal (..), absolute paths, shell metacharacters
  - Captures real stdout/stderr/exit_code — never returns expected_output as evidence
  - Returns structured result with FILE_CREATED, CONTENT_VERIFIED, SHA256
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_TASK_DIR = _ROOT / "aims_workspace" / "test_tasks"
_EXECUTOR = _ROOT / "ops" / "scripts" / "aims_local_executor.py"
_EXECUTOR_TIMEOUT = 60

_BLOCKED_PATH_RE = re.compile(r"\.\.|[;&|`$><!\*\?{}\[\]\\]")


@dataclass
class LocalExecutorActionResult:
    status: str                  # PASSED | FAILED | BLOCKED_BY_FINAL_POLICY_GATE
    execution_route: str
    task_json: str
    stdout: str
    stderr: str
    exit_code: int
    executor_result: dict
    file_created: bool
    content_verified: bool
    sha256: str | None
    error_class: str | None


def _validate_task_path(task_json: str) -> tuple[bool, str]:
    """
    Validate task_json path: must be inside aims_workspace/test_tasks/,
    no traversal, no metacharacters.
    """
    if not task_json:
        return False, "empty task_json path"

    if _BLOCKED_PATH_RE.search(task_json):
        return False, f"path contains blocked characters: {task_json!r}"

    # Normalize: if relative, resolve from _ROOT
    p = Path(task_json)
    if not p.is_absolute():
        p = _ROOT / p

    try:
        resolved = p.resolve()
    except Exception as exc:
        return False, f"path resolution error: {exc}"

    try:
        resolved.relative_to(_TASK_DIR.resolve())
    except ValueError:
        return False, f"path escapes allowed task dir {_TASK_DIR}: {resolved}"

    if not resolved.exists():
        return False, f"task file not found: {resolved}"

    if resolved.suffix != ".json":
        return False, f"task file must be .json: {resolved}"

    return True, str(resolved)


def _first_failed_action_error_class(executor_result: dict) -> str | None:
    """Extract error_class from the first FAILED action in executor result."""
    for action in executor_result.get("actions_executed", []):
        if action.get("status") == "FAILED" and action.get("error_class"):
            return action["error_class"]
    return None


def run_local_executor_task(task_json: str) -> LocalExecutorActionResult:
    """
    Execute python3 ops/scripts/aims_local_executor.py <task_json>.

    Returns structured result. Never fabricates output.
    """
    # Path validation
    ok, detail = _validate_task_path(task_json)
    if not ok:
        return LocalExecutorActionResult(
            status="FAILED",
            execution_route="logi_telegram_local_executor",
            task_json=task_json,
            stdout="", stderr=detail, exit_code=1,
            executor_result={},
            file_created=False,
            content_verified=False,
            sha256=None,
            error_class="INVALID_TASK_PATH",
        )

    resolved_path = detail  # _validate_task_path returns resolved path on success

    if not _EXECUTOR.exists():
        return LocalExecutorActionResult(
            status="FAILED",
            execution_route="logi_telegram_local_executor",
            task_json=task_json,
            stdout="", stderr="executor script not found", exit_code=1,
            executor_result={},
            file_created=False,
            content_verified=False,
            sha256=None,
            error_class="EXECUTOR_NOT_FOUND",
        )

    # Execute
    try:
        proc = subprocess.run(
            ["python3", str(_EXECUTOR), resolved_path],
            capture_output=True,
            text=True,
            timeout=_EXECUTOR_TIMEOUT,
            cwd=str(_ROOT),
        )
    except subprocess.TimeoutExpired:
        return LocalExecutorActionResult(
            status="FAILED",
            execution_route="logi_telegram_local_executor",
            task_json=task_json,
            stdout="", stderr=f"executor timed out after {_EXECUTOR_TIMEOUT}s",
            exit_code=124,
            executor_result={},
            file_created=False,
            content_verified=False,
            sha256=None,
            error_class="EXECUTOR_TIMEOUT",
        )

    raw_stdout = proc.stdout or ""
    raw_stderr = proc.stderr or ""

    # Parse executor JSON result
    executor_result: dict = {}
    try:
        executor_result = json.loads(raw_stdout)
    except (json.JSONDecodeError, ValueError):
        pass

    executor_status = executor_result.get("status", "FAILED")
    verification = executor_result.get("verification", {})

    file_created = verification.get("file_exists", {}).get("result") == "PASSED"
    content_verified = verification.get("content_equals", {}).get("result") == "PASSED"

    # Extract SHA256 from actions
    sha256: str | None = None
    for action in executor_result.get("actions_executed", []):
        if action.get("action_type") == "sha256_file" and action.get("status") == "PASSED":
            sha256 = action.get("stdout", "").strip()
            break

    overall = "PASSED" if proc.returncode == 0 and executor_status == "PASSED" else "FAILED"

    # Propagate specific error_class from executor result when available
    if overall == "PASSED":
        specific_error_class = None
    else:
        specific_error_class = (
            executor_result.get("error_class")
            or _first_failed_action_error_class(executor_result)
            or "EXECUTOR_FAILED"
        )

    return LocalExecutorActionResult(
        status=overall,
        execution_route="logi_telegram_local_executor",
        task_json=task_json,
        stdout=raw_stdout,
        stderr=raw_stderr,
        exit_code=proc.returncode,
        executor_result=executor_result,
        file_created=file_created,
        content_verified=content_verified,
        sha256=sha256,
        error_class=specific_error_class,
    )


def format_telegram_executor_result(result: LocalExecutorActionResult) -> str:
    """Format LocalExecutorActionResult as a Telegram-safe response string."""
    if result.status == "BLOCKED_BY_FINAL_POLICY_GATE":
        return (
            "STATUS: BLOCKED_BY_FINAL_POLICY_GATE\n"
            "ERROR_CLASS: EXECUTOR_ROUTE_POLICY_BLOCKED"
        )

    lines = [f"STATUS: {result.status}"]
    lines.append(f"EXECUTION_ROUTE: {result.execution_route}")
    lines.append(f"FILE_CREATED: {'true' if result.file_created else 'false'}")
    lines.append(f"CONTENT_VERIFIED: {'true' if result.content_verified else 'false'}")
    if result.sha256:
        lines.append(f"SHA256: {result.sha256}")
    if result.error_class:
        lines.append(f"ERROR_CLASS: {result.error_class}")
    if result.stderr and result.status == "FAILED":
        lines.append(f"STDERR: {result.stderr[:200]}")
    return "\n".join(lines)
