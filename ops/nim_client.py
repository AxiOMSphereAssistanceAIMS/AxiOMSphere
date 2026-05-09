"""
NIM client — единый интерфейс для NVIDIA NIM API.

Поддерживает:
  - Локальные NIM контейнеры (docker-compose сервисы на DGX)
  - Облачные NIM API (build.nvidia.com) через NVIDIA_API_KEY

Использование:
    from ops.nim_client import NIMClient

    # Локальный OCR NIM
    client = NIMClient.ocr()
    result = client.ocr_pdf(pdf_bytes)

    # Облачный teacher (Nemotron-Ultra)
    client = NIMClient.cloud_teacher()
    text = client.chat("Сгенерируй обучающий пример...")
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


# ── Конфигурация ──────────────────────────────────────────────────────────────

_CLOUD_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
_CLOUD_API_KEY  = os.environ.get("OMNIROUTE_API_KEY", "").strip()

# Локальные NIM — порты из docker-compose
_LOCAL_OCR_URL   = os.environ.get("NIM_OCR_URL",   "http://localhost:9010")
_LOCAL_RERANK_URL = os.environ.get("NIM_RERANK_URL", "http://localhost:9011")

# Облачные модели — роутятся через OmniRoute (gemini-free-fallback)
_OMNI_MODEL  = os.environ.get("OMNIROUTE_MODEL", "gemini-free-fallback")
TEACHER_MODEL    = os.environ.get("OMNIROUTE_TEACHER_MODEL", _OMNI_MODEL)
DEEPSEEK_R1_70B  = _OMNI_MODEL
NEMOTRON_NANO    = _OMNI_MODEL
QWEN3_32B        = _OMNI_MODEL
DEEPSEEK_R1_FULL = _OMNI_MODEL


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict, headers: dict | None = None,
               timeout: int = 120) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_json(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ── NIMClient ─────────────────────────────────────────────────────────────────

class NIMClient:
    """Базовый клиент. Используй фабричные методы ниже."""

    def __init__(self, base_url: str, api_key: str = "", timeout: int = 120) -> None:
        self._base = base_url.rstrip("/")
        self._key  = api_key
        self._timeout = timeout

    @property
    def _auth_headers(self) -> dict:
        if self._key:
            return {"Authorization": f"Bearer {self._key}"}
        return {}

    # ── OpenAI-compatible chat ────────────────────────────────────────────────

    def chat(
        self,
        prompt: str,
        model: str = "",
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resolved_model = model or getattr(self, "_default_model", "")
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if resolved_model:
            payload["model"] = resolved_model

        resp = _post_json(
            f"{self._base}/chat/completions",
            payload,
            headers=self._auth_headers,
            timeout=self._timeout,
        )
        return resp["choices"][0]["message"]["content"].strip()

    def chat_messages(
        self,
        messages: list[dict],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        resolved_model = model or getattr(self, "_default_model", "")
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if resolved_model:
            payload["model"] = resolved_model

        resp = _post_json(
            f"{self._base}/chat/completions",
            payload,
            headers=self._auth_headers,
            timeout=self._timeout,
        )
        return resp["choices"][0]["message"]["content"].strip()

    # ── OCR ───────────────────────────────────────────────────────────────────

    def ocr_url(self, image_url: str, timeout: int = 60) -> str:
        """OCR изображения по URL (nemoretriever-ocr-v1)."""
        payload = {"url": image_url}
        resp = _post_json(
            f"{self._base}/ocr",
            payload,
            headers=self._auth_headers,
            timeout=timeout,
        )
        return resp.get("text", "")

    def ocr_base64(self, image_b64: str, mime: str = "image/png",
                   timeout: int = 60) -> str:
        """OCR изображения из base64."""
        payload = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                }],
            }]
        }
        resp = _post_json(
            f"{self._base}/chat/completions",
            payload,
            headers=self._auth_headers,
            timeout=timeout,
        )
        return resp["choices"][0]["message"]["content"].strip()

    # ── Health check ──────────────────────────────────────────────────────────

    def health(self) -> bool:
        try:
            _get_json(f"{self._base}/health/ready",
                      headers=self._auth_headers, timeout=5)
            return True
        except Exception:
            try:
                _get_json(f"{self._base}/v1/health/ready",
                          headers=self._auth_headers, timeout=5)
                return True
            except Exception:
                return False

    # ── Фабричные методы ──────────────────────────────────────────────────────

    @classmethod
    def ocr(cls) -> "NIMClient":
        """Локальный OCR NIM контейнер."""
        return cls(_LOCAL_OCR_URL, timeout=60)

    @classmethod
    def cloud_teacher(cls, model: str = TEACHER_MODEL) -> "NIMClient":
        """OmniRoute cloud backend for teacher data generation (no key required)."""
        client = cls(_CLOUD_BASE_URL, api_key=_CLOUD_API_KEY, timeout=180)
        client._default_model = model  # type: ignore[attr-defined]
        return client

    @classmethod
    def cloud_deepseek(cls, model: str = DEEPSEEK_R1_70B) -> "NIMClient":
        """OmniRoute cloud backend (DeepSeek alias)."""
        client = cls(_CLOUD_BASE_URL, api_key=_CLOUD_API_KEY, timeout=300)
        client._default_model = model  # type: ignore[attr-defined]
        return client

    @classmethod
    def cloud_qwen3(cls, model: str = QWEN3_32B) -> "NIMClient":
        """OmniRoute cloud backend (Qwen3 alias)."""
        client = cls(_CLOUD_BASE_URL, api_key=_CLOUD_API_KEY, timeout=180)
        client._default_model = model  # type: ignore[attr-defined]
        return client

    @classmethod
    def local_qwen3(cls, port: int = 9020) -> "NIMClient":
        """Локальный Qwen3-32B NIM контейнер (только если ARM64-образ доступен)."""
        return cls(f"http://localhost:{port}/v1", timeout=120)

    @classmethod
    def local_nemotron_nano(cls) -> "NIMClient":
        """Локальный Nemotron-Nano-8B NIM контейнер (DGX, порт 9050 / сервис nim-nemotron-nano:8000)."""
        url = os.environ.get("NIM_FAST_URL", "http://nim-nemotron-nano:8000/v1")
        return cls(url, timeout=60)


# ── Синтетика через облако ────────────────────────────────────────────────────

def generate_teacher_pair(
    user_turn: str,
    system_prompt: str,
    action_hint: str,
    client: NIMClient | None = None,
) -> dict | None:
    """
    Генерирует одну обучающую пару через облачный NIM teacher.
    Возвращает {"messages": [...]} или None если ответ не валидный JSON.
    """
    if client is None:
        client = NIMClient.cloud_teacher()

    system = (
        "You are a JSON action router. Given the system instructions and a user request, "
        "output ONLY a single valid JSON object representing the correct action. "
        f"The action should be: {action_hint}. "
        "No explanation, no markdown, no extra text."
    )

    try:
        asst = client.chat(
            prompt=user_turn,
            system=system,
            temperature=0.1,
            max_tokens=512,
        )
        json.loads(asst)  # проверка валидности
    except (urllib.error.URLError, KeyError, json.JSONDecodeError):
        return None

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_turn})
    messages.append({"role": "assistant", "content": asst})

    return {"messages": messages}
