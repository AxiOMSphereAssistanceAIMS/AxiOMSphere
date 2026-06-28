#!/usr/bin/env python3
import asyncio
import json
import os
import uuid
import urllib.error
import urllib.request
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

AUTH_TOKEN = os.environ.get("SLOT32_PROXY_API_KEY", "aims-local-repair-token")
OLLAMA_URL = os.environ.get("SLOT32_PROXY_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.environ.get("SLOT32_PROXY_MODEL", "axi_omi_sphere:latest")
UPSTREAM_TIMEOUT_S = int(os.environ.get("SLOT32_PROXY_UPSTREAM_TIMEOUT_S", "240"))
MAX_OUTPUT_TOKENS = int(os.environ.get("SLOT32_MAX_OUTPUT_TOKENS", "512"))
MAX_REQUEST_CHARS = int(os.environ.get("SLOT32_MAX_REQUEST_CHARS", "300000"))
LOCK_WAIT_TIMEOUT_S = int(os.environ.get("SLOT32_LOCK_WAIT_TIMEOUT_S", "240"))

app = FastAPI()
OLLAMA_LOCK = asyncio.Lock()

def clean_text(text: str) -> str:
    if not text:
        return ""
    for token in ["<|endoftext|>", "<|im_start|>", "<|im_end|>"]:
        text = text.replace(token, "")
    return text.strip()

def authorized(authorization: str, x_api_key: str) -> bool:
    return authorization == f"Bearer {AUTH_TOKEN}" or x_api_key == AUTH_TOKEN

def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif "text" in item:
                    parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content)

def anthropic_to_ollama_messages(body: dict):
    messages = []

    system = body.get("system")
    if system:
        if isinstance(system, str):
            messages.append({"role": "system", "content": system})
        else:
            messages.append({"role": "system", "content": extract_text(system)})

    for m in body.get("messages", []):
        role = m.get("role", "user")
        if role not in ("user", "assistant", "system"):
            role = "user"
        messages.append({
            "role": role,
            "content": extract_text(m.get("content", ""))
        })

    return messages


def post_ollama_chat(payload: dict, timeout_s: int) -> dict:
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[-1000:]}") from exc
    return json.loads(raw)

@app.head("/")
async def head_root():
    return {}

@app.get("/health")
async def health():
    return {
        "ok": True,
        "model": MODEL,
        "backend": "ollama_native_api_chat",
        "think": False,
        "single_flight": True,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "max_request_chars": MAX_REQUEST_CHARS,
        "lock_wait_timeout_s": LOCK_WAIT_TIMEOUT_S,
        "upstream_timeout_s": UPSTREAM_TIMEOUT_S
    }

@app.post("/v1/messages/count_tokens")
async def count_tokens(
    request: Request,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default="", alias="x-api-key"),
):
    if not authorized(authorization, x_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    text = "\n".join(extract_text(m.get("content", "")) for m in body.get("messages", []))
    return {"input_tokens": max(1, len(text) // 4)}

@app.post("/v1/messages")
async def messages(
    request: Request,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default="", alias="x-api-key"),
):
    if not authorized(authorization, x_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")

    body_raw = await request.body()
    request_chars = len(body_raw)
    if request_chars > MAX_REQUEST_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"slot32 request too large: {request_chars} chars > {MAX_REQUEST_CHARS}; use narrower context"
        )

    body = json.loads(body_raw.decode("utf-8"))

    requested_max_tokens = int(body.get("max_tokens", 1024))
    max_tokens = min(requested_max_tokens, MAX_OUTPUT_TOKENS)
    temperature = float(body.get("temperature", 0))

    payload = {
        "model": MODEL,
        "think": False,
        "stream": False,
        "keep_alive": "2h",
        "messages": anthropic_to_ollama_messages(body),
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        }
    }

    lock_acquired = False
    try:
        await asyncio.wait_for(OLLAMA_LOCK.acquire(), timeout=LOCK_WAIT_TIMEOUT_S)
        lock_acquired = True
        data = await asyncio.to_thread(post_ollama_chat, payload, UPSTREAM_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=429,
            detail=f"slot32 busy: another request is running; retry later"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama upstream error: {e}")
    finally:
        if lock_acquired:
            OLLAMA_LOCK.release()

    text = clean_text(data.get("message", {}).get("content", ""))

    return JSONResponse({
        "id": "msg_" + uuid.uuid4().hex[:24],
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": data.get("prompt_eval_count", 0),
            "output_tokens": data.get("eval_count", 0)
        },
        "metadata": {
            "backend": "ollama_native_api_chat",
            "think": False,
            "single_flight": True,
            "request_chars": request_chars,
            "requested_max_tokens": requested_max_tokens,
            "capped_max_tokens": max_tokens,
            "max_request_chars": MAX_REQUEST_CHARS,
            "lock_wait_timeout_s": LOCK_WAIT_TIMEOUT_S,
            "upstream_timeout_s": UPSTREAM_TIMEOUT_S
        }
    })

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8084)
