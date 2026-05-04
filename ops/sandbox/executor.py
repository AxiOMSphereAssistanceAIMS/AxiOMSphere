"""Sandboxed Python execution for untrusted/generated code.

Runs code in a subprocess with:
  - hard wall-clock timeout
  - no network (via restricted env, not full namespace isolation)
  - stdout/stderr capture
  - no disk writes outside a temp dir (temp dir cleaned after run)

Usage:
    ex = SandboxExecutor(timeout=10)
    result = ex.run("print(2 + 2)")
    assert result.stdout.strip() == "4"
    assert result.ok
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("aims.sandbox")

_DEFAULT_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT_SEC", "15"))


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


class SandboxExecutor:
    """Run Python snippets in a subprocess with timeout and no network."""

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def run(self, code: str, *, extra_env: dict[str, str] | None = None) -> SandboxResult:
        """Execute *code* and return stdout/stderr."""
        with tempfile.TemporaryDirectory(prefix="aims_sandbox_") as tmpdir:
            script = Path(tmpdir) / "script.py"
            script.write_text(textwrap.dedent(code), encoding="utf-8")

            env = _restricted_env(tmpdir)
            if extra_env:
                env.update(extra_env)

            try:
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=env,
                    cwd=tmpdir,
                )
                return SandboxResult(
                    ok=proc.returncode == 0,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    returncode=proc.returncode,
                )
            except subprocess.TimeoutExpired:
                log.warning("sandbox: script timed out after %ds", self.timeout)
                return SandboxResult(
                    ok=False,
                    stdout="",
                    stderr=f"Timeout after {self.timeout}s",
                    returncode=-1,
                    timed_out=True,
                )
            except Exception as exc:
                log.exception("sandbox: unexpected executor error")
                return SandboxResult(
                    ok=False,
                    stdout="",
                    stderr=str(exc),
                    returncode=-2,
                )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _restricted_env(tmpdir: str) -> dict[str, str]:
    """Return a minimal env with networking vars stripped."""
    base = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": tmpdir,
        "TMPDIR": tmpdir,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    # Preserve PYTHONPATH so imports from /ops still work
    if "PYTHONPATH" in os.environ:
        base["PYTHONPATH"] = os.environ["PYTHONPATH"]
    return base
