"""
logi_llm_chat.py

Real LLM calls for Logi's conversational path. Direct SLOT32 SGLang endpoint
(same one ops.agents.logi_queue_poller uses) — no shell, read-only network I/O.

Before this module existed, the conversational fallback (_build_plain_reply in
conversational_orchestrator.py) returned canned strings ("Принял. Работаю по
контексту.") with no model call at all, even when a large grounding prompt had
been built. This module is what actually reaches SLOT32.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

SLOT32_MODEL = os.environ.get("AIMS_SLOT32_MODEL", "aims_slot32_qwen3_coder_next_fp8_v0")
SLOT32_PROXY_TOKEN = os.environ.get("SLOT32_PROXY_API_KEY", "aims-local-repair-token")

# Callers may run on the host (network_mode: host, 127.0.0.1 reaches SGLang
# directly) or inside a bridge-networked container (127.0.0.1 is the
# container itself; only the proxy's host-published port is reachable, via
# the bridge gateway). Try candidates in order; first that answers wins.
_DIRECT_CANDIDATES = [
    (os.environ.get("AIMS_SLOT32_OPENAI_URL", ""), None),
    ("http://127.0.0.1:18081/v1", None),
    ("http://172.18.0.1:8084/v1", SLOT32_PROXY_TOKEN),
    ("http://host.docker.internal:8084/v1", SLOT32_PROXY_TOKEN),
]

CANNED_FALLBACKS = {
    "Принял. Работаю.",
    "Принял. Работаю по контексту.",
    "Да. Разберу вопрос и отвечу кратко.",
    "Да. Разберу вопрос по контексту и отвечу кратко.",
}


class Slot32Unavailable(RuntimeError):
    pass


def _post_chat(url: str, token: str | None, prompt: str, max_tokens: int,
               temperature: float, timeout: int) -> str:
    body = json.dumps({
        "model": SLOT32_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions", data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


def slot32_chat(prompt: str, max_tokens: int = 700, temperature: float = 0.3,
                timeout: int = 300) -> str:
    """Send a single-turn prompt to SLOT32 and return the model's text reply.

    Tries each reachable-endpoint candidate in order (direct host path first,
    proxy bridge path as fallback for containerized callers). Raises
    Slot32Unavailable only once every candidate has failed, so callers can
    degrade to a canned reply instead of crashing the bot.
    """
    errors = []
    for url, token in _DIRECT_CANDIDATES:
        if not url:
            continue
        try:
            return _post_chat(url, token, prompt, max_tokens, temperature, timeout)
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as e:
            errors.append(f"{url}: {e}")
            continue
    raise Slot32Unavailable("; ".join(errors)[:400] or "no candidates configured")


def build_chat_context_prompt(text: str, history: list[str], skill_context: str = "",
                              recent_case: dict | None = None) -> str:
    """Compose a grounded chat prompt: recent conversation + latest closed-loop
    case (if any) + strategy skill context. Kept small — this is a chat reply,
    not a full engineering-review grounding prompt."""
    parts = [
        "Ты — Logi, оркестратор инженерной команды AIMS. Отвечай по-русски, "
        "кратко и по существу, используя фактический контекст ниже. "
        "Если в вопросе просят объяснить/описать что-то из недавнего кейса — "
        "отвечай по данным кейса, а не общими словами.",
    ]
    if history:
        parts.append("ПОСЛЕДНИЕ СООБЩЕНИЯ ДИАЛОГА:\n" + "\n".join(f"- {h}" for h in history[-5:]))
    if recent_case:
        parts.append(
            "ПОСЛЕДНИЙ РАЗОБРАННЫЙ КЕЙС (полный отчёт ниже):\n"
            f"название: {recent_case.get('title', '')}\n"
            f"источник: {recent_case.get('source', '')}\n"
            f"итог: {recent_case.get('outcome', '')}\n"
            f"{recent_case.get('human_report_ru', '')}"
        )
    if skill_context:
        parts.append(f"ДОП. КОНТЕКСТ СТРАТЕГИИ:\n{skill_context[:1500]}")
    parts.append(f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{text[:2000]}")
    return "\n\n".join(parts)
