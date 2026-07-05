"""
logi_assistant_gateway.py

Thin gateway layer sitting in front of LogiAgent.

Pipeline:
  1. Parse minimal context (language, project area, operational keywords)
  2. Load live Telegram/Traini/Argus context if query is operational
  3. Apply M10 safety rules
  4. Delegate to existing LogiAgent (or return enriched context directly
     for read-only operational queries where LogiAgent is not needed)
  5. Return structured result dict

Does NOT replace: ai_intent_router, syntax_interpreter, syntax_policy, or LogiAgent tools.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ops.agents.m10_safety_adapter import check_m10_safety
from ops.agents.operational_context_merger import is_operational_question, merge_operational_context
from ops.agents.telegram_context_ingestor import load_operational_context

# Import canonical executor task regex from local_executor_action (single source of truth).
# Covers English strict/natural + Russian/mixed forms.
from ops.agents.local_executor_action import EXECUTOR_TASK_RE as _EXECUTOR_TASK_RE

_ROOT = Path(__file__).resolve().parents[2]

_STATIC_SCHEDULE = {
    "22:30 UTC": "VRAM unload — pre_docbench_unload.py",
    "23:00 UTC": "DocBench nightly",
    "00:01 UTC": "training_ingest — new documents",
    "00:30 UTC": "training_generate_pairs — 32B (~60–90 min)",
    "02:30 UTC": "ft_prepare_chain_run — QLoRA 14B",
    "05:30 UTC": "daily_deploy_14b_to_andrei.py",
}

_AREA_RE = re.compile(
    r"\b(DOCSREG|DOCGEN|Redis|scheduler|Traini|Argus|Repairman|"
    r"Claude\s*Code|SLOT32|SLOT14|SLOT120|logi)\b",
    re.IGNORECASE,
)
_TASK_ID_RE = re.compile(r"\bCC-TASK-\d{4}\b")
_LANGUAGE_RE = re.compile(r"[а-яёА-ЯЁ]")


@dataclass
class GatewayContext:
    raw_text: str
    source: str
    chat_id: str
    from_user: str
    language: str
    mentioned_area: str | None
    mentioned_task_id: str | None
    is_operational: bool
    now_utc: str


def _parse_context(text: str, source: str, chat_id: str, from_user: str) -> GatewayContext:
    now_utc = datetime.now(timezone.utc).isoformat()
    ru = len(_LANGUAGE_RE.findall(text or ""))
    en = len(re.findall(r"[a-zA-Z]", text or ""))
    language = "ru" if ru > en * 0.3 else "en"
    area_m = _AREA_RE.search(text or "")
    area = area_m.group(0) if area_m else None
    task_m = _TASK_ID_RE.search(text or "")
    return GatewayContext(
        raw_text=text or "",
        source=source,
        chat_id=chat_id,
        from_user=from_user,
        language=language,
        mentioned_area=area,
        mentioned_task_id=task_m.group(0) if task_m else None,
        is_operational=is_operational_question(text or ""),
        now_utc=now_utc,
    )


def process_gateway_message(
    text: str,
    source: str = "cli",
    chat_id: str = "0",
    from_user: str = "",
) -> dict:
    ctx = _parse_context(text, source, chat_id, from_user)

    # ── run_local_executor_task: narrow approved execution path ──────────────
    executor_match = _EXECUTOR_TASK_RE.search(text or "")
    if executor_match:
        task_json = executor_match.group(1).strip()
        from ops.agents.local_executor_action import (
            run_local_executor_task,
            format_telegram_executor_result,
            validate_executor_message,
            LocalExecutorActionResult,
        )
        # Validate full message text before executing — rejects trailing injection
        msg_ok, msg_reason = validate_executor_message(text or "")
        if not msg_ok:
            blocked = LocalExecutorActionResult(
                status="FAILED",
                execution_route="logi_telegram_local_executor",
                task_json=task_json,
                stdout="", stderr=msg_reason, exit_code=1,
                executor_result={},
                file_created=False, content_verified=False,
                sha256=None, error_class="COMMAND_BLOCKED",
            )
            return {
                "status": "FAILED",
                "action_type": "run_local_executor_task",
                "execution_route": "logi_telegram_local_executor",
                "task_json": task_json,
                "file_created": False,
                "content_verified": False,
                "sha256": None,
                "error_class": "COMMAND_BLOCKED",
                "executor_result": {},
                "summary": format_telegram_executor_result(blocked),
                "source": source,
                "now_utc": ctx.now_utc,
            }
        exec_result = run_local_executor_task(task_json)
        return {
            "status": exec_result.status,
            "action_type": "run_local_executor_task",
            "execution_route": exec_result.execution_route,
            "task_json": task_json,
            "file_created": exec_result.file_created,
            "content_verified": exec_result.content_verified,
            "sha256": exec_result.sha256,
            "error_class": exec_result.error_class,
            "executor_result": exec_result.executor_result,
            "summary": format_telegram_executor_result(exec_result),
            "source": source,
            "now_utc": ctx.now_utc,
        }
    # ─────────────────────────────────────────────────────────────────────────

    # M10 safety check
    safety = check_m10_safety(text, source, intent_confidence=0.85)
    if not safety.allowed:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "reason": safety.reason,
            "requires_confirmation": safety.requires_confirmation,
            "text": text,
        }
    if safety.requires_confirmation:
        return {
            "status": "REQUIRES_CONFIRMATION",
            "allowed": True,
            "requires_confirmation": True,
            "reason": safety.reason,
            "text": text,
        }

    # Operational query: enrich with live context before delegating
    operational_ctx: dict | None = None
    if ctx.is_operational:
        live_msgs = load_operational_context(max_messages=20)
        operational_ctx = merge_operational_context(
            user_query=text,
            static_schedule=_STATIC_SCHEDULE,
            telegram_context=live_msgs,
            scheduler_context=None,
            now_utc=ctx.now_utc,
        )

    # Build enriched prompt for LogiAgent
    enriched_text = text
    if operational_ctx and operational_ctx.get("status") not in ("NO_TRAINING_FOUND", "UNKNOWN"):
        # Prepend operational summary so LogiAgent can incorporate it
        enriched_text = (
            f"[OPERATIONAL CONTEXT — {ctx.now_utc}]\n"
            f"{operational_ctx.get('answer_summary', '')}\n\n"
            f"[USER QUERY]\n{text}"
        )

    # Delegate to LogiAgent — compatibility helper: tries .chat() then .run()
    logi_response: str | None = None
    logi_error: str | None = None
    logi_error_class: str | None = None
    try:
        from ops.logi.conversational_orchestrator import LogiAgent
        agent = LogiAgent()
        if callable(getattr(agent, "chat", None)):
            logi_response = agent.chat(enriched_text)
        elif callable(getattr(agent, "run", None)):
            # run(user_id, text) — use chat_id as user_id, falling back to 0
            try:
                uid = int(chat_id) if chat_id else 0
            except (ValueError, TypeError):
                uid = 0
            logi_response = agent.run(uid, enriched_text)
        else:
            logi_error = "LogiAgent has neither .chat() nor .run()"
            logi_error_class = "LOGI_AGENT_METHOD_MISSING"
    except Exception as exc:
        logi_error = f"{type(exc).__name__}: {exc}"
        logi_error_class = "LOGI_AGENT_DELEGATION_FAILED"

    # Build result
    result: dict = {
        "status": "OK",
        "source": source,
        "language": ctx.language,
        "mentioned_area": ctx.mentioned_area,
        "mentioned_task_id": ctx.mentioned_task_id,
        "now_utc": ctx.now_utc,
    }
    if operational_ctx:
        result["operational_status"] = operational_ctx.get("status")
        result["operational_summary"] = operational_ctx.get("answer_summary", "")
        result["sources_used"] = operational_ctx.get("sources_used", [])

    if logi_response:
        result["logi_response"] = logi_response
        result["summary"] = logi_response
    elif logi_error:
        # Delegation failed — surface the error explicitly, never swallow silently
        result["status"] = "DEGRADED"
        result["warning"] = "LogiAgent delegation failed"
        result["error_class"] = logi_error_class
        result["error_message"] = logi_error
        if operational_ctx and operational_ctx.get("answer_summary"):
            result["summary"] = operational_ctx["answer_summary"]
        else:
            result["summary"] = f"LogiAgent delegation failed: {logi_error}"
    elif operational_ctx and operational_ctx.get("answer_summary"):
        result["summary"] = operational_ctx["answer_summary"]
        result["warning"] = "LogiAgent unavailable — returning operational context only"
    else:
        result["summary"] = "No response available."
        result["warning"] = "LogiAgent produced no output"

    return result
