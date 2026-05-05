"""AIMS Anthropic-Compatible Gateway v3.

Bridges Claude Code Anthropic Messages API /v1/messages to:
- local Ollama OpenAI-compatible /v1/chat/completions
- NVIDIA NIM OpenAI-compatible /v1/chat/completions

Supports:
- model profiles
- Anthropic text blocks
- Anthropic tool_result blocks -> OpenAI tool messages
- Anthropic tools -> OpenAI tools
- OpenAI tool_calls -> Anthropic tool_use blocks

Non-streaming first. Streaming SSE can be added later if Claude Code requires it.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="AIMS Anthropic-Compatible Gateway", version="3.0")

AUTH_TOKEN = os.getenv("AIMS_CLAUDE_PROXY_TOKEN", "aims-local-repair-token")


PROFILES: dict[str, dict[str, Any]] = {
    "local-nemotron": {
        "provider": "ollama",
        "base_url": os.getenv("OLLAMA_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        "model": os.getenv("AIMS_LOCAL_MODEL", "nemotron-3-super:120b"),
        "api_key_env": None,
        "supports_tools": True,
    },
    "aims-repairman-nemotron": {
        "provider": "ollama",
        "base_url": os.getenv("OLLAMA_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        "model": os.getenv("AIMS_LOCAL_MODEL", "nemotron-3-super:120b"),
        "api_key_env": None,
        "supports_tools": True,
    },
    "llama405b": {
        "provider": "nvidia_nim",
        "base_url": os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "model": os.getenv("AIMS_NIM_LLAMA405B_MODEL", "meta/llama-3.1-405b-instruct"),
        "api_key_env": "NVIDIA_API_KEY",
        "supports_tools": True,
    },
    "minimax-m2": {
        "provider": "nvidia_nim",
        "base_url": os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "model": os.getenv("AIMS_NIM_MINIMAX_MODEL", "minimaxai/minimax-m2"),
        "api_key_env": "NVIDIA_API_KEY",
        "supports_tools": False,
    },
}

# Model fallback chain for rate limit handling
MODEL_FALLBACK_CHAIN = [
    "local-nemotron",
    "llama405b",
    "minimax-m2",
]

# Track rate limit errors per model
_rate_limit_tracker: dict[str, int] = {}


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
        "supports_tools": True,
    }


def get_next_model_in_chain(current_model: str) -> str | None:
    """Get the next model in the fallback chain after current_model.

    Returns None if current_model is the last in the chain.
    """
    try:
        current_idx = MODEL_FALLBACK_CHAIN.index(current_model)
        if current_idx < len(MODEL_FALLBACK_CHAIN) - 1:
            return MODEL_FALLBACK_CHAIN[current_idx + 1]
    except (ValueError, IndexError):
        pass
    return None


def is_rate_limit_error(status_code: int, response_text: str) -> bool:
    """Check if the error is a rate limit error."""
    if status_code == 429:
        return True
    # Check for common rate limit messages
    lower_text = response_text.lower()
    return any(phrase in lower_text for phrase in [
        "rate limit",
        "too many requests",
        "quota exceeded",
        "limit exceeded",
    ])


def anthropic_tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not tools:
        return []

    out: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name")
        if not name:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def content_blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_use":
            # If an assistant tool_use is present in history, preserve it textually.
            parts.append(json.dumps(block, ensure_ascii=False))
        elif btype == "tool_result":
            parts.append(json.dumps(block, ensure_ascii=False))
        else:
            parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(x for x in parts if x)


def anthropic_messages_to_openai(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    system = payload.get("system")
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        messages.append({"role": "system", "content": content_blocks_to_text(system)})

    # Map Anthropic tool_use ids to OpenAI tool_call ids where possible.
    for msg in payload.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            messages.append({"role": role, "content": str(content)})
            continue

        # User message may contain tool_result blocks.
        tool_results = [b for b in content if b.get("type") == "tool_result"]
        non_tool = [b for b in content if b.get("type") != "tool_result"]

        if non_tool:
            messages.append({"role": role, "content": content_blocks_to_text(non_tool)})

        for tr in tool_results:
            tool_use_id = tr.get("tool_use_id", "tool_call_unknown")
            tr_content = tr.get("content", "")
            if isinstance(tr_content, list):
                tr_text = content_blocks_to_text(tr_content)
            else:
                tr_text = str(tr_content)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_use_id,
                "content": tr_text,
            })

    return messages


def openai_tool_calls_to_anthropic(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for tc in tool_calls:
        fn = tc.get("function", {}) or {}
        name = fn.get("name")
        raw_args = fn.get("arguments", "{}")

        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {"_raw_arguments": raw_args}

        if not name:
            continue

        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", f"toolu_{name}"),
            "name": name,
            "input": args,
        })

    return blocks


def openai_to_anthropic_response(openai_data: dict[str, Any], model_alias: str, backend_model: str) -> dict[str, Any]:
    choice = openai_data.get("choices", [{}])[0]
    finish_reason = choice.get("finish_reason")
    message = choice.get("message", {}) or {}

    content_blocks: list[dict[str, Any]] = []

    text = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []

    if text and not tool_calls:
        stripped = text.strip()
        parsed = None
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None

        if isinstance(parsed, dict) and parsed.get("type") == "tool_use" and parsed.get("name"):
            content_blocks.append({
                "type": "tool_use",
                "id": parsed.get("id", f"toolu_{parsed.get('name')}"),
                "name": parsed.get("name"),
                "input": parsed.get("input", {}),
            })
            tool_calls = [{"_converted_from_text": True}]
        elif isinstance(parsed, dict) and parsed.get("name") and isinstance(parsed.get("input"), dict):
            content_blocks.append({
                "type": "tool_use",
                "id": parsed.get("id", f"toolu_{parsed.get('name')}"),
                "name": parsed.get("name"),
                "input": parsed.get("input", {}),
            })
            tool_calls = [{"_converted_from_text": True}]
        else:
            content_blocks.append({"type": "text", "text": text})

    if tool_calls:
        content_blocks.extend(openai_tool_calls_to_anthropic(tool_calls))

    if not content_blocks and message.get("reasoning"):
        content_blocks.append({"type": "text", "text": str(message.get("reasoning"))})

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    usage = openai_data.get("usage", {}) or {}

    if tool_calls:
        stop_reason = "tool_use"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "end_turn"

    return {
        "id": openai_data.get("id", "msg_local"),
        "type": "message",
        "role": "assistant",
        "model": model_alias,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
        "metadata": {
            "backend_model": backend_model,
            "finish_reason": finish_reason,
        },
    }


@app.post("/v1/messages")
async def messages(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
    check_auth(authorization)
    payload = await request.json()

    model_alias, profile = select_profile(payload.get("model"))
    original_model = model_alias

    # Try current model and fallback chain on rate limit
    max_attempts = len(MODEL_FALLBACK_CHAIN)
    attempt = 0

    while attempt < max_attempts:
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

        openai_payload: dict[str, Any] = {
            "model": backend_model,
            "messages": anthropic_messages_to_openai(payload),
            "temperature": payload.get("temperature", 0.1),
            "max_tokens": payload.get("max_tokens", 4096),
            "stream": False,
        }

        openai_tools = anthropic_tools_to_openai(payload.get("tools"))
        if openai_tools and profile.get("supports_tools", True):
            openai_payload["tools"] = openai_tools

            # Anthropic tool_choice can be "auto", {"type":"tool","name":"..."} or other structures.
            tool_choice = payload.get("tool_choice")
            if tool_choice:
                if isinstance(tool_choice, dict) and tool_choice.get("type") == "tool":
                    openai_payload["tool_choice"] = {
                        "type": "function",
                        "function": {"name": tool_choice.get("name")},
                    }
                elif isinstance(tool_choice, dict) and tool_choice.get("type") in {"auto", "any"}:
                    openai_payload["tool_choice"] = "auto"
                elif isinstance(tool_choice, str):
                    openai_payload["tool_choice"] = tool_choice

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=openai_payload,
                    headers=headers,
                )

            # Check for rate limit error
            if is_rate_limit_error(resp.status_code, resp.text):
                _rate_limit_tracker[model_alias] = _rate_limit_tracker.get(model_alias, 0) + 1

                # Try next model in chain
                next_model = get_next_model_in_chain(model_alias)
                if next_model:
                    print(f"Rate limit hit on {model_alias}, switching to {next_model}")
                    model_alias = next_model
                    _, profile = select_profile(model_alias)
                    attempt += 1
                    continue
                else:
                    # No more fallbacks
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "type": "rate_limit_error",
                                "message": f"Rate limit exceeded on all models in fallback chain. Original model: {original_model}",
                            }
                        }
                    )

            if resp.status_code >= 400:
                return JSONResponse(status_code=resp.status_code, content={"error": resp.text})

            # Success - return response with metadata about model used
            response_data = openai_to_anthropic_response(resp.json(), model_alias, backend_model)
            if model_alias != original_model:
                response_data["metadata"]["fallback_used"] = True
                response_data["metadata"]["original_model"] = original_model
                response_data["metadata"]["fallback_model"] = model_alias

            return JSONResponse(response_data)

        except httpx.TimeoutException:
            # On timeout, try next model
            next_model = get_next_model_in_chain(model_alias)
            if next_model:
                print(f"Timeout on {model_alias}, switching to {next_model}")
                model_alias = next_model
                _, profile = select_profile(model_alias)
                attempt += 1
                continue
            else:
                raise HTTPException(status_code=504, detail=f"Timeout on all models in fallback chain")

        except Exception as e:
            # On other errors, fail immediately
            raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")

    # Should not reach here
    raise HTTPException(status_code=500, detail="Fallback chain exhausted")


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": alias,
                "object": "model",
                "created": 0,
                "owned_by": profile["provider"],
                "display_name": alias,
                "metadata": {
                    "provider": profile["provider"],
                    "backend_model": profile["model"],
                    "supports_tools": bool(profile.get("supports_tools")),
                },
            }
            for alias, profile in PROFILES.items()
        ],
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8082)
