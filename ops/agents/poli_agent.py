"""PoliAgent — FastAPI wrapper around SysPolic policy gate.

Every self-healing action must pass through this gate before execution.
Logs every decision (allow and deny) to the audit log file.
Port: 8004. No authentication — internal service only.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from parent ops/ directory
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

import uvicorn
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from core.service_auth import verify_service_token
from self_healing.policy_gate import SysPolic, PolicyDenied

log = logging.getLogger("aims.poli_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# Audit log path — ensure parent directory exists
AUDIT_LOG_PATH = Path(
    os.environ.get(
        "POLI_AUDIT_LOG",
        "/home/axi_omi_sphere/aims-workspace/aims_workspace/poli_audit.log",
    )
)
AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_policy = SysPolic()
app = FastAPI(title="PoliAgent", version="2.0.0")


# ── request / response models ──────────────────────────────────────────────────

class CheckRequest(BaseModel):
    action_type: str
    params: dict
    requester: str
    department: str


class CheckResponse(BaseModel):
    allowed: bool
    reason: str
    audit_id: str


# ── helpers ────────────────────────────────────────────────────────────────────

def _write_audit(
    audit_id: str,
    allowed: bool,
    action_type: str,
    requester: str,
    department: str,
    reason: str,
) -> None:
    """Append one audit record to the audit log file."""
    ts = datetime.now(timezone.utc).isoformat()
    verdict = "ALLOW" if allowed else "DENY"
    line = (
        f"{ts} | {verdict} | audit_id={audit_id} | action_type={action_type} "
        f"| requester={requester} | department={department} | reason={reason}\n"
    )
    try:
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:
        log.error("failed to write audit log: %s", exc)


# ── endpoints ──────────────────────────────────────────────────────────────────

@app.post("/check", response_model=CheckResponse)
def check(req: CheckRequest, _auth: None = Depends(verify_service_token)) -> CheckResponse:
    """Check whether an action is allowed by policy.

    Returns audit_id that must be passed to MainyRepairAgent for execution.
    """
    audit_id = uuid.uuid4().hex

    # Build action dict that SysPolic.allow() expects
    action = {"type": req.action_type, **req.params}

    allowed = False
    reason = ""

    try:
        _policy.allow(action)
        allowed = True
        reason = f"action '{req.action_type}' permitted by policy"
        log.info(
            "ALLOW audit_id=%s action_type=%s requester=%s",
            audit_id, req.action_type, req.requester,
        )
    except PolicyDenied as exc:
        allowed = False
        reason = str(exc)
        log.warning(
            "DENY audit_id=%s action_type=%s requester=%s reason=%s",
            audit_id, req.action_type, req.requester, reason,
        )
    except Exception as exc:
        allowed = False
        reason = f"policy check error: {exc}"
        log.exception("unexpected error in policy check: %s", exc)

    _write_audit(
        audit_id=audit_id,
        allowed=allowed,
        action_type=req.action_type,
        requester=req.requester,
        department=req.department,
        reason=reason,
    )

    return CheckResponse(allowed=allowed, reason=reason, audit_id=audit_id)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "poli_agent", "port": 8004}


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "poli_agent:app",
        host="0.0.0.0",
        port=8004,
        log_level="info",
        reload=False,
    )
