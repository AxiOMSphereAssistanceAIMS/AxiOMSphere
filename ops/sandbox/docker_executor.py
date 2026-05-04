"""Docker-based sandboxed Python execution with kernel-level isolation.

Runs code in a Docker container with:
  - Network namespace isolation (--net=none)
  - Filesystem mount restrictions (tmpdir only)
  - Hard memory + CPU limits
  - Wall-clock timeout
  - File I/O via volume mounts

Requires:
  - Docker daemon running
  - aims-sandbox:latest image built (run: bash ops/sandbox/build_and_test.sh)
  - docker package installed (pip install docker)

Usage:
    ex = DockerSandboxExecutor(
        image="aims-sandbox:latest",
        timeout=30,
        memory_limit="1g",
        cpus_limit=1.0
    )
    result = ex.run(
        "import pandas as pd; print(pd.DataFrame({'x': [1, 2, 3]}))",
        files={"input.csv": b"x,y\\n1,2\\n"},
        collect=["output.xlsx"]
    )
    if result.ok:
        print(result.stdout)
    else:
        print(result.error)
"""
from __future__ import annotations

import docker
import json
import logging
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("aims.sandbox.docker")

_DEFAULT_TIMEOUT = 30
_DEFAULT_MEMORY = "1g"
_DEFAULT_CPUS = 1.0


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    output_files: dict[str, bytes] | None = None

    @property
    def error(self) -> str:
        if self.timed_out:
            return "Timeout expired"
        if self.stderr:
            return self.stderr.strip()
        return f"exit code {self.returncode}"


class DockerSandboxExecutor:
    """Run Python snippets in a Docker container (kernel-level isolation)."""

    def __init__(
        self,
        image: str = "aims-sandbox:latest",
        timeout: int = _DEFAULT_TIMEOUT,
        memory_limit: str = _DEFAULT_MEMORY,
        cpus_limit: float = _DEFAULT_CPUS,
    ) -> None:
        self.image = image
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpus_limit = cpus_limit
        self.client = docker.from_env()

    def run(
        self,
        code: str,
        *,
        files: dict[str, bytes] | None = None,
        collect: list[str] | None = None,
    ) -> SandboxResult:
        """Execute *code* in Docker container; return stdout/stderr + collected files."""
        files = files or {}
        collect = collect or []
        code = textwrap.dedent(code)

        with tempfile.TemporaryDirectory(prefix="aims_sandbox_") as tmpdir:
            tmppath = Path(tmpdir)

            # Write input files to tmpdir
            for filename, data in files.items():
                dest = tmppath / Path(filename).name  # strip path prefix for safety
                dest.write_bytes(data)

            # Write code script
            script = tmppath / "script.py"
            script.write_text(code, encoding="utf-8")

            try:
                # Run container with strict isolation
                container = self.client.containers.run(
                    self.image,
                    ["python3", "-u", "/tmp/sandbox-work/script.py"],
                    volumes={tmpdir: {"bind": "/tmp/sandbox-work", "mode": "rw"}},
                    network_disabled=True,  # --net=none
                    mem_limit=self.memory_limit,
                    memswap_limit=self.memory_limit,
                    cpu_quota=int(self.cpus_limit * 100000),
                    stdin_open=False,
                    detach=True,
                    remove=True,
                )

                # Wait for completion with timeout
                try:
                    exit_code = container.wait(timeout=self.timeout)["StatusCode"]
                    timed_out = False
                except Exception:
                    container.stop(timeout=1)
                    exit_code = -1
                    timed_out = True

                # Capture logs
                stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
                stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

                # Collect output files
                output_files: dict[str, bytes] = {}
                for filename in collect:
                    fpath = tmppath / Path(filename).name
                    if fpath.exists():
                        try:
                            data = fpath.read_bytes()
                            output_files[filename] = data
                        except Exception as exc:
                            log.warning("sandbox: failed to read output %s: %s", filename, exc)

                return SandboxResult(
                    ok=exit_code == 0 and not timed_out,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=exit_code,
                    timed_out=timed_out,
                    output_files=output_files if output_files else None,
                )

            except docker.errors.ImageNotFound:
                log.error("sandbox: image %s not found; build with: docker build -f ops/sandbox/Dockerfile -t %s .", self.image, self.image)
                return SandboxResult(
                    ok=False,
                    stdout="",
                    stderr=f"Image not found: {self.image}",
                    returncode=-1,
                )
            except Exception as exc:
                log.exception("sandbox: unexpected docker executor error")
                return SandboxResult(
                    ok=False,
                    stdout="",
                    stderr=str(exc),
                    returncode=-2,
                )


def docker_available() -> bool:
    """Check if Docker daemon is accessible and aims-sandbox image exists."""
    try:
        client = docker.from_env()
        client.images.get("aims-sandbox:latest")
        return True
    except Exception:
        return False
