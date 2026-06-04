"""AIMS Anthropic-Compatible Gateway.

Bridges Claude Code Anthropic Messages API /v1/messages to:
- local Ollama OpenAI-compatible /v1/chat/completions
- NVIDIA NIM OpenAI-compatible /v1/chat/completions

Supported Claude Code model aliases:
- local-nemotron
- aims-repairman-nemotron
- llama405b
- deepseek-v3.2
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="AIMS Anthropic-Compatible Gateway", version="2.0")

AUTH_TOKEN = os.getenv("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")

PROFILES: dict[str, dict[str, Any]] = {
    "local-nemotron": {
        "provider": "ollama",
        "base_url": os.getenv("OLLAMA_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        "model": os.getenv("AIMS_LOCAL_MODEL", "nemotron-3-super:120b"),
        "api_key_env": None,
    },
    "aims-repairman-nemotron": {
        "provider": "ollama",
        "base_url": os.getenv("OLLAMA_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        "model": os.getenv("AIMS_LOCAL_MODEL", "nemotron-3-super:120b"),
        "api_key_env": None,
    },
    "llama405b": {
        "provider": "nvidia_nim",
        "base_url": os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "model": os.getenv("AIMS_NIM_LLAMA405B_MODEL", "meta/llama-3.1-405b-instruct"),
        "api_key_env": "NVIDIA_API_KEY",
    },
    "deepseek-v3.2": {
        "provider": "nvidia_nim",
        "base_url": os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "model": os.getenv("AIMS_NIM_DEEPSEEK_MODEL", "deepseek-ai/deepseek-v3.2"),
        "api_key_env": "NVIDIA_API_KEY",
    },
}


def check_auth(authorization: str | None) -> None:
    if authorization != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def select_profile(requested_model: str | None) -> tuple[str, dict[str, Any]]:
    alias = requested_model or os.getenv("AIMS_MODEL_PROFILE", "local-nemotron")
    if alias in PROFILES:
        return alias, PROFILES[alias]

    return alias, {
        "provider": "ollama",
        "base_url": os.getenv("OLLAMA_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        "model": alias,
        "api_key_env": None,
    }


def to_openai_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    system = payload.get("system")
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system})

    for msg in payload.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            content = "\n".join(parts)

        messages.append({"role": role, "content": str(content)})

    return messages


def to_anthropic_response(openai_data: dict[str, Any], model_alias: str, backend_model: str) -> dict[str, Any]:
    choice = openai_data.get("choices", [{}])[0]
    message = choice.get("message", {})
    text = message.get("content", "")

    if not text and message.get("reasoning"):
        text = message.get("reasoning", "")

    usage = openai_data.get("usage", {})
    return {
        "id": openai_data.get("id", "msg_local"),
        "type": "message",
        "role": "assistant",
        "model": model_alias,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
        "metadata": {
            "backend_model": backend_model,
        },
    }


@app.post("/v1/messages")
async def messages(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
    check_auth(authorization)
    payload = await request.json()

    model_alias, profile = select_profile(payload.get("model"))
    backend_model = profile["model"]
    base_url = profile["base_url"].rstrip("/")
    api_key_env = profile.get("api_key_env")

    headers = {"Content-Type": "application/json"}
    if api_key_env:
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise HTTPException(status_code=500, detail=f"Missing required environment variable: {api_key_env}")
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = "Bearer ollama"

    openai_payload = {
        "model": backend_model,
        "messages": to_openai_messages(payload),
        "temperature": payload.get("temperature", 0.1),
        "max_tokens": payload.get("max_tokens", 4096),
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            json=openai_payload,
            headers=headers,
        )

    if resp.status_code >= 400:
        return JSONResponse(status_code=resp.status_code, content={"error": resp.text})

    return JSONResponse(to_anthropic_response(resp.json(), model_alias, backend_model))


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "profiles": {
            alias: {
                "provider": p["provider"],
                "base_url": p["base_url"],
                "model": p["model"],
                "requires_api_key": bool(p.get("api_key_env")),
                "api_key_env": p.get("api_key_env"),
            }
            for alias, p in PROFILES.items()
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8082)
