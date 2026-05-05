"""KnomiAgent — FastAPI wrapper around the Knomi knowledge search index.

Exposes search and reindex endpoints for internal use by LogiOrchestrator.
Port: 8002. No authentication — internal service only.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Allow imports from parent ops/ directory
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

# Allow knomi/ package imports (search.py uses `from common import ...`)
_knomi_dir = _ops_dir / "knomi"
if str(_knomi_dir) not in sys.path:
    sys.path.insert(0, str(_knomi_dir))

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.service_auth import verify_service_token
from knomi.search import search as knomi_search_fn
from knomi.indexer import rebuild_index

log = logging.getLogger("aims.knomi_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(title="KnomiAgent", version="2.0.0")


# ── request / response models ──────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=20, ge=1, le=200)


class SearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[dict]


class ReindexResponse(BaseModel):
    ok: bool
    indexed: int
    detail: str


# ── endpoints ──────────────────────────────────────────────────────────────────

@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    """Search the Knomi knowledge index.

    Returns raw results — filtering is LogiOrchestrator's responsibility.
    """
    log.info("search query=%r top_k=%d", req.query, req.top_k)
    try:
        results = knomi_search_fn(req.query, top_k=req.top_k)
    except Exception as exc:
        log.exception("search failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"search error: {exc}") from exc
    log.info("search returned %d results", len(results))
    return SearchResponse(query=req.query, top_k=req.top_k, results=results)


@app.post("/reindex", response_model=ReindexResponse)
def reindex(_auth: None = Depends(verify_service_token)) -> ReindexResponse:
    """Trigger re-indexing of new master documents into the knowledge index."""
    log.info("reindex requested")
    try:
        count = rebuild_index()
    except Exception as exc:
        log.exception("reindex failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"reindex error: {exc}") from exc
    log.info("reindex complete, indexed=%d", count)
    return ReindexResponse(ok=True, indexed=count, detail=f"indexed {count} chunks")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "knomi_agent", "port": 8002}


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "knomi_agent:app",
        host="0.0.0.0",
        port=8002,
        log_level="info",
        reload=False,
    )
