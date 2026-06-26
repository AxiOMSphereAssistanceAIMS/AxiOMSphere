from __future__ import annotations

import os
import socket
import subprocess
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_REDIS_URL = "redis://aims-redis:6379/0"
DEFAULT_SERVICE_NAME = "aims-redis"


@dataclass(frozen=True)
class RedisRuntimeResolution:
    redis_service_present: bool
    compose_service_name: str
    selected_redis_url: str
    runtime_mode: str
    host_localhost_available: bool
    compose_hostname_expected: bool
    blocker: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compose_services() -> list[str]:
    try:
        result = subprocess.run(
            ["docker", "compose", "config", "--services"],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _localhost_port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 6379), timeout=1):
            return True
    except Exception:
        return False


def _hostname_resolves(hostname: str) -> bool:
    try:
        socket.gethostbyname(hostname)
        return True
    except Exception:
        return False


def _runtime_hint(runtime_hint: str | None) -> str:
    text = (runtime_hint or os.environ.get("DOCSREG_RUNTIME_MODE") or "").strip().lower()
    if text in {"compose", "compose_network", "compose-network", "container"}:
        return "compose_network"
    if text in {"host", "localhost"}:
        return "host"
    return "unknown"


def resolve_redis_url(runtime_hint: str | None = None) -> dict[str, Any]:
    """Resolve the canonical Redis URL for DOCSREG/DOCGEN runtimes."""
    for env_name in ("DOCSREG_REDIS_URL", "REDIS_URL", "AIMS_REDIS_URL"):
        value = os.environ.get(env_name, "").strip()
        if value:
            compose_services = _compose_services()
            return RedisRuntimeResolution(
                redis_service_present=DEFAULT_SERVICE_NAME in compose_services,
                compose_service_name=DEFAULT_SERVICE_NAME,
                selected_redis_url=value,
                runtime_mode=_runtime_hint(runtime_hint),
                host_localhost_available=_localhost_port_open(),
                compose_hostname_expected=_hostname_resolves(DEFAULT_SERVICE_NAME),
                blocker=None,
            ).to_dict()

    services = _compose_services()
    redis_service_present = DEFAULT_SERVICE_NAME in services
    host_localhost_available = _localhost_port_open()
    compose_hostname_expected = _hostname_resolves(DEFAULT_SERVICE_NAME)
    resolved_hint = _runtime_hint(runtime_hint)

    blocker: str | None = None
    if resolved_hint == "compose_network" or compose_hostname_expected:
        selected = DEFAULT_REDIS_URL
        runtime_mode = "compose_network"
    elif host_localhost_available:
        selected = "redis://127.0.0.1:6379/0"
        runtime_mode = "host"
    elif redis_service_present:
        selected = DEFAULT_REDIS_URL
        runtime_mode = "blocked"
        blocker = "runtime_network_mismatch"
    else:
        selected = DEFAULT_REDIS_URL
        runtime_mode = "unknown"
        blocker = "redis_unavailable"

    if redis_service_present and not host_localhost_available and runtime_mode != "compose_network":
        blocker = "runtime_network_mismatch"
        if resolved_hint != "host":
            runtime_mode = "blocked"

    return RedisRuntimeResolution(
        redis_service_present=redis_service_present,
        compose_service_name=DEFAULT_SERVICE_NAME,
        selected_redis_url=selected,
        runtime_mode=runtime_mode,
        host_localhost_available=host_localhost_available,
        compose_hostname_expected=compose_hostname_expected,
        blocker=blocker,
    ).to_dict()
