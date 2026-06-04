"""Docker control tools for the Logi universal orchestrator.

Subprocess-based; no docker-sdk dependency.
Destructive actions (start/stop/restart) are gated — callers must pass
poli_approved=True or obtain an audit_id before invoking them.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any

log = logging.getLogger("aims.logi.docker_tools")

# How many log lines to return by default
_DEFAULT_LOG_TAIL = 50

# Containers that are never allowed to be stopped/restarted via this interface
_PROTECTED = frozenset({"axiomsphere-omi-bot", "axiomsphere-axi-bot"})


def docker_ps() -> dict[str, Any]:
    """Return a list of all containers with their status."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "docker ps failed"}

        containers = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                containers.append({"raw": line})

        return {"ok": True, "containers": containers, "count": len(containers)}
    except FileNotFoundError:
        return {"error": "docker not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "docker ps timed out"}
    except Exception as exc:
        log.exception("docker_ps failed: %s", exc)
        return {"error": str(exc)}


def docker_control(
    container: str,
    action: str,
    poli_approved: bool = False,
    audit_id: str = "",
) -> dict[str, Any]:
    """Start, stop, or restart a Docker container.

    Args:
        container: Container name or ID.
        action: One of start | stop | restart.
        poli_approved: Must be True for stop/restart actions.
        audit_id: PoliAgent audit ID (logged but not verified here).
    """
    action = action.lower().strip()
    if action not in ("start", "stop", "restart", "pause", "unpause"):
        return {"error": f"unsupported action: {action}. Use start|stop|restart."}

    if action in ("stop", "restart", "pause") and container in _PROTECTED:
        return {
            "error": f"container '{container}' is protected — cannot {action} via logi interface",
            "protected": True,
        }

    if action in ("stop", "restart") and not poli_approved:
        return {
            "error": f"action '{action}' requires PoliAgent approval (poli_approved=True + audit_id)",
            "requires_approval": True,
            "hint": "call poli_check first to obtain an audit_id",
        }

    log.info(
        "docker_control action=%s container=%s audit_id=%s approved=%s",
        action, container, audit_id, poli_approved,
    )

    try:
        result = subprocess.run(
            ["docker", action, container],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {
                "ok": False,
                "action": action,
                "container": container,
                "error": result.stderr.strip() or f"docker {action} failed",
            }
        return {
            "ok": True,
            "action": action,
            "container": container,
            "audit_id": audit_id,
            "output": result.stdout.strip() or f"{action} OK",
        }
    except subprocess.TimeoutExpired:
        return {"error": f"docker {action} timed out for {container}"}
    except Exception as exc:
        log.exception("docker_control failed: %s", exc)
        return {"error": str(exc)}


def container_logs(container: str, tail: int = _DEFAULT_LOG_TAIL) -> dict[str, Any]:
    """Fetch the last N log lines from a container."""
    tail = max(1, min(tail, 500))
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {
                "ok": False,
                "container": container,
                "error": result.stderr.strip() or "docker logs failed",
            }
        lines = (result.stdout + result.stderr).strip().splitlines()
        return {
            "ok": True,
            "container": container,
            "tail": tail,
            "lines": lines,
            "log_text": "\n".join(lines[-tail:]),
        }
    except subprocess.TimeoutExpired:
        return {"error": f"docker logs timed out for {container}"}
    except Exception as exc:
        log.exception("container_logs failed: %s", exc)
        return {"error": str(exc)}


def docker_compose_ps() -> dict[str, Any]:
    """Return compose-aware status (includes service name column)."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=20,
            cwd="/home/axi_omi_sphere/aims-workspace",
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "docker compose ps failed"}

        # compose ps --format json outputs one JSON object per line (not an array)
        services = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                services.append(json.loads(line))
            except json.JSONDecodeError:
                services.append({"raw": line})

        return {"ok": True, "services": services, "count": len(services)}
    except FileNotFoundError:
        return {"error": "docker compose not available"}
    except subprocess.TimeoutExpired:
        return {"error": "docker compose ps timed out"}
    except Exception as exc:
        log.exception("docker_compose_ps failed: %s", exc)
        return {"error": str(exc)}


def system_snapshot() -> dict[str, Any]:
    """Collect a full system snapshot: containers, GPU, disk, memory."""
    snapshot: dict[str, Any] = {"timestamp": time.time()}

    # --- containers ---
    containers_result = docker_ps()
    snapshot["containers"] = containers_result

    # --- GPU ---
    try:
        gpu_result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.free,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if gpu_result.returncode == 0:
            gpus = []
            for line in gpu_result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 5:
                    gpus.append({
                        "name": parts[0],
                        "memory_used_mb": parts[1],
                        "memory_free_mb": parts[2],
                        "memory_total_mb": parts[3],
                        "utilization_pct": parts[4],
                    })
            snapshot["gpu"] = gpus
        else:
            snapshot["gpu"] = {"error": gpu_result.stderr.strip()}
    except FileNotFoundError:
        snapshot["gpu"] = {"error": "nvidia-smi not found"}
    except Exception as exc:
        snapshot["gpu"] = {"error": str(exc)}

    # --- disk ---
    try:
        df_result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=5,
        )
        if df_result.returncode == 0:
            lines = df_result.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                snapshot["disk"] = {
                    "filesystem": parts[0] if parts else "?",
                    "size": parts[1] if len(parts) > 1 else "?",
                    "used": parts[2] if len(parts) > 2 else "?",
                    "avail": parts[3] if len(parts) > 3 else "?",
                    "use_pct": parts[4] if len(parts) > 4 else "?",
                }
    except Exception as exc:
        snapshot["disk"] = {"error": str(exc)}

    # --- memory ---
    try:
        free_result = subprocess.run(
            ["free", "-h"],
            capture_output=True, text=True, timeout=5,
        )
        if free_result.returncode == 0:
            lines = free_result.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                snapshot["memory"] = {
                    "total": parts[1] if len(parts) > 1 else "?",
                    "used": parts[2] if len(parts) > 2 else "?",
                    "free": parts[3] if len(parts) > 3 else "?",
                }
    except Exception as exc:
        snapshot["memory"] = {"error": str(exc)}

    return snapshot
