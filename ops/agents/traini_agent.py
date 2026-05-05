"""
TrainiAgent — fine-tuning pipeline trigger and management.

Wraps the existing ops/ft/ pipeline:
  - Reads training pairs from aims_workspace/training/
  - Triggers fine-tuning via the existing FT config/scripts
  - Reports status back to LogiOrchestrator
  - Canary deployment: updates ops/config/nemoclaw_inference_routing.yaml on promotion

Port: 8007
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Allow imports from parent ops/ directory
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from core.service_auth import verify_service_token

log = logging.getLogger("traini_agent")
app = FastAPI(title="TrainiAgent", version="2.0")

_OPS = str(Path(__file__).resolve().parent.parent)
_WORKSPACE = Path(os.environ.get(
    "AIMS_WORKSPACE",
    "/home/axi_omi_sphere/aims-workspace/aims_workspace",
))
_TRAINING_DIR = _WORKSPACE / "training"
_FT_DIR = Path(_OPS) / "ft"
_FT_LOGS = _FT_DIR / "logs"

# In-memory job state (survives process lifetime)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ── Training data counting ────────────────────────────────────────────────────

def _count_training_pairs() -> int:
    pairs_file = _TRAINING_DIR / "quality_pairs.jsonl"
    if not pairs_file.exists():
        return 0
    try:
        with pairs_file.open() as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _count_correction_pairs() -> int:
    corrections_file = _TRAINING_DIR / "corrections.jsonl"
    if not corrections_file.exists():
        return 0
    try:
        with corrections_file.open() as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _read_latest_eval_score() -> float:
    eval_dir = _FT_DIR / "eval"
    if not eval_dir.exists():
        return 1.0  # no eval yet → don't trigger
    score_files = sorted(eval_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not score_files:
        return 1.0
    try:
        with score_files[0].open() as f:
            data = json.load(f)
        return float(data.get("quality_score", data.get("score", 1.0)))
    except Exception:
        return 1.0


# ── FT job runner ──────────────────────────────────────────────────────────────

def _run_ft_job(job_id: str, config: dict):
    """Run FT pipeline in background thread."""
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

    _FT_LOGS.mkdir(parents=True, exist_ok=True)
    log_path = _FT_LOGS / f"ft_{job_id}.log"

    try:
        # Use the existing run_ft.sh script if present, else fall back to python trainer
        run_script = _FT_DIR / "run_ft.sh"
        if run_script.exists():
            cmd = ["bash", str(run_script), "--job-id", job_id]
        else:
            # Fallback: look for train.py
            train_py = _FT_DIR / "train.py"
            if not train_py.exists():
                raise FileNotFoundError(f"No FT script found in {_FT_DIR}")
            cmd = [sys.executable, str(train_py), "--job-id", job_id]

        # Add config overrides as env
        env = os.environ.copy()
        env["FT_JOB_ID"] = job_id
        env["FT_TRAINING_DIR"] = str(_TRAINING_DIR)
        env["FT_OUTPUT_DIR"] = str(_FT_DIR / "output" / f"job_{job_id}")
        if config.get("base_model"):
            env["FT_BASE_MODEL"] = config["base_model"]
        if config.get("epochs"):
            env["FT_EPOCHS"] = str(config["epochs"])

        log.info("FT job %s starting: %s", job_id, " ".join(cmd))
        with log_path.open("w") as logf:
            proc = subprocess.run(
                cmd,
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=int(os.environ.get("FT_TIMEOUT_SECONDS", "14400")),  # 4h default
            )

        if proc.returncode == 0:
            with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _jobs[job_id]["log_path"] = str(log_path)
            log.info("FT job %s completed successfully", job_id)
        else:
            with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = f"exit code {proc.returncode}"
                _jobs[job_id]["log_path"] = str(log_path)
            log.error("FT job %s failed: exit %d", job_id, proc.returncode)

    except subprocess.TimeoutExpired:
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = "timeout"
        log.error("FT job %s timed out", job_id)
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(e)
        log.exception("FT job %s error: %s", job_id, e)


# ── API models ─────────────────────────────────────────────────────────────────

class TriggerFTRequest(BaseModel):
    trigger_reason: str      # "pairs_threshold" | "eval_quality" | "corrections" | "manual"
    base_model: Optional[str] = None
    epochs: Optional[int] = None
    force: bool = False      # bypass threshold checks


class TriggerFTResponse(BaseModel):
    job_id: str
    status: str              # "queued" | "skipped" | "already_running"
    trigger_reason: str
    training_pairs: int
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str              # "queued" | "running" | "completed" | "failed"
    trigger_reason: str
    training_pairs: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    log_path: Optional[str] = None


class PromoteModelRequest(BaseModel):
    job_id: str
    model_name: str          # e.g. "omi-ft-14b-v16"
    model_path: str          # path to adapter/model
    canary_fraction: float = 0.1   # fraction of traffic to canary (10%)


# ── FT trigger endpoint ────────────────────────────────────────────────────────

@app.post("/trigger_ft", response_model=TriggerFTResponse)
async def trigger_ft(req: TriggerFTRequest, _auth: None = Depends(verify_service_token)):
    """
    Trigger a fine-tuning job. Called by LogiOrchestrator check_training_triggers().
    Checks thresholds unless force=True.
    """
    # Check if any job is already running
    with _jobs_lock:
        running = [j for j in _jobs.values() if j["status"] == "running"]
    if running:
        return TriggerFTResponse(
            job_id=running[0]["job_id"],
            status="already_running",
            trigger_reason=req.trigger_reason,
            training_pairs=_count_training_pairs(),
            message=f"FT job {running[0]['job_id']} already in progress",
        )

    pairs = _count_training_pairs()
    corrections = _count_correction_pairs()
    eval_score = _read_latest_eval_score()

    # Threshold checks (unless forced)
    if not req.force:
        if req.trigger_reason == "pairs_threshold" and pairs < 50:
            return TriggerFTResponse(
                job_id="",
                status="skipped",
                trigger_reason=req.trigger_reason,
                training_pairs=pairs,
                message=f"Skipped: only {pairs} pairs (threshold: 50)",
            )
        if req.trigger_reason == "eval_quality" and eval_score >= 0.82:
            return TriggerFTResponse(
                job_id="",
                status="skipped",
                trigger_reason=req.trigger_reason,
                training_pairs=pairs,
                message=f"Skipped: eval score {eval_score:.2f} above threshold 0.82",
            )
        if req.trigger_reason == "corrections" and corrections < 50:
            return TriggerFTResponse(
                job_id="",
                status="skipped",
                trigger_reason=req.trigger_reason,
                training_pairs=corrections,
                message=f"Skipped: only {corrections} corrections (threshold: 50)",
            )

    job_id = uuid.uuid4().hex[:12]
    config = {
        "base_model": req.base_model,
        "epochs": req.epochs,
        "trigger_reason": req.trigger_reason,
    }

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "trigger_reason": req.trigger_reason,
            "training_pairs": pairs,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }

    # Launch in background thread
    t = threading.Thread(target=_run_ft_job, args=(job_id, config), daemon=True)
    t.start()

    log.info("FT job %s queued (reason=%s, pairs=%d)", job_id, req.trigger_reason, pairs)
    return TriggerFTResponse(
        job_id=job_id,
        status="queued",
        trigger_reason=req.trigger_reason,
        training_pairs=pairs,
        message=f"FT job {job_id} queued ({pairs} training pairs)",
    )


@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def job_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobStatusResponse(**job)


@app.get("/status")
async def all_status():
    with _jobs_lock:
        return {"jobs": list(_jobs.values())}


@app.post("/promote_model")
async def promote_model(req: PromoteModelRequest, _auth: None = Depends(verify_service_token)):
    """
    Canary promotion: update inference routing to send fraction of traffic to new model.
    LogiOrchestrator calls this after reviewing FT eval results.
    """
    routing_path = Path(_OPS) / "config" / "nemoclaw_inference_routing.yaml"
    import yaml
    if not routing_path.exists():
        raise HTTPException(status_code=404, detail="inference routing config not found")

    with routing_path.open() as f:
        routing = yaml.safe_load(f)

    # Add canary rule for the new model
    canary_rule = {
        "name": f"canary_{req.model_name}",
        "trigger": "canary",
        "model": req.model_name,
        "adapter_path": req.model_path,
        "fraction": req.canary_fraction,
        "promoted_from_job": req.job_id,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }

    rules = routing.get("routing_rules", [])
    # Remove existing canary rule if present
    rules = [r for r in rules if not str(r.get("name", "")).startswith("canary_")]
    rules.append(canary_rule)
    routing["routing_rules"] = rules

    with routing_path.open("w") as f:
        yaml.dump(routing, f, default_flow_style=False)

    log.info("Model %s promoted as canary (%.0f%% traffic)", req.model_name, req.canary_fraction * 100)
    return {
        "status": "promoted",
        "model": req.model_name,
        "canary_fraction": req.canary_fraction,
        "job_id": req.job_id,
    }


@app.get("/health")
async def health():
    pairs = _count_training_pairs()
    eval_score = _read_latest_eval_score()
    with _jobs_lock:
        running_jobs = [j["job_id"] for j in _jobs.values() if j["status"] == "running"]
    return {
        "status": "ok",
        "agent": "traini_agent",
        "port": 8007,
        "training_pairs": pairs,
        "latest_eval_score": eval_score,
        "running_jobs": running_jobs,
    }


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8007)
