"""SysMR — Self Maintenance & Repair execution layer.

Receives a proposed action dict, passes it through SysPolic, then executes.
Hybrid: deterministic rules for known actions, limited LLM for analysis only.
Does NOT make decisions — only executes what it receives.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

# Allow imports from parent ops/ directory
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

from core.runtime_names import QUEUE_PENDING, QUEUE_PROCESSING
from .policy_gate import SysPolic, PolicyDenied

log = logging.getLogger("aims.sysmr")

_policy = SysPolic()


class RepairExecutor:

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute a repair action after policy check.

        Returns {"ok": bool, "action": str, "detail": str}
        """
        atype = action.get("type", "")
        try:
            _policy.allow(action)
        except PolicyDenied as e:
            log.warning("action blocked by policy: %s", e)
            return {"ok": False, "action": atype, "detail": f"policy denied: {e}"}

        handler = _HANDLERS.get(atype)
        if handler is None:
            return {"ok": False, "action": atype, "detail": f"no handler for '{atype}'"}

        try:
            detail = handler(action)
            log.info("action executed: type=%s detail=%s", atype, detail)
            return {"ok": True, "action": atype, "detail": detail}
        except Exception as e:
            log.exception("action failed: type=%s", atype)
            return {"ok": False, "action": atype, "detail": str(e)}


# ── action handlers ────────────────────────────────────────────────────────────

def _restart_container(action: dict[str, Any]) -> str:
    target = action["target"]
    result = subprocess.run(
        ["docker", "compose", "restart", target],
        capture_output=True,
        text=True,
        cwd="/home/axi_omi_sphere/aims-workspace",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:300])
    return f"restarted {target}"


def _switch_model(action: dict[str, Any]) -> str:
    model = action["model"]
    import os
    os.environ["OMI_OLLAMA_MODEL"] = model
    return f"switched to {model} (env only — restart required to persist)"


def _clear_queue(action: dict[str, Any]) -> str:
    try:
        import redis
        host = action.get("redis_host", "aims-redis")
        port = int(action.get("redis_port", 6379))
        queues = action.get("queues") or [action.get("queue", QUEUE_PENDING), QUEUE_PROCESSING]
        r = redis.Redis(host=host, port=port, decode_responses=True)
        count = 0
        for q in queues:
            count += r.llen(q)
            r.delete(q)
        return f"cleared {count} items from {queues}"
    except Exception as e:
        raise RuntimeError(f"redis clear failed: {e}") from e


def _reload_config(_action: dict[str, Any]) -> str:
    return "config reload signal sent (SIGHUP not implemented — restart container instead)"


def _pause_worker(action: dict[str, Any]) -> str:
    queue = action.get("queue", QUEUE_PENDING)
    try:
        import redis
        host = action.get("redis_host", "aims-redis")
        r = redis.Redis(host=host, decode_responses=True)
        r.set("aims:worker:paused", "1", ex=3600)
        return f"worker pause flag set for queue {queue}"
    except Exception as e:
        raise RuntimeError(f"redis pause failed: {e}") from e


def _resume_worker(action: dict[str, Any]) -> str:
    try:
        import redis
        host = action.get("redis_host", "aims-redis")
        r = redis.Redis(host=host, decode_responses=True)
        r.delete("aims:worker:paused")
        return "worker resume flag cleared"
    except Exception as e:
        raise RuntimeError(f"redis resume failed: {e}") from e


_HANDLERS: dict[str, Any] = {
    "restart_container": _restart_container,
    "switch_model":      _switch_model,
    "clear_queue":       _clear_queue,
    "reload_config":     _reload_config,
    "pause_worker":      _pause_worker,
    "resume_worker":     _resume_worker,
}
