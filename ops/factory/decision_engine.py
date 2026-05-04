"""Decision engine — pure functions, no I/O.

On every pipeline step failure, decide() is called to determine:
  RETRY    — transient error (GPU busy, rate limit), back-off and retry
  REPAIR   — infrastructure error; call PoliAgent + MainyRepairAgent, then retry
  ESCALATE — code-level error (404 endpoint missing); invoke Claude Code repair
  FINETUNE — quality gate failure; save training pair, trigger TrainiAgent
  ABORT    — unrecoverable (policy denied, max retries, code bug in filter step)
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any


class Action(str, enum.Enum):
    RETRY    = "RETRY"
    REPAIR   = "REPAIR"
    ESCALATE = "ESCALATE"
    FINETUNE = "FINETUNE"
    ABORT    = "ABORT"


@dataclass
class Decision:
    action:        Action
    reason:        str
    repair_action: dict[str, Any] = field(default_factory=dict)
    backoff_s:     float = 0.0
    save_pair:     bool  = False


# Maps pipeline step name → SysPolic-accepted container name for restart_container action.
# All container names use axiomsphere-* format to match docker-compose.yml.
STEP_SERVICE_MAP: dict[str, str | None] = {
    "knomi_search":    "axiomsphere-qdrant",
    "context_filter":  None,            # in-process, no container
    "doci_compose":    "axiomsphere-doc-agent",
    "cloud_validate":  "axiomsphere-aims-api",
    "poli_check":      None,            # host process, no container restart
    "omi_store":       "axiomsphere-omi-api",
}

_HTTP_STATUS_RE = re.compile(r"HTTP[^\d]*(\d{3})")
_GPU_SIGNALS = ("model loading", "loading model", "model is loading", "cuda out of memory")


def _parse_http_status(error: str) -> int | None:
    m = _HTTP_STATUS_RE.search(error or "")
    return int(m.group(1)) if m else None


def _is_gpu_contention(error: str) -> bool:
    err_lower = (error or "").lower()
    return any(sig in err_lower for sig in _GPU_SIGNALS)


def _restart_action(step_name: str) -> dict[str, Any]:
    target = STEP_SERVICE_MAP.get(step_name)
    if target:
        return {"type": "restart_container", "target": target}
    return {"type": "reload_config", "target": step_name}


def decide(
    error: str | None,
    http_status: int | None,
    step_name: str,
    attempt: int,
    max_attempts: int = 3,
) -> Decision:
    """Return a Decision based on the error signal from a failed pipeline step.

    Pure function — no I/O, no side effects. Called by SupervisedPipeline._run_step().
    """
    if attempt >= max_attempts:
        return Decision(Action.ABORT, f"max attempts ({max_attempts}) reached")

    # context_filter is in-process Python — any error is a code bug, not infra
    if step_name == "context_filter":
        return Decision(Action.ABORT, "context_filter code error — not retryable")

    # Policy denial is a deliberate gate, not an error
    if error and "policy_denied" in error:
        return Decision(Action.ABORT, "policy gate denied action")

    err = error or ""
    status = http_status or _parse_http_status(err)

    # GPU contention (Ollama returns 500 with "model loading" body)
    if status == 500 and _is_gpu_contention(err):
        return Decision(Action.RETRY, "GPU contention — model loading", backoff_s=15.0)

    # Transient 500 on first attempt
    if status == 500 and attempt < 2:
        return Decision(Action.RETRY, "server error, attempt < 2", backoff_s=5.0)

    # Persistent 500 → repair (restart container)
    if status == 500:
        return Decision(
            Action.REPAIR, "persistent server error",
            repair_action=_restart_action(step_name),
            backoff_s=10.0,
        )

    # Schema / validation error → reload config and retry
    if status == 422:
        return Decision(
            Action.REPAIR, "schema validation error",
            repair_action={"type": "reload_config", "target": step_name},
            backoff_s=2.0,
        )

    # Endpoint missing → Claude Code must fix the code
    if status == 404:
        return Decision(Action.ESCALATE, "endpoint not found — code-level fix required")

    # Service unavailable → restart container
    if status == 503:
        return Decision(
            Action.REPAIR, "service unavailable",
            repair_action=_restart_action(step_name),
            backoff_s=5.0,
        )

    # Rate limit (cloud validation uses external APIs)
    if status == 429:
        return Decision(Action.RETRY, "rate limited", backoff_s=60.0)

    # Timeout signal (embedded in error string by call_tool)
    if "timeout" in err.lower() or "timed out" in err.lower():
        if attempt < 2:
            return Decision(Action.RETRY, "timeout, attempt < 2", backoff_s=20.0)
        return Decision(
            Action.REPAIR, "persistent timeout",
            repair_action=_restart_action(step_name),
            backoff_s=20.0,
        )

    # Quality below threshold (CloudValidation response, not an HTTP error)
    if "quality" in err.lower() and "threshold" in err.lower():
        return Decision(Action.FINETUNE, "quality below threshold", save_pair=True)

    # Unknown error on first attempt → retry once
    if attempt < 1:
        return Decision(Action.RETRY, f"unknown error, retry once: {err[:120]}", backoff_s=3.0)

    # Unknown persistent error → escalate to Claude Code
    return Decision(Action.ESCALATE, f"unhandled error after {attempt} attempts: {err[:200]}")
