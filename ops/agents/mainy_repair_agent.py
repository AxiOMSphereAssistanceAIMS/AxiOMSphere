"""MainyRepairAgent — FastAPI wrapper around RepairExecutor.

Requires a valid audit_id (issued by PoliAgent) for every execution request.
Includes a circuit breaker: if error rate in the last 10 calls exceeds 50%,
returns 503 until the window clears.
Port: 8005. No authentication — internal service only.
"""
from __future__ import annotations

import logging
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from parent ops/ directory
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from core.service_auth import verify_service_token
from self_healing.repair_executor import RepairExecutor

log = logging.getLogger("aims.mainy_repair_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

_executor = RepairExecutor()
app = FastAPI(title="MainyRepairAgent", version="2.0.0")

# ── circuit breaker state ──────────────────────────────────────────────────────
# Stores True (success) / False (failure) for the last 10 outcomes.
_CIRCUIT_WINDOW = 10
_CIRCUIT_THRESHOLD = 0.50  # 50 % errors → open
_outcomes: deque[bool] = deque(maxlen=_CIRCUIT_WINDOW)


def _circuit_is_open() -> bool:
    """Return True when error rate in the last window exceeds the threshold."""
    if len(_outcomes) < _CIRCUIT_WINDOW:
        return False
    errors = sum(1 for ok in _outcomes if not ok)
    return (errors / _CIRCUIT_WINDOW) > _CIRCUIT_THRESHOLD


def _record_outcome(ok: bool) -> None:
    _outcomes.append(ok)


# ── request / response models ──────────────────────────────────────────────────

class ActionPayload(BaseModel):
    type: str
    # allow arbitrary extra fields (e.g. target, model, queue, …)
    model_config = {"extra": "allow"}


class ExecuteRequest(BaseModel):
    action: dict
    audit_id: str
    authorized_by: str


class ExecuteResponse(BaseModel):
    ok: bool
    action: str
    detail: str
    timestamp: str


# ── endpoints ──────────────────────────────────────────────────────────────────

@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest, _auth: None = Depends(verify_service_token)) -> ExecuteResponse:
    """Execute a repair action.

    Requires audit_id — PoliAgent must have already approved the action.
    Returns 403 if audit_id is missing, 503 if circuit breaker is open.
    """
    # Guard: audit_id must be present
    if not req.audit_id or not req.audit_id.strip():
        log.warning("execute rejected — missing audit_id")
        raise HTTPException(
            status_code=403,
            detail="audit_id is required; PoliAgent must approve before execution",
        )

    # Guard: circuit breaker
    if _circuit_is_open():
        log.error(
            "circuit_breaker_open — rejecting execute for action=%s",
            req.action.get("type"),
        )
        raise HTTPException(
            status_code=503,
            detail="circuit_breaker_open",
        )

    action_type = req.action.get("type", "unknown")
    log.info(
        "execute action_type=%s audit_id=%s authorized_by=%s",
        action_type, req.audit_id, req.authorized_by,
    )

    result = _executor.execute(req.action)
    _record_outcome(result.get("ok", False))

    ts = datetime.now(timezone.utc).isoformat()
    return ExecuteResponse(
        ok=result.get("ok", False),
        action=result.get("action", action_type),
        detail=result.get("detail", ""),
        timestamp=ts,
    )


@app.get("/circuit_status")
def circuit_status() -> dict:
    """Diagnostic endpoint — shows recent outcome window."""
    errors = sum(1 for ok in _outcomes if not ok)
    total = len(_outcomes)
    return {
        "window": _CIRCUIT_WINDOW,
        "recorded": total,
        "errors": errors,
        "error_rate": round(errors / total, 3) if total else 0.0,
        "open": _circuit_is_open(),
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "mainy_repair_agent",
        "port": 8005,
        "circuit_open": _circuit_is_open(),
    }


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "mainy_repair_agent:app",
        host="0.0.0.0",
        port=8005,
        log_level="info",
        reload=False,
    )
