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

SLOT32_URL = os.environ.get("AIMS_SLOT32_OPENAI_URL", "http://127.0.0.1:18081/v1")
SLOT32_MODEL = os.environ.get("AIMS_SLOT32_MODEL", "aims_slot32_qwen3_coder_next_fp8_v0")

CANNED_FALLBACKS = {
    "Принял. Работаю.",
    "Принял. Работаю по контексту.",
    "Да. Разберу вопрос и отвечу кратко.",
    "Да. Разберу вопрос по контексту и отвечу кратко.",
}


class Slot32Unavailable(RuntimeError):
    pass


def slot32_chat(prompt: str, max_tokens: int = 700, temperature: float = 0.3,
                timeout: int = 300) -> str:
    """Send a single-turn prompt to SLOT32 and return the model's text reply.

    Raises Slot32Unavailable on any network/parse failure so callers can
    degrade to a canned reply instead of crashing the bot.
    """
    body = json.dumps({
        "model": SLOT32_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        SLOT32_URL.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as e:
        raise Slot32Unavailable(str(e)[:300]) from e


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
            "ПОСЛЕДНИЙ РАЗОБРАННЫЙ КЕЙС:\n"
            f"название: {recent_case.get('title', '')}\n"
            f"источник: {recent_case.get('source', '')}\n"
            f"итог: {recent_case.get('outcome', '')}\n"
            f"суть: {recent_case.get('problem_summary_ru', '')}\n"
            f"разбор: {recent_case.get('human_report_ru', '')}\n"
            f"гипотеза первопричины: {recent_case.get('root_cause_hypothesis', '')}"
        )
    if skill_context:
        parts.append(f"ДОП. КОНТЕКСТ СТРАТЕГИИ:\n{skill_context[:1500]}")
    parts.append(f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{text[:2000]}")
    return "\n\n".join(parts)
