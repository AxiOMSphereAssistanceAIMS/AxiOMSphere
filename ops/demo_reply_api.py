"""
Demo Reply API — FastAPI service on port 8020.

Receives Mini App callbacks from the Telegram Web App Reply transport,
validates initData (HMAC-SHA256), and routes confirmed replies to axi_demo.

Security model:
  - Bot token is never sent to the frontend; lives only in server env.
  - initData is validated using HMAC-SHA256 before any action is taken.
  - query_id and user.id are extracted server-side from validated initData only.
  - Answer text is selected server-side from the _pending_replies registry.
  - Tokens are single-use and expire after _REPLY_TOKEN_TTL seconds.
  - Only one token per session is ever active; out-of-order calls are rejected.
  - Token is consumed only after all identity and availability checks pass.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

_WEBAPP_HTML = Path(__file__).parent / "demo_webapp" / "index.html"

log = logging.getLogger(__name__)

_BOT_TOKEN: str = os.environ.get("AXI_BOT_TOKEN", "")


# ── initData validation ────────────────────────────────────────────────────────

def _parse_validated_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Validate Telegram Web App initData per the official spec and return parsed fields.

    Returns a dict of the verified fields (hash excluded) on success, or None on any
    validation failure.

      secret_key = HMAC-SHA256("WebAppData", bot_token)
      check_hash = HMAC-SHA256(data_check_string, secret_key)
    where data_check_string is the sorted key=value pairs joined by newlines,
    with the 'hash' field excluded.
    """
    if not bot_token:
        log.warning("demo_reply_api: AXI_BOT_TOKEN not set — initData validation impossible")
        return None

    try:
        params = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = params.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(params.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()

        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            return None

        return params

    except Exception as exc:
        log.warning("demo_reply_api: initData parse error: %s", exc)
        return None


# ── FastAPI app ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI):
    log.info("demo_reply_api: started on port 8020")
    yield
    log.info("demo_reply_api: stopped")


app = FastAPI(
    title="AxiOMSphere Demo Reply API",
    lifespan=_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class ReplyRequest(BaseModel):
    token: str
    init_data: str


@app.get("/demo/webapp/index.html", response_class=HTMLResponse)
async def webapp_html():
    if not _WEBAPP_HTML.exists():
        raise HTTPException(status_code=404, detail="Mini App page not found")
    return HTMLResponse(content=_WEBAPP_HTML.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "demo_reply_api"}


@app.post("/demo/reply")
async def demo_reply(body: ReplyRequest):
    parsed = _parse_validated_init_data(body.init_data, _BOT_TOKEN)
    if parsed is None:
        raise HTTPException(status_code=403, detail="initData validation failed")

    query_id = parsed.get("query_id")
    if not query_id:
        raise HTTPException(status_code=403, detail="query_id absent from signed initData")

    user_json = parsed.get("user")
    if not user_json:
        raise HTTPException(status_code=403, detail="user absent from signed initData")
    try:
        user_data = json.loads(user_json)
        user_id = int(user_data["id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        raise HTTPException(status_code=403, detail="user.id absent from signed initData")

    # Import here to avoid circular dependency at module load time
    from axi_demo import handle_webapp_reply

    ok = await handle_webapp_reply(body.token, query_id, user_id)
    if not ok:
        raise HTTPException(status_code=400, detail="token unknown, expired, or reply already consumed")

    return JSONResponse({"status": "ok"})


# ── Entry point for direct run ─────────────────────────────────────────────────

def start_demo_reply_api(host: str = "0.0.0.0", port: int = 8020) -> None:
    """Start the server in an already-running asyncio event loop (via uvicorn).

    Binds to 0.0.0.0 so Docker's port mapping can forward traffic.
    Host-side exposure is restricted to 127.0.0.1 by the compose ports mapping:
      127.0.0.1:8020:8020
    """
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    import asyncio
    asyncio.ensure_future(server.serve())
    log.info("demo_reply_api: scheduled on %s:%s", host, port)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8020)
