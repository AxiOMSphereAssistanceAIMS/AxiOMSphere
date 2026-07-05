#!/usr/bin/env python3
"""
aims_local_executor.py

Minimal controlled executor for AIMS local tasks.

Usage:
    python3 ops/scripts/aims_local_executor.py <task_file.json>

Accepts a JSON task file, executes only safe controlled actions,
verifies expected outputs, and returns a JSON result.

Never silently passes. Never returns command text as success.
Every action produces real filesystem evidence or an explicit FAILED status.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


# ─── Allowlist ───────────────────────────────────────────────────────────────

_ALLOWED_COMMANDS = {
    "echo", "cat", "ls", "sha256sum", "test",
    "mkdir", "cp", "sed", "grep",
}

_BLOCKED_PATTERNS = [
    re.compile(r"\brm\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bcurl\b"),
    re.compile(r"\bwget\b"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bchown\b"),
    re.compile(r"\bdd\b\s+(if|of)="),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bsystemctl\b"),
    re.compile(r"\bdocker\b"),
    re.compile(r"\baws\b"),
    re.compile(r"\bcodex\s+login\b"),
    re.compile(r"\bclaude\s+login\b"),
]

_DEFAULT_TIMEOUT = 30  # seconds


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class ActionResult:
    action_type: str
    status: str           # PASSED | FAILED | SKIPPED
    detail: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


@dataclass
class ExecutorResult:
    status: str                              # PASSED | FAILED
    task_id: str
    actions_executed: list[dict] = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    error_class: str | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


# ─── Validation ──────────────────────────────────────────────────────────────

def _check_command_allowed(cmd: list[str] | str) -> tuple[bool, str]:
    """Return (allowed, reason). Checks allowlist and blocked patterns."""
    if isinstance(cmd, list):
        if not cmd:
            return False, "empty command"
        base = Path(cmd[0]).name
        cmd_str = " ".join(str(c) for c in cmd)
    else:
        cmd_str = str(cmd)
        base = Path(cmd_str.split()[0]).name if cmd_str.strip() else ""

    if base not in _ALLOWED_COMMANDS:
        return False, f"command '{base}' not in allowlist: {sorted(_ALLOWED_COMMANDS)}"

    for pat in _BLOCKED_PATTERNS:
        if pat.search(cmd_str):
            return False, f"blocked pattern matched: {pat.pattern!r}"

    return True, ""


# ─── Action handlers ─────────────────────────────────────────────────────────

def _do_write_file(action: dict) -> ActionResult:
    path = action.get("path", "")
    content = action.get("content", "")
    if not path:
        return ActionResult("write_file", "FAILED", "missing 'path'")
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ActionResult("write_file", "PASSED", f"wrote {len(content)} bytes to {path}")
    except Exception as exc:
        return ActionResult("write_file", "FAILED", f"write error: {exc}")


def _do_read_file(action: dict) -> ActionResult:
    path = action.get("path", "")
    if not path:
        return ActionResult("read_file", "FAILED", "missing 'path'")
    try:
        content = Path(path).read_text(encoding="utf-8")
        return ActionResult("read_file", "PASSED", f"read {len(content)} bytes", stdout=content)
    except FileNotFoundError:
        return ActionResult("read_file", "FAILED", f"file not found: {path}")
    except Exception as exc:
        return ActionResult("read_file", "FAILED", f"read error: {exc}")


def _do_sha256_file(action: dict) -> ActionResult:
    path = action.get("path", "")
    if not path:
        return ActionResult("sha256_file", "FAILED", "missing 'path'")
    try:
        data = Path(path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        return ActionResult("sha256_file", "PASSED", f"sha256={digest}", stdout=digest)
    except FileNotFoundError:
        return ActionResult("sha256_file", "FAILED", f"file not found: {path}")
    except Exception as exc:
        return ActionResult("sha256_file", "FAILED", f"hash error: {exc}")


def _do_command(action: dict) -> ActionResult:
    cmd = action.get("command")
    timeout = int(action.get("timeout", _DEFAULT_TIMEOUT))
    shell = action.get("shell", False)

    if not cmd:
        return ActionResult("command", "FAILED", "missing 'command'")

    allowed, reason = _check_command_allowed(cmd)
    if not allowed:
        return ActionResult("command", "FAILED", f"command rejected: {reason}")

    try:
        if shell:
            # shell=True only for string commands that passed allowlist
            if not isinstance(cmd, str):
                cmd = " ".join(str(c) for c in cmd)
            result = subprocess.run(
                cmd, shell=True,
                capture_output=True, text=True,
                timeout=timeout,
            )
        else:
            if isinstance(cmd, str):
                import shlex
                cmd = shlex.split(cmd)
            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                timeout=timeout,
            )
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return ActionResult(
            "command", status,
            f"exit={result.returncode}",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return ActionResult("command", "FAILED",
                            f"command timed out after {timeout}s",
                            exit_code=124)
    except Exception as exc:
        return ActionResult("command", "FAILED", f"execution error: {exc}")


# ─── Verification ─────────────────────────────────────────────────────────────

def _verify(spec: dict) -> dict:
    """
    Run verification steps. Returns a dict with PASSED/FAILED per check.
    If any check fails, overall verification_status = FAILED.
    """
    results: dict = {}
    overall = "PASSED"

    # file_exists
    if "file_exists" in spec:
        path = spec["file_exists"]
        ok = Path(path).exists()
        results["file_exists"] = {"path": path, "result": "PASSED" if ok else "FAILED"}
        if not ok:
            overall = "FAILED"

    # content_equals
    if "content_equals" in spec:
        path = spec["content_equals"].get("path", "")
        expected = spec["content_equals"].get("content", "")
        try:
            actual = Path(path).read_text(encoding="utf-8")
            # Strip trailing newline for comparison robustness
            ok = actual.rstrip("\n") == expected.rstrip("\n")
            results["content_equals"] = {
                "path": path,
                "expected": expected,
                "actual": actual,
                "result": "PASSED" if ok else "FAILED",
            }
            if not ok:
                overall = "FAILED"
        except FileNotFoundError:
            results["content_equals"] = {"path": path, "result": "FAILED", "error": "file not found"}
            overall = "FAILED"

    # sha256_equals
    if "sha256_equals" in spec:
        path = spec["sha256_equals"].get("path", "")
        expected_hash = spec["sha256_equals"].get("hash", "")
        try:
            actual_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            ok = actual_hash == expected_hash if expected_hash else True
            results["sha256_equals"] = {
                "path": path,
                "expected": expected_hash or "(any)",
                "actual": actual_hash,
                "result": "PASSED" if ok else "FAILED",
            }
            if not ok:
                overall = "FAILED"
        except FileNotFoundError:
            results["sha256_equals"] = {"path": path, "result": "FAILED", "error": "file not found"}
            overall = "FAILED"

    results["verification_status"] = overall
    return results


# ─── Main executor ────────────────────────────────────────────────────────────

_ACTION_HANDLERS = {
    "write_file":  _do_write_file,
    "read_file":   _do_read_file,
    "sha256_file": _do_sha256_file,
    "command":     _do_command,
}


def run_task(task: dict) -> ExecutorResult:
    task_id = task.get("task_id", "unknown")
    actions = task.get("actions", [])
    verify_spec = task.get("verify", {})

    executed: list[dict] = []
    overall_status = "PASSED"
    last_stdout = ""
    last_stderr = ""
    last_exit = 0
    error_class = None

    for action in actions:
        action_type = action.get("type", "")
        handler = _ACTION_HANDLERS.get(action_type)
        if handler is None:
            result = ActionResult(action_type, "FAILED", f"unknown action type: {action_type!r}")
        else:
            result = handler(action)

        executed.append(asdict(result))
        if result.stdout:
            last_stdout = result.stdout
        if result.stderr:
            last_stderr = result.stderr
        if result.exit_code is not None:
            last_exit = result.exit_code

        if result.status == "FAILED":
            overall_status = "FAILED"
            error_class = f"ACTION_FAILED:{action_type}"
            # Continue to collect evidence but mark overall as FAILED

    # Run verification
    verification = _verify(verify_spec) if verify_spec else {}
    if verification.get("verification_status") == "FAILED":
        overall_status = "FAILED"
        if error_class is None:
            error_class = "VERIFICATION_FAILED"

    return ExecutorResult(
        status=overall_status,
        task_id=task_id,
        actions_executed=executed,
        verification=verification,
        error_class=error_class,
        stdout=last_stdout,
        stderr=last_stderr,
        exit_code=last_exit,
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({
            "status": "FAILED",
            "error_class": "MISSING_TASK_FILE",
            "detail": "Usage: aims_local_executor.py <task_file.json>",
        }))
        return 1

    task_file = argv[1]
    try:
        task = json.loads(Path(task_file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(json.dumps({
            "status": "FAILED",
            "error_class": "TASK_FILE_NOT_FOUND",
            "task_file": task_file,
        }))
        return 1
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "status": "FAILED",
            "error_class": "TASK_FILE_INVALID_JSON",
            "detail": str(exc),
        }))
        return 1

    result = run_task(task)
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return 0 if result.status == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
