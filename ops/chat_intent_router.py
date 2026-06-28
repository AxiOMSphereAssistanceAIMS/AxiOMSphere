"""Shared free-text → slash-command router for AIMS bots.

Accepts a user message and a command map, calls the local small Qwen model for
intent classification, returns (command_name, args_list) or None for "chat" intent.

Usage in a bot handler:
    from chat_intent_router import classify, ARGUS_CMDS
    result = await asyncio.to_thread(classify, text, ARGUS_CMDS)
    if result:
        cmd, args = result
        ctx.args = args
        await cmd_map[cmd](update, ctx)
        return
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

_TIMEOUT = 8

# ── Command maps ──────────────────────────────────────────────────────────────

ARGUS_CMDS: dict[str, str] = {
    "status":      "system/container status, что запущено, состояние, как дела",
    "models":      "list available ollama models, модели, список моделей",
    "installed":   "list installed ollama models on nodes, установленные модели",
    "logs":        "show container logs, логи [container] [N]",
    "restart":     "restart container, перезапусти [container]",
    "rebuild":     "rebuild/redeploy container, пересобери [container]",
    "stop":        "stop container, останови [container]",
    "up":          "start/up container, запусти [container]",
    "load":        "load ollama model into VRAM, загрузи модель [model]",
    "unload":      "unload/evict ollama model from VRAM, выгрузи модель [model]",
    "tasks":       "show running/queued tasks, задачи, очередь задач",
    "incidents":   "show incidents/alerts, инциденты, алерты",
    "diagnose":    "run self-diagnostics, диагностика системы",
    "dgx":         "DGX hardware info / GPU memory, железо, GPU VRAM, метрики DGX",
    "wake":        "wake up argus / disable sleep, разбудить, не спать",
    "sleep":       "enable sleep mode, уснуть, тихий режим",
    "digest":      "show daily digest/summary, дайджест, сводка",
    "plan":        "show weekly/daily plan, план, расписание",
    "ft_log":      "show fine-tuning training log, лог обучения, что в логе тренировки, покажи лог [14|70|72|qwen3]",
    "ft_download": "HF model download progress, что скачивается, статус загрузки модели, прогресс скачки",
    "eval":        "A/B compare two models on golden suite, сравни модели, запусти eval, оцени модель [candidate] [baseline]",
    "deploy":      "deploy/transfer model to PC Andrei, задеплой модель, перенеси модель на андрей, деплой [model]",
}

OMI_CMDS: dict[str, str] = {
    "status":               "pipeline queue status, статус очереди, что в обработке",
    "tasks":                "show active/pending tasks, задачи, список задач",
    "search":               "search documents in registry, найди [query], поиск",
    "registry_audit":       "read-only registry consistency audit, certified without master, pending without master, rejected without master, master without standard, compare standards_index with documents",
    "docs_today":           "documents processed today, документы сегодня, что обработано",
    "registry_sync_status": "registry sync/replication status, статус реестра, синхронизация",
    "docsreg":              "register source files into the master-document DB via DOCSREG, run certification cycle from a file path on DGX, register standards / docs / files into registry, запусти DOCSREG, DOCSREG teacher",
    "move":                 "move document to section P01–P11, переместить [file] [section]",
    "archive":              "archive document, архивировать [file]",
    "backup_now":           "run backup right now, сделай бэкап, резервная копия сейчас",
    "backup_list":          "list existing backups, список бэкапов",
    "nightplan":            "show or run night processing plan, ночной план",
    "skills":               "list available Omi skills/tools, навыки, возможности",
    "selftest":             "run self-test / smoke check, самотест, проверь себя",
}

DOCUMENT_WORK_CMDS: dict[str, str] = {
    "docsreg": (
        "register or certify source documents into the master-document database; "
        "use when the user asks to register standards, files, folders, evidence, or documents"
    ),
    "docgen": (
        "generate or synthesize a document/master document from sources or a draft; "
        "use when the user asks to create a new document, produce a DOCGEN bundle, or generate output"
    ),
}

AXI_CMDS: dict[str, str] = {
    "quality_report": "quality report on recent documents, отчёт качества, покажи качество",
    "stuck_tasks":    "show stuck/frozen tasks, зависшие задачи, задачи не двигаются",
    "analyze":        "analyze document(s), анализ документа, проанализируй файл",
    "registry_audit": "read-only registry consistency audit, certified without master, pending without master, master without standard, compare standards_index with documents",
}

# ── Internal HTTP helper ──────────────────────────────────────────────────────

def _post_ollama(base_url: str, model: str, prompt: str, timeout: int) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return (data.get("message", {}).get("content") or "").strip()


# ── Keyword fallback (no LLM required) ───────────────────────────────────────

# Maps command_name → list of keyword sets (each set: ALL words must appear).
_KEYWORD_RULES: dict[str, list[tuple[str, ...]]] = {
    # AXI_CMDS
    "quality_report": [("качеств",), ("quality", "report"), ("отчёт",), ("report",)],
    "stuck_tasks":    [("зависш",), ("stuck",), ("не двигает",), ("frozen",)],
    "analyze":        [("анализ",), ("analyze",), ("анализируй",)],
    "registry_audit": [("registry audit",), ("registry consistency",), ("certified without master",), ("pending without master",), ("master without standard",), ("аудит реест",), ("проверь реестр",), ("расхожд",)],
    # ARGUS_CMDS
    "status":         [("статус",), ("состояние",), ("status",), ("как дела",)],
    "models":         [("модели",), ("models",), ("список моделей",)],
    "logs":           [("логи",), ("logs",)],
    "restart":        [("перезапусти",), ("restart",)],
    "diagnose":       [("диагностик",), ("diagnose",)],
    "dgx":            [("dgx",), ("gpu",), ("vram",)],
    "tasks":          [("задачи",), ("tasks",), ("очередь",)],
    "incidents":      [("инцидент",), ("алерт",), ("incident",), ("alert",)],
    "digest":         [("дайджест",), ("digest",), ("сводка",)],
    # OMI_CMDS
    "search":         [("найди",), ("поиск",), ("search",)],
    "registry_audit": [("registry audit",), ("registry consistency",), ("certified without master",), ("pending without master",), ("rejected without master",), ("master without standard",), ("аудит реест",), ("проверь реестр",), ("расхожд",)],
    "docsreg":        [
        ("docsreg",),
        ("доксрег",),
        ("запусти docsreg",),
        ("run docsreg",),
        ("start docsreg",),
        ("register", "standards"),
        ("register", "standard"),
        ("register", "documents"),
        ("register", "document"),
        ("register", "docs"),
        ("register", "files"),
        ("register", "folder"),
        ("register", "standards", "from"),
    ],
    "backup_now":     [("бэкап",), ("backup",), ("резервная копия",)],
}


def _keyword_classify(
    text: str,
    cmd_map: dict[str, str],
) -> tuple[str, list[str]] | None:
    """Fast keyword fallback — no LLM required. Returns first matching command."""
    tl = text.lower()
    for cmd, rule_sets in _KEYWORD_RULES.items():
        if cmd not in cmd_map:
            continue
        for keywords in rule_sets:
            if all(kw in tl for kw in keywords):
                return cmd, []
    return None


# ── Classifier ────────────────────────────────────────────────────────────────

def classify(
    text: str,
    cmd_map: dict[str, str],
    *,
    base_url: str = "",
    model: str = "",
    timeout: int = _TIMEOUT,
    dialog_messages: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]] | None:
    """
    Classify free text against cmd_map using the local small model.
    Returns (command_name, args_list) or None when intent is plain chat.

    base_url / model resolved from env if not provided.
    Falls back to keyword matching when model is unavailable.
    """
    text = (text or "").strip()
    if not text:
        return None

    if not base_url:
        try:
            from ollama_resolve import effective_small_qwen_ollama_base_url
            base_url = effective_small_qwen_ollama_base_url()
        except Exception:
            pass

    if not model:
        try:
            from ollama_resolve import small_qwen_model_name
            model = small_qwen_model_name()
        except Exception:
            model = os.environ.get("AXI_INTENT_OLLAMA_MODEL", "") or os.environ.get("OMI_OLLAMA_MODEL", "")

    # Keyword fallback when model is unavailable
    if not base_url or not model:
        return _keyword_classify(text, cmd_map)

    cmd_lines = "\n".join(f"- {k}: {v}" for k, v in cmd_map.items())
    dialog_lines = ""
    if dialog_messages:
        turns: list[str] = []
        for item in dialog_messages[-8:]:
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                turns.append(f"{role}: {content}")
        if turns:
            dialog_lines = "\nConversation context:\n" + "\n".join(turns) + "\n"
    if cmd_map is DOCUMENT_WORK_CMDS:
        prompt = (
            "You are a document-work router for AIMS.\n"
            "Choose exactly one command: docsreg or docgen.\n"
            "Use the current message plus conversation context.\n"
            "Return ONLY: docsreg [args...] or docgen [args...] or chat.\n"
            "Never return clarify, question, or any other command.\n"
            "Important: short replies like 'yes', 'continue', 'do that', 'go ahead' must be resolved from the conversation context.\n"
            "Examples:\n"
            "Conversation: user asks 'Should I register these standards or generate a new document?'\n"
            "User message: 'yes, register them'\n"
            "Route: docsreg\n"
            "Conversation: user asks 'Do you want DOCSREG or DOCGEN?'\n"
            "User message: 'yes, generate the document'\n"
            "Route: docgen\n"
            "Rules:\n"
            "- docsreg: register standards, source files, folders, registry/database, master documents.\n"
            "- docgen: generate a new document or DOCGEN bundle from sources or draft text.\n"
            "- If the user says register in the context of standards/master DB, choose docsreg.\n"
            "- If the user asks to generate or build a document, choose docgen.\n"
            "- If the user is clearly referring to the previous document-work choice with short replies like yes/continue, use the conversation context.\n\n"
            f"Commands:\n{cmd_lines}\n"
            f"{dialog_lines}\n"
            f"User message: {text}\n"
            "Route:"
        )
    else:
        prompt = (
            "You are a command router. Given a user message, return the matching command name "
            "and any space-separated arguments.\n"
            "Reply with ONLY: command_name [args...]\n"
            "If no command fits (plain question/conversation), reply with: chat\n\n"
            f"Commands:\n{cmd_lines}\n"
            f"{dialog_lines}\n"
            f"User message: {text}\n"
            "Route:"
        )

    try:
        raw = _post_ollama(base_url, model, prompt, timeout).lower().strip()
    except Exception:
        # Model call failed — try keyword fallback before giving up
        return _keyword_classify(text, cmd_map)

    parts = raw.split()
    if not parts:
        return _keyword_classify(text, cmd_map)

    cmd = parts[0].rstrip(":").strip()
    if cmd == "chat" or cmd not in cmd_map:
        return None

    args = parts[1:]
    return cmd, args
