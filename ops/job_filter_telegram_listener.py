"""
job_filter_telegram_listener.py

Gives the JobLocator Telegram bot a chat-driven way to change its own
search-filter configuration, without ever editing code from a chat message.

Flow (per the "no hallucinations, confirmed by Logi as orchestrator" contract):

  1. User sends /tune <free text request>.
  2. A local LLM (configurable model/slot — JOB_FILTER_TUNE_LLM_MODEL, e.g.
     point it at the long-context SLOT14 runtime) parses the request into ONE
     of a small, fixed set of supported actions (see _SUPPORTED_ACTIONS). If
     it can't confidently map the request onto one of those actions, the bot
     asks a clarifying question instead of guessing.
  3. The bot echoes back its plain-language understanding and asks the user
     to confirm with /confirm <id> — this is the hallucination guard: nothing
     happens until the user has read back what the bot understood and agreed
     it's right.
  4. /confirm moves the request from pending -> confirmed. This is NOT
     execution. A confirmed request is a task for a Logi-orchestrated
     fullstack session to actually implement in code, test, and deploy —
     exactly the loop this repo has used all night for real filter fixes.
  5. Only once a human/Logi session calls
     job_filter_change_request.mark_completed(request_id, evidence=...) does
     the bot report the change as done. JobLocator itself never claims a
     change landed — it can only report queued/confirmed/completed states
     that this module's own storage actually reflects.

/skills reads the bot's own live filter configuration (introspection).
/tasks lists its own pending/confirmed/completed change requests (planning).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

_OPS_DIR = str(Path(__file__).resolve().parent)
if _OPS_DIR not in sys.path:
    sys.path.insert(0, _OPS_DIR)

from agents import job_filter_change_request as jfcr  # noqa: E402
from job_filter import JobFilterConfig  # noqa: E402

log = logging.getLogger("job_filter_telegram_listener")

# Fixed action vocabulary the LLM parser is constrained to. Anything that
# doesn't map cleanly onto one of these becomes a clarifying question
# instead of a guessed action — this is what "no hallucinations" means in
# practice: the model cannot invent a new action type or free-form code edit.
_SUPPORTED_ACTIONS = {
    "add_title_exclusion": "STOP SHOWING postings whose TITLE contains a given word/phrase — use this when the user wants fewer/no results of some kind (\"remove X from my results\", \"don't show me X\", \"уберите X из поиска\", \"исключи X\").",
    "remove_title_exclusion": "START SHOWING title-matched postings again — use this ONLY when the user wants to undo an existing filter and see MORE results (\"stop excluding X\", \"верни X в поиск\", \"не исключай больше X\").",
    "add_hard_exclusion": "Same as add_title_exclusion but matches title+description anywhere, not just the title.",
    "remove_hard_exclusion": "Same as remove_title_exclusion but for a hard (title+description) exclusion.",
    "set_draft_min_ats_percent": "Change the minimum resume-match percentage required before a Gmail draft is created.",
    "set_draft_min_opportunity_score": "Change the minimum opportunity score required before a Gmail draft is created.",
}

_SYSTEM_PROMPT = f"""You parse a free-text request (Russian or English) about changing a job-search bot's filters into STRICT JSON. You may ONLY use these actions, nothing else:

{json.dumps(_SUPPORTED_ACTIONS, indent=2, ensure_ascii=False)}

CRITICAL — direction of the action is about the RESULT the user wants, not
which words appear in their sentence: if the user wants to see FEWER
postings of some kind (excluding/filtering out/removing something FROM THE
RESULTS), that is an add_*_exclusion action, even if their sentence uses the
word "remove" or "убери" — they mean "remove these jobs from what I see",
not "remove an existing filter". Only use a remove_*_exclusion action when
the user explicitly wants an existing filter undone so MORE postings show up.

"target" must be a short, normalized keyword or short phrase suitable for
substring matching against a job title/description (lowercase, no filler
words) — not a verbatim quote of the user's sentence. E.g. for "чистый
электрик" the target is "electrical", not "чистый электрик".

Respond with ONLY a JSON object, no other text, matching exactly one of these two shapes:

Confident match:
{{"confident": true, "action": "<one of the action names above>", "target": "<normalized keyword/phrase or numeric value>", "understood_summary": "<one plain-language sentence in the SAME language as the request, restating what you understood, phrased as its concrete effect on search results — e.g. 'postings with electrical in the title will stop being shown'>"}}

Not confident / doesn't map to a supported action:
{{"confident": false, "clarifying_question": "<one short question, in the SAME language as the request, asking exactly what's missing to proceed>"}}

Never invent an action outside the list above. If the request describes something outside these actions (e.g. asking to change scraping sources, add a new job board, rewrite scoring logic), return confident=false with a clarifying_question explaining that's outside what you can currently propose."""


def _local_llm_chat(messages: list[dict[str, str]]) -> str:
    """Call the configured local Ollama model directly over HTTP. Raises on
    failure — callers must treat any exception as "could not parse", not
    silently proceed.

    Talks to Ollama's /api/chat directly rather than importing a shared
    helper module, since those live under ops/omi_telegram/ which isn't on
    this container's PYTHONPATH — a plain HTTP call avoids that cross
    -container path dependency entirely.
    """
    import httpx

    from ollama_resolve import effective_ollama_base_url

    base = effective_ollama_base_url().rstrip("/")
    if not base:
        raise RuntimeError("Ollama base URL is empty")
    # Defaults to SLOT14 (omi-ft-14b-v19) — its long context comfortably
    # fits this system prompt plus the supported-actions list plus a chat
    # request. "slot14"/"slot32" are internal routing aliases, not real
    # Ollama tags, so JOB_FILTER_TUNE_LLM_MODEL must be a real model:tag
    # name if overridden (see `ollama list` / GET {base}/api/tags).
    model = os.environ.get("JOB_FILTER_TUNE_LLM_MODEL", "").strip() or "omi-ft-14b-v19:latest"
    resp = httpx.post(
        f"{base}/api/chat",
        json={"model": model, "messages": messages, "stream": False},
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("message", {}).get("content", ""))


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    # Strip markdown code fences if the model wrapped its JSON in one.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def parse_change_request(raw_text: str) -> dict[str, Any]:
    """Parse a free-text tune request into a structured proposal or a
    clarifying question. Never raises to the caller — any failure (model
    unreachable, malformed output, action outside the fixed vocabulary)
    degrades to a clarifying question, never a guessed action.
    """
    fallback = {
        "confident": False,
        "clarifying_question": (
            "Не смог разобрать запрос — модель недоступна или ответ был не в "
            "ожидаемом формате. Опишите изменение точнее: какое слово/фразу "
            "добавить или убрать из исключений, или какой порог поменять."
        ),
    }
    try:
        reply = _local_llm_chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ]
        )
    except Exception as exc:
        log.warning("job_filter tune LLM call failed: %s", exc)
        return fallback

    parsed = _extract_json_object(reply)
    if not parsed or not isinstance(parsed, dict):
        log.warning("job_filter tune LLM returned unparseable output: %r", reply[:500])
        return fallback

    if parsed.get("confident") is True:
        action = parsed.get("action")
        if action not in _SUPPORTED_ACTIONS:
            log.warning("job_filter tune LLM invented an unsupported action: %r", action)
            return fallback
        if not str(parsed.get("target", "")).strip():
            return fallback
        if not str(parsed.get("understood_summary", "")).strip():
            return fallback
        return parsed

    if parsed.get("confident") is False and str(parsed.get("clarifying_question", "")).strip():
        return parsed

    return fallback


def current_filter_summary() -> str:
    """Introspect the bot's own live filter configuration — the /skills
    command. Reflects actual JobFilterConfig defaults plus the env-var
    overrides that govern draft-creation thresholds.
    """
    cfg = JobFilterConfig()
    lines = [
        "<b>JobLocator — текущие фильтры</b>",
        "",
        f"Title exclusions ({len(cfg.title_exclusions)}): " + ", ".join(sorted(cfg.title_exclusions)),
        "",
        f"Hard exclusions ({len(cfg.hard_exclusions)}): " + ", ".join(sorted(cfg.hard_exclusions)),
        "",
        f"Min experience years: {cfg.min_experience_years}",
        "",
        "Draft-creation thresholds:",
        f"  resume match ≥ {os.environ.get('JOB_FILTER_DRAFT_MIN_ATS_PERCENT', '20')}%",
        f"  description ≥ {os.environ.get('JOB_FILTER_DRAFT_MIN_DESCRIPTION_CHARS', '80')} chars",
        f"  opportunity score ≥ {os.environ.get('JOB_FILTER_DRAFT_MIN_OPPORTUNITY_SCORE', '70')}",
    ]
    return "\n".join(lines)


def current_task_summary() -> str:
    """/tasks — JobLocator's own plan: what's queued, confirmed (awaiting
    fullstack), and recently completed.
    """
    pending = jfcr.list_pending()
    confirmed = jfcr.list_confirmed()
    completed = jfcr.list_completed()[-5:]

    lines = ["<b>JobLocator — задачи</b>", ""]
    lines.append(f"Ожидают подтверждения ({len(pending)}):")
    for r in pending:
        lines.append(f"  • {r.request_id}: {r.understood_summary}")
    lines.append("")
    lines.append(f"Подтверждены, ждут fullstack ({len(confirmed)}):")
    for r in confirmed:
        lines.append(f"  • {r.request_id}: {r.understood_summary}")
    lines.append("")
    lines.append(f"Недавно выполнено (последние {len(completed)}):")
    for r in completed:
        lines.append(f"  • {r.request_id}: {r.understood_summary} — {r.evidence[:120]}")
    return "\n".join(lines)


# ── Telegram handlers ────────────────────────────────────────────────────────


async def cmd_start(update, context) -> None:
    await update.message.reply_text(
        "JobLocator online. /tune <что изменить> — предложить изменение фильтров. "
        "/skills — текущие фильтры. /tasks — очередь задач. /help — помощь."
    )


async def cmd_help(update, context) -> None:
    await update.message.reply_text(
        "/tune <текст> — опишите словами, что изменить в поиске (например: "
        "'убери из результатов чистых электриков'). Я предложу понимание "
        "задачи и попрошу подтвердить /confirm <id> перед постановкой в "
        "очередь на fullstack.\n"
        "/confirm <id> — подтвердить предложенное изменение.\n"
        "/cancel <id> — отменить.\n"
        "/skills — какие фильтры активны сейчас.\n"
        "/tasks — что в очереди / подтверждено / недавно сделано."
    )


async def cmd_tune(update, context) -> None:
    raw_text = " ".join(context.args) if context.args else ""
    if not raw_text.strip():
        await update.message.reply_text("Использование: /tune <что изменить>")
        return
    chat_id = str(update.effective_chat.id)
    parsed = parse_change_request(raw_text)

    if not parsed.get("confident"):
        await update.message.reply_text(
            parsed.get("clarifying_question", "Уточните запрос, пожалуйста.")
        )
        return

    record = jfcr.write_change_request(
        requested_by=chat_id,
        raw_request_text=raw_text,
        understood_summary=str(parsed["understood_summary"]),
        proposed_change={
            "action": parsed["action"],
            "target": parsed["target"],
            "reason": raw_text,
        },
    )
    await update.message.reply_text(
        f"Понял так: {record.understood_summary}\n\n"
        f"Подтвердите: /confirm {record.request_id}\n"
        f"Отменить: /cancel {record.request_id}\n"
        f"(истекает через 10 минут без подтверждения)"
    )


async def cmd_confirm(update, context) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /confirm <id>")
        return
    request_id = context.args[0]
    chat_id = str(update.effective_chat.id)
    record = jfcr.load_change_request(request_id)
    if record is None:
        await update.message.reply_text("Задача не найдена.")
        return
    if record.status != "pending":
        await update.message.reply_text(f"Задача уже в статусе: {record.status}")
        return
    if jfcr.is_expired(record):
        jfcr.mark_rejected(request_id, reason="confirmation window expired")
        await update.message.reply_text("Время на подтверждение истекло, задача отменена. Отправьте /tune заново.")
        return
    confirmed = jfcr.mark_confirmed(request_id, requested_by=chat_id)
    if confirmed is None:
        await update.message.reply_text("Не удалось подтвердить (не ваша задача?).")
        return
    await update.message.reply_text(
        f"Принято: {confirmed.request_id}\n"
        "Задача поставлена в очередь для Logi/fullstack. "
        "Сообщу здесь, когда изменение будет реально внедрено и подтверждено — "
        "не раньше."
    )


async def cmd_cancel(update, context) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /cancel <id>")
        return
    request_id = context.args[0]
    rejected = jfcr.mark_rejected(request_id, reason="cancelled by requester")
    if rejected is None:
        await update.message.reply_text("Задача не найдена или уже закрыта.")
        return
    await update.message.reply_text(f"Отменено: {rejected.request_id}")


async def cmd_skills(update, context) -> None:
    await update.message.reply_text(current_filter_summary(), parse_mode="HTML")


async def cmd_tasks(update, context) -> None:
    await update.message.reply_text(current_task_summary(), parse_mode="HTML")


def build_application():
    """Construct the python-telegram-bot Application. Imported lazily so
    modules that only need parse_change_request()/current_filter_summary()
    (e.g. tests) don't require python-telegram-bot to be installed.
    """
    from telegram.ext import Application, CommandHandler

    token = os.environ.get("JOB_FILTER_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("JOB_FILTER_BOT_TOKEN is not set")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("tune", cmd_tune))
    app.add_handler(CommandHandler("confirm", cmd_confirm))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    return app


def run_polling_forever() -> None:
    app = build_application()
    log.info("JobLocator Telegram listener starting (polling)")
    app.run_polling(drop_pending_updates=True, close_loop=False)
