import logging
import os
import time
from typing import Any, Dict, Optional

import requests

log = logging.getLogger("aims.model_router")

# Default models — match the live AIMS stack
_DEFAULT_LOCAL_MODEL = os.getenv("AIMS_LOCAL_MODEL", "qwen3:32b-q8_0")
_DEFAULT_NIM_MODEL   = "meta/llama-3.1-405b-instruct"
_DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"


# =========================================================
# BASE INTERFACE
# =========================================================

class BaseModelClient:
    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError


# =========================================================
# LOCAL MODEL — Ollama-compatible API
# =========================================================

class LocalModelClient(BaseModelClient):
    def __init__(self):
        self.url = (
            os.getenv("OLLAMA_LOCAL_URL")
            or os.getenv("LOCAL_MODEL_URL")
            or "http://localhost:11434"
        ).rstrip("/")
        self.model = _DEFAULT_LOCAL_MODEL

    def generate(self, prompt: str, **kwargs) -> str:
        model = kwargs.get("model") or self.model
        r = requests.post(
            f"{self.url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "temperature": kwargs.get("temperature", 0.3),
                    "num_predict": kwargs.get("max_tokens", 512),
                },
            },
            timeout=kwargs.get("timeout", 120),
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


# =========================================================
# NVIDIA NIM
# =========================================================

class NIMClient(BaseModelClient):
    def __init__(self):
        self.api_key  = os.getenv("NVIDIA_API_KEY", "")
        self.base_url = "https://integrate.api.nvidia.com/v1"

    def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            return "nim_unavailable: NVIDIA_API_KEY not configured"

        model = kwargs.get("model") or _DEFAULT_NIM_MODEL
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": kwargs.get("temperature", 0.3),
                "max_tokens": kwargs.get("max_tokens", 1024),
            },
            timeout=kwargs.get("timeout", 60),
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# =========================================================
# CLAUDE (Anthropic)
# =========================================================

class ClaudeClient(BaseModelClient):
    def __init__(self):
        self.api_key  = os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com").rstrip("/")

    def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            return "claude_unavailable: ANTHROPIC_API_KEY not configured"

        model = kwargs.get("model") or _DEFAULT_CLAUDE_MODEL
        r = requests.post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": kwargs.get("max_tokens", 1024),
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=kwargs.get("timeout", 60),
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


# =========================================================
# RETRY HELPER
# =========================================================

def _safe_request(fn, retries: int = 2, delay: float = 1.5):
    last_err = None
    for i in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(delay * (i + 1))
    raise last_err


# =========================================================
# RETRY-WRAPPED CLIENTS
# — use explicit class names instead of super() so that
#   lambdas capture the right binding
# =========================================================

class SafeLocalModelClient(LocalModelClient):
    def generate(self, prompt: str, **kwargs) -> str:
        _self = self
        return _safe_request(
            lambda: LocalModelClient.generate(_self, prompt, **kwargs)
        )


class SafeNIMClient(NIMClient):
    def generate(self, prompt: str, **kwargs) -> str:
        # Skip retry for nim_unavailable — it will always return the same signal
        if not self.api_key:
            return "nim_unavailable: NVIDIA_API_KEY not configured"
        _self = self
        return _safe_request(
            lambda: NIMClient.generate(_self, prompt, **kwargs)
        )


class SafeClaudeClient(ClaudeClient):
    def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            return "claude_unavailable: ANTHROPIC_API_KEY not configured"
        _self = self
        return _safe_request(
            lambda: ClaudeClient.generate(_self, prompt, **kwargs)
        )


# =========================================================
# MODEL ROUTER
# =========================================================

class ModelRouter:
    def __init__(self):
        self.clients: Dict[str, BaseModelClient] = {
            "local":  SafeLocalModelClient(),
            "nim":    SafeNIMClient(),
            "claude": SafeClaudeClient(),
        }

        # task_type → preferred provider
        self.task_map: Dict[str, str] = {
            "cheap":     "local",
            "bulk":      "local",
            "ocr":       "local",
            "reasoning": "nim",
            "analysis":  "nim",
            "repair":    "claude",
            "debug":     "claude",
        }

        # primary → fallback (claude falls back to nim, not local — needs reasoning)
        self.fallbacks: Dict[str, str] = {
            "nim":    "local",
            "local":  "nim",
            "claude": "nim",
        }

    # -------------------------------------------------
    def get_client(self, task_type: str) -> BaseModelClient:
        provider = self.task_map.get(task_type, "nim")
        return self.clients[provider]

    # -------------------------------------------------
    def generate(
        self,
        task_type: str,
        prompt: str,
        model: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        provider = self.task_map.get(task_type, "nim")
        client   = self.clients.get(provider)

        if not client:
            return {"success": False, "error": f"No client for provider '{provider}'"}

        start = time.time()

        try:
            result = client.generate(prompt, model=model, **kwargs)
            return {
                "success":  True,
                "result":   result,
                "provider": provider,
                "latency":  round(time.time() - start, 3),
            }

        except Exception as primary_err:
            log.warning("ModelRouter: %s failed (%s) — trying fallback", provider, primary_err)
            fallback_provider = self.fallbacks.get(provider)

            if not fallback_provider:
                return {
                    "success":  False,
                    "error":    str(primary_err),
                    "provider": provider,
                }

            fallback_client = self.clients.get(fallback_provider)

            try:
                result = fallback_client.generate(prompt, **kwargs)
                log.info("ModelRouter: fallback %s succeeded", fallback_provider)
                return {
                    "success":         True,
                    "result":          result,
                    "fallback":        True,
                    "provider":        fallback_provider,
                    "primary_error":   str(primary_err),
                    "latency":         round(time.time() - start, 3),
                }

            except Exception as fallback_err:
                return {
                    "success": False,
                    "error":   f"{provider}: {primary_err} | fallback {fallback_provider}: {fallback_err}",
                }


# =========================================================
# DEBUG
# =========================================================

def test_router():
    router = ModelRouter()
    resp = router.generate(task_type="cheap", prompt="Hello, world")
    print(resp)


if __name__ == "__main__":
    test_router()
