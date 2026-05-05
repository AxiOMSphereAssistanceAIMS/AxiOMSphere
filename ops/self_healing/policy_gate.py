"""SysPolic — deterministic policy gate for self-healing actions.

STRICT rule-based, NO LLM. Acts as gatekeeper before SysMR executes anything.
Returns allow/deny and the reason. Never ambiguous.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("aims.syspolic")

SAFE_ACTIONS: frozenset[str] = frozenset({
    "restart_container",
    "switch_model",
    "clear_queue",
    "reload_config",
    "pause_worker",
    "resume_worker",
    "repairman_inspect",
    "repairman_repair",
    "repairman_fix",
})

DANGEROUS_ACTIONS: frozenset[str] = frozenset({
    "delete_db",
    "exec_shell",
    "wipe_storage",
    "drop_table",
    "rm_rf",
    "push_to_prod",
})

# services that may be restarted automatically (docker compose service names, not container_name)
RESTARTABLE_CONTAINERS: frozenset[str] = frozenset({
    "axi-bot",
    "omi-bot",
    "argus-bot",
    "logi-bot",
    "aims-api",
    "aims-worker",
    "aims-orchestrator",
    "queue-api",
    "task-registry",
    "doc-agent",
    "knomi-agent",
    "poli-agent",
    "mainy-repair-agent",
    "omi-api",
    "qdrant",
    "aims-redis",
    "schedule",
})


class PolicyDenied(Exception):
    pass


class SysPolic:
    """Rule-based policy gate. Call allow() before every SysMR action."""

    def allow(self, action: dict[str, Any]) -> bool:
        """Return True if action is permitted, False otherwise.

        Raises PolicyDenied with reason if action is explicitly forbidden.
        """
        atype = action.get("type", "")

        if atype in DANGEROUS_ACTIONS:
            reason = f"action type '{atype}' is on the DANGEROUS list"
            log.warning("DENIED: %s | action=%s", reason, action)
            raise PolicyDenied(reason)

        if atype == "restart_container":
            target = action.get("target", "")
            if target not in RESTARTABLE_CONTAINERS:
                reason = f"container '{target}' not in RESTARTABLE_CONTAINERS"
                log.warning("DENIED: %s", reason)
                raise PolicyDenied(reason)

        if atype == "switch_model":
            model = action.get("model", "")
            if not model:
                reason = "switch_model requires 'model' field"
                log.warning("DENIED: %s", reason)
                raise PolicyDenied(reason)

        # Repairman action validation
        if atype in ("repairman_inspect", "repairman_repair", "repairman_fix"):
            task = action.get("task", "")
            if not task:
                reason = f"{atype} requires 'task' field"
                log.warning("DENIED: %s", reason)
                raise PolicyDenied(reason)

            # Check concept preservation for repair and fix
            if atype in ("repairman_repair", "repairman_fix"):
                concept_preserved = action.get("concept_preserved", False)
                restorative = action.get("restorative", False)

                if not concept_preserved:
                    reason = f"{atype} denied: concept must be preserved (concept_preserved=True required)"
                    log.warning("DENIED: %s", reason)
                    raise PolicyDenied(reason)

                if not restorative:
                    reason = f"{atype} denied: changes must be restorative (restorative=True required)"
                    log.warning("DENIED: %s", reason)
                    raise PolicyDenied(reason)

        if atype not in SAFE_ACTIONS:
            reason = f"action type '{atype}' is not in SAFE_ACTIONS whitelist"
            log.warning("DENIED: %s | action=%s", reason, action)
            raise PolicyDenied(reason)

        log.info("ALLOWED: type=%s", atype)
        return True
