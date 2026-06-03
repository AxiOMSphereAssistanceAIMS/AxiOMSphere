#!/usr/bin/env python3
"""Repairman API — HTTP endpoint for automated repairman task triggering.

Allows LogiOrchestrator and ArgusAgent to trigger repairman tasks programmatically.
Port: 8010
"""
from __future__ import annotations

import logging
import os
import pathlib
import subprocess
import threading
import time
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

# Import automation flags and helpers from repairman_bot
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from repairman_bot import (
    AUTO_INSPECT, AUTO_STATUS, AUTO_CURRENT, AUTO_REPAIR, AUTO_FIX, AUTO_MODEL,
    RUN_REPAIRMAN, ROOT, ISSUES_DIR, LOGS_DIR, CURRENT_MODEL,
    write_issue_file, current_model_text, set_model, proxy_health,
    RUN_LOCK
)

# Import service auth
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core.service_auth import verify_service_token

log = logging.getLogger("repairman_api")
app = FastAPI(title="RepairmanAPI", version="1.0.0")

ISSUES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ── Request/Response models ────────────────────────────────────────────────

class RepairmanTaskRequest(BaseModel):
    task: str
    mode: str = "repair"  # inspect | repair | fix
    source: str = "logi_orchestrator"  # logi_orchestrator | argus_agent | manual


class RepairmanTaskResponse(BaseModel):
    status: str
    message: str
    issue_path: str | None = None
    log_path: str | None = None


class ModelSwitchRequest(BaseModel):
    profile: str  # kiro-sonnet | kr-sonnet | kiro-haiku | kr-haiku | local-nemotron | auto


class StatusResponse(BaseModel):
    current_model: str
    proxy_health: dict | str
    lock_acquired: bool


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.post("/trigger", response_model=RepairmanTaskResponse)
async def trigger_task(req: RepairmanTaskRequest, _auth: None = Depends(verify_service_token)):
    """Trigger a repairman task (automated or manual).

    Requires PoliAgent approval before execution.
    """

    # Check automation policy
    if req.mode == "inspect" and not AUTO_INSPECT:
        raise HTTPException(status_code=403, detail="inspect mode not allowed in automation policy")
    if req.mode == "repair" and not AUTO_REPAIR:
        raise HTTPException(status_code=403, detail="repair mode not allowed in automation policy")
    if req.mode == "fix" and not AUTO_FIX:
        raise HTTPException(status_code=403, detail="fix mode not allowed in automation policy")

    # Request PoliAgent approval
    import httpx
    poli_url = os.getenv("POLI_URL", "http://poli-agent:8004") + "/check"

    # Map mode to action_type
    action_type_map = {
        "inspect": "repairman_inspect",
        "repair": "repairman_repair",
        "fix": "repairman_fix",
    }
    action_type = action_type_map.get(req.mode, "repairman_repair")

    # Build policy check request
    policy_check = {
        "action_type": action_type,
        "params": {
            "task": req.task,
            "mode": req.mode,
            "concept_preserved": True,  # Repairman always preserves concept
            "restorative": True,        # Repairman changes are restorative
        },
        "requester": req.source,
        "department": "self_healing",
    }

    try:
        from core.service_auth import service_headers
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(poli_url, json=policy_check, headers=service_headers())
            policy_result = resp.json()

        if not policy_result.get("allowed", False):
            reason = policy_result.get("reason", "unknown")
            log.warning("PoliAgent denied repairman task: %s", reason)

            # Send notification to Telegram if bot token is available
            try:
                telegram_token = os.environ.get("REPAIRMAN_BOT_TOKEN")
                telegram_chat_id = os.environ.get("REPAIRMAN_ADMIN_CHAT_ID")

                if telegram_token and telegram_chat_id:
                    import json
                    import urllib.request

                    proposal_message = (
                        f"🚫 PoliAgent denied automated repair\n\n"
                        f"Task: {req.task[:200]}\n"
                        f"Mode: {req.mode}\n"
                        f"Source: {req.source}\n"
                        f"Reason: {reason}\n\n"
                        f"💡 Repairman proposal:\n"
                        f"This task appears to be restorative and concept-preserving. "
                        f"If you approve, use:\n"
                        f"/fix {req.task[:100]}"
                    )

                    telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                    telegram_payload = {
                        "chat_id": telegram_chat_id,
                        "text": proposal_message,
                        "disable_web_page_preview": True,
                    }

                    req_tg = urllib.request.Request(
                        telegram_url,
                        data=json.dumps(telegram_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req_tg, timeout=10) as resp:
                        log.info("Telegram notification sent: %d", resp.status)
            except Exception as tg_error:
                log.warning("Failed to send Telegram notification: %s", tg_error)

            raise HTTPException(
                status_code=403,
                detail=f"PoliAgent denied: {reason}"
            )

        audit_id = policy_result.get("audit_id", "unknown")
        log.info("PoliAgent approved repairman task: audit_id=%s", audit_id)

    except httpx.HTTPError as e:
        log.error("Failed to contact PoliAgent: %s", e)
        raise HTTPException(status_code=503, detail=f"PoliAgent unavailable: {e}")

    if not RUN_LOCK.acquire(blocking=False):
        return RepairmanTaskResponse(
            status="busy",
            message="Repairman is already running another task"
        )

    try:
        # Prepare task text based on mode
        if req.mode == "inspect":
            full_task = "Inspect only. Do not modify files.\n\nTask:\n" + req.task
        elif req.mode == "fix":
            full_task = (
                "You have explicit permission to modify project files inside /home/axi_omi_sphere/aims-workspace as needed for this task.\n"
                "Goal: Restore process operability without changing concept.\n"
                "Do not modify secrets, credentials, databases, production data, model files, external storage, deploy, git push, or restart services unless separately explicitly requested.\n\n"
                f"PoliAgent audit_id: {audit_id}\n\n"
                "Task:\n" + req.task
            )
        else:  # repair
            full_task = (
                "Run as AIMS Claude Code Repairman. Follow the repairman permission model.\n"
                "Concept review passed. Production process output must remain unchanged.\n\n"
                f"PoliAgent audit_id: {audit_id}\n\n"
                "Task:\n" + req.task
            )

        issue_path = write_issue_file(req.mode, 0, full_task)  # user_id=0 for automated
        log_path = LOGS_DIR / f"{issue_path.stem}.log"

        log.info("Repairman task triggered: mode=%s source=%s audit_id=%s", req.mode, req.source, audit_id)

        # Run in background thread
        def _run():
            try:
                env = os.environ.copy()
                env["NO_COLOR"] = "1"
                env["TERM"] = env.get("TERM", "xterm")

                started = time.time()
                log.info("DEBUG: RUN_REPAIRMAN=%s ROOT=%s exists=%s", RUN_REPAIRMAN, ROOT, RUN_REPAIRMAN.exists())
                proc = subprocess.run(
                    [str(RUN_REPAIRMAN), str(ROOT), str(issue_path)],
                    cwd=str(ROOT),
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=3600,
                )
                elapsed = round(time.time() - started, 1)
                output = proc.stdout or ""
                log_path.write_text(output, encoding="utf-8", errors="replace")

                log.info("Repairman task finished: exit=%d elapsed=%.1fs audit_id=%s", proc.returncode, elapsed, audit_id)
            except Exception as e:
                log.exception("Repairman task error: %s", e)
            finally:
                RUN_LOCK.release()

        threading.Thread(target=_run, daemon=True).start()

        return RepairmanTaskResponse(
            status="started",
            message=f"Task accepted, thinking... (mode={req.mode}, source={req.source}, audit_id={audit_id})",
            issue_path=str(issue_path),
            log_path=str(log_path)
        )

    except Exception as e:
        RUN_LOCK.release()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/switch_model")
async def switch_model(req: ModelSwitchRequest, _auth: None = Depends(verify_service_token)):
    """Switch repairman model (automated for system reliability)."""
    if not AUTO_MODEL:
        raise HTTPException(status_code=403, detail="model switching not allowed in automation policy")
    
    ok, output = set_model(req.profile)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Model switch failed: {output}")
    
    log.info("Model switched to %s", req.profile)
    return {
        "status": "ok",
        "profile": req.profile,
        "output": output,
        "current": current_model_text()
    }


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get current repairman status (always allowed)."""
    try:
        import json
        health_data = proxy_health()
        try:
            health_dict = json.loads(health_data)
        except:
            health_dict = health_data
    except Exception as e:
        health_dict = {"error": str(e)}
    
    return StatusResponse(
        current_model=current_model_text(),
        proxy_health=health_dict,
        lock_acquired=not RUN_LOCK.acquire(blocking=False) or (RUN_LOCK.release() or False)
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "repairman_api",
        "port": 8010,
        "automation_policy": {
            "inspect": AUTO_INSPECT,
            "status": AUTO_STATUS,
            "current": AUTO_CURRENT,
            "repair": AUTO_REPAIR,
            "fix": AUTO_FIX,
            "model": AUTO_MODEL,
        }
    }


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8010, log_level="info")
