"""ArgusAgent — health metrics collector for AIMS V2.

Monitors key Docker containers, Ollama availability, and task queue depth.
Recalculates health score every 60 seconds in the background.
Emits health events to LogiOrchestrator when score drops below 70.
Port: 8006. No authentication — internal service only.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow imports from parent ops/ directory
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

import httpx
import uvicorn
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from core.service_auth import verify_service_token

log = logging.getLogger("aims.argus_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# ── configuration ──────────────────────────────────────────────────────────────

WATCHED_CONTAINERS = [
    "axiomsphere-omi-api",
    "axiomsphere-axi-bot",
    "axiomsphere-qdrant",
    "axiomsphere-task-registry",
]

OLLAMA_URL = "http://localhost:11434/api/tags"
LOGI_HEALTH_EVENT_URL = "http://localhost:8000/health_event"
HEALTH_LOW_THRESHOLD = 70
REFRESH_INTERVAL_SECONDS = 60

app = FastAPI(title="ArgusAgent", version="2.0.0")

# ── shared state (updated by background task) ──────────────────────────────────

_state: dict[str, Any] = {
    "health_score": 100,
    "services": {},
    "timestamp": datetime.now(timezone.utc).isoformat(),
}


# ── checks ─────────────────────────────────────────────────────────────────────

def _check_containers() -> dict[str, str]:
    """Run 'docker ps' and return {container_name: "up" | "down"} for watched containers."""
    statuses: dict[str, str] = {c: "down" for c in WATCHED_CONTAINERS}
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        running = set(result.stdout.strip().splitlines())
        for name in WATCHED_CONTAINERS:
            statuses[name] = "up" if name in running else "down"
    except Exception as exc:
        log.warning("docker ps failed: %s", exc)
    return statuses


async def _check_ollama() -> str:
    """Return "reachable" or "unreachable"."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(OLLAMA_URL)
            return "reachable" if resp.status_code == 200 else "unreachable"
    except Exception:
        return "unreachable"


async def _check_task_queue() -> int:
    """Return total task queue depth: pending + processing (0 if unavailable)."""
    try:
        import redis.asyncio as aioredis  # type: ignore
        r = aioredis.Redis(host="aims-redis", port=6379, decode_responses=True)
        pending = await r.llen("queue:pending")
        processing = await r.llen("queue:processing")
        await r.aclose()
        return int(pending + processing)
    except Exception:
        return 0


def _compute_score(container_statuses: dict[str, str], ollama: str, queue_depth: int) -> int:
    """Compute a 0-100 health score.

    Weights:
    - Each container: 15 points (4 containers = 60 pts total)
    - Ollama reachable: 30 points
    - Queue depth < 100: 10 points
    """
    score = 0

    # Containers: 15 pts each, up to 60
    up_count = sum(1 for s in container_statuses.values() if s == "up")
    score += up_count * 15

    # Ollama
    if ollama == "reachable":
        score += 30

    # Queue depth
    if queue_depth < 100:
        score += 10

    return min(score, 100)


async def _emit_health_event(score: int, services: dict[str, Any]) -> None:
    """Notify LogiOrchestrator when health score drops below threshold."""
    payload = {
        "source": "argus_agent",
        "health_score": score,
        "services": services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "WARNING" if score >= 50 else "CRITICAL",
        "type": "low_health_score",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(LOGI_HEALTH_EVENT_URL, json=payload)
            log.info("health event emitted, logi responded %d", resp.status_code)
    except Exception as exc:
        log.warning("failed to emit health event: %s", exc)


async def _refresh_loop() -> None:
    """Background coroutine — refreshes health state every REFRESH_INTERVAL_SECONDS."""
    global _state
    while True:
        try:
            container_statuses = _check_containers()
            ollama_status = await _check_ollama()
            queue_depth = await _check_task_queue()
            score = _compute_score(container_statuses, ollama_status, queue_depth)

            services: dict[str, Any] = {
                **container_statuses,
                "ollama": ollama_status,
                "task_queue_depth": queue_depth,
            }
            ts = datetime.now(timezone.utc).isoformat()

            _state = {
                "health_score": score,
                "services": services,
                "timestamp": ts,
            }

            log.info("health_score=%d ollama=%s queue_depth=%d", score, ollama_status, queue_depth)

            if score < HEALTH_LOW_THRESHOLD:
                log.warning("health score below threshold (%d < %d), emitting event", score, HEALTH_LOW_THRESHOLD)
                await _emit_health_event(score, services)

        except Exception as exc:
            log.exception("error in health refresh loop: %s", exc)

        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)


# ── FastAPI lifecycle ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(_refresh_loop())
    log.info("ArgusAgent started — background health refresh every %ds", REFRESH_INTERVAL_SECONDS)


# ── endpoints ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    health_score: int
    services: dict
    timestamp: str


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return the latest cached health snapshot."""
    return HealthResponse(status="ok", **_state)


@app.post("/refresh")
async def force_refresh(_auth: None = Depends(verify_service_token)) -> dict:
    """Trigger an immediate health recalculation (bypass the 60-second interval)."""
    container_statuses = _check_containers()
    ollama_status = await _check_ollama()
    queue_depth = await _check_task_queue()
    score = _compute_score(container_statuses, ollama_status, queue_depth)
    services: dict[str, Any] = {
        **container_statuses,
        "ollama": ollama_status,
        "task_queue_depth": queue_depth,
    }
    ts = datetime.now(timezone.utc).isoformat()
    global _state
    _state = {"health_score": score, "services": services, "timestamp": ts}
    return _state


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "argus_agent:app",
        host="0.0.0.0",
        port=8006,
        log_level="info",
        reload=False,
    )
