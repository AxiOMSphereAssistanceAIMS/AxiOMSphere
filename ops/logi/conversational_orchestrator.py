"""ConversationalOrchestrator — LLM-powered interactive orchestration agent.

Provides conversational interface with plan management and agent delegation.
Uses Qwen3:14b for lightweight reasoning and interactive workflows.
Delegates to PipelineCoordinator for structured document pipelines.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable

from logi.plans import (
    Plan, Step, PlanStatus,
    save_plan, load_plan, list_plans as _list_plans,
    latest_active_plan,
)
from logi.tool_registry import TOOL_REGISTRY

log = logging.getLogger("aims.conversational_orchestrator")

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
AGENT_MODEL = os.environ.get("CONVERSATIONAL_ORCHESTRATOR_MODEL", os.environ.get("LOGI_AGENT_MODEL", "qwen3:14b"))
HISTORY_TURNS = 8

SYSTEM_PROMPT = """You are ConversationalOrchestrator — an intelligent interactive agent for the AIMS document factory system.
You have two modes: conversational chat and structured plan-based task delegation.

Available agents (via tool_registry):
- knomi: knowledge search (finds relevant regulatory docs, standards, prior work)
- doci: document composer/generator (creates HSE, ISO, emergency procedures, etc.)
- poli: policy validator (checks documents against regulations)
- cloud: cloud quality validation (DeepSeek/Gemini comparison)
- omi: document storage and retrieval
- traini: training data collection
- pipeline_coordinator: full pipeline orchestrator (end-to-end document task)

When the user asks a question or wants to chat — respond directly.
When the user wants to plan, create, or delegate work — use tools to build and execute a plan.
Always think step by step. Prefer creating a plan with steps before executing, unless the task is simple.

Respond in the same language the user uses (Russian or English).
Keep responses concise and informative."""


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a new plan with a title and goal. Use this when starting a multi-step task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short plan title"},
                    "goal": {"type": "string", "description": "Detailed goal description"},
                },
                "required": ["title", "goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_step",
            "description": "Add a step to the current active plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "Plan ID (from create_plan or list_plans)"},
                    "title": {"type": "string", "description": "Step description"},
                    "agent": {
                        "type": "string",
                        "enum": ["knomi", "doci", "poli", "cloud", "omi", "traini", "logi"],
                        "description": "Which agent handles this step",
                    },
                    "payload": {"type": "object", "description": "Parameters to pass to the agent"},
                },
                "required": ["plan_id", "title", "agent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_step",
            "description": "Execute a single pending step in a plan by calling the assigned agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "step_id": {"type": "string"},
                },
                "required": ["plan_id", "step_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_plan",
            "description": "Execute all pending steps in a plan sequentially.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                },
                "required": ["plan_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan_status",
            "description": "Get current status and step results of a plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                },
                "required": ["plan_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_plans",
            "description": "List all plans for the current user.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the knowledge base via knomi agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_document",
            "description": "Generate a document via doci agent (compose_and_generate endpoint).",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Document topic or detailed description"},
                    "doc_type": {"type": "string", "default": "procedure"},
                    "department": {"type": "string", "default": "operations"},
                },
                "required": ["content"],
            },
        },
    },
]


def _http_post(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ollama_chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    payload: dict[str, Any] = {
        "model": AGENT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3},
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")

    for attempt in range(4):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=240) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
            if e.code == 500 and attempt < 3:
                wait = (attempt + 1) * 10
                log.warning("Ollama 500 (attempt %d/4), retrying in %ds: %s", attempt + 1, wait, body)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(10)
                continue
            raise


def _call_agent(agent: str, payload: dict) -> str:
    """Call an agent via tool_registry and return formatted response."""
    from logi.tool_registry import call_tool

    result = call_tool(agent, payload)

    if "error" in result:
        return f"Error calling {agent}: {result['error']}"

    if not isinstance(result, dict):
        return str(result)

    # Agent-specific response extraction
    if agent == "knomi":
        items = result.get("results", [])
        if not items:
            return "No knowledge base results found for this query."
        lines = []
        for r in items[:5]:
            title = r.get("title") or r.get("doc_id", "?")
            snippet = r.get("snippet") or r.get("text", "")[:200]
            score = r.get("score", 0)
            lines.append(f"• [{score:.2f}] {title}: {snippet}")
        return "\n".join(lines)

    if agent == "doci":
        preview = result.get("preview", "")
        doc_path = result.get("doc_path", "")
        status = result.get("status", "?")
        score = result.get("quality_score", 0)
        return f"Document {status} (quality={score:.1f})\nPath: {doc_path}\nPreview:\n{preview[:800]}"

    if agent == "poli":
        allowed = result.get("allowed", False)
        reason = result.get("reason", "")
        audit_id = result.get("audit_id", "")
        return f"Policy check: {'ALLOWED' if allowed else 'DENIED'}\nReason: {reason}\nAudit: {audit_id}"

    if agent == "cloud":
        score = result.get("quality_score", result.get("score", 0))
        feedback = result.get("feedback", result.get("quality_feedback", ""))
        status = result.get("status", "?")
        return f"Cloud validation: {status} (score={score})\n{feedback[:500]}"

    if agent == "omi":
        doc_id = result.get("doc_id", result.get("id", "?"))
        title = result.get("title", "?")
        status = result.get("status", "?")
        return f"Document stored: id={doc_id}, title={title}, status={status}"

    if agent == "traini":
        job_id = result.get("job_id", "?")
        status = result.get("status", "?")
        return f"Training job: {job_id}, status={status}"

    # Generic fallback — try common text keys
    for key in ("result", "content", "output", "text", "document", "answer", "message"):
        if key in result and result[key]:
            val = result[key]
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)

    return json.dumps(result, ensure_ascii=False)


def _normalize_payload(agent: str, payload: dict, step_title: str = "") -> dict:
    """Ensure the payload matches each agent's expected request schema."""
    import uuid as _uuid

    if agent == "knomi":
        return {
            "query": payload.get("query") or step_title,
            "top_k": payload.get("top_k", 10),
        }

    if agent == "doci":
        return {
            "task_id": payload.get("task_id") or _uuid.uuid4().hex[:12],
            "user_request": payload.get("user_request") or payload.get("content") or step_title,
            "doc_type": payload.get("doc_type", "procedure"),
            "filtered_docs": payload.get("filtered_docs", []),
            "industry": payload.get("industry"),
            "level": payload.get("level"),
        }

    if agent == "poli":
        return {
            "action_type": payload.get("action_type", "document_generation"),
            "params": payload.get("params") or {"description": step_title},
            "requester": payload.get("requester", "logi_agent"),
            "department": payload.get("department", "operations"),
        }

    if agent == "cloud":
        return {
            "task_id": payload.get("task_id") or _uuid.uuid4().hex[:12],
            "user_request": payload.get("user_request") or step_title,
            "document_text": payload.get("document_text", ""),
            "doc_path": payload.get("doc_path"),
            "doc_type": payload.get("doc_type", "procedure"),
        }

    if agent == "omi":
        return {
            "task_id": payload.get("task_id") or _uuid.uuid4().hex[:12],
            "title": payload.get("title") or step_title,
            "doc_type": payload.get("doc_type", "procedure"),
            "status": payload.get("status", "draft"),
            "quality_score": payload.get("quality_score", 0.0),
            "file_path": payload.get("file_path"),
            "summary": payload.get("summary") or step_title,
            "industry": payload.get("industry"),
        }

    if agent == "traini":
        return {
            "trigger_reason": payload.get("trigger_reason", "manual"),
            "base_model": payload.get("base_model"),
            "epochs": payload.get("epochs"),
            "force": payload.get("force", False),
        }

    # logi orchestrator and fallback — pass through as-is
    if "content" not in payload and step_title:
        payload = {**payload, "content": step_title}
    return payload


class LogiAgent:
    def __init__(self) -> None:
        self._history: dict[int, list[dict]] = {}

    def _get_history(self, user_id: int) -> list[dict]:
        return self._history.setdefault(user_id, [])

    def clear_history(self, user_id: int) -> None:
        self._history[user_id] = []

    def _trim_history(self, history: list[dict]) -> list[dict]:
        if len(history) > HISTORY_TURNS * 2:
            return history[-(HISTORY_TURNS * 2):]
        return history

    # ── tool handlers ─────────────────────────────────────────────────────────

    def _tool_create_plan(self, user_id: int, args: dict) -> str:
        plan = Plan(user_id=user_id, title=args["title"], goal=args["goal"])
        save_plan(plan)
        return f"Plan created: id={plan.id}\n{plan.summary()}"

    def _tool_add_step(self, user_id: int, args: dict) -> str:
        plan_id = args["plan_id"]
        plan = load_plan(user_id, plan_id)
        if not plan:
            return f"Plan {plan_id} not found"
        step = Step(
            title=args["title"],
            agent=args["agent"],
            payload=args.get("payload") or {},
        )
        plan.steps.append(step)
        save_plan(plan)
        return f"Step added: {step.id} → [{step.agent}] {step.title}\n{plan.summary()}"

    def _tool_execute_step(self, user_id: int, args: dict, notify: Callable[[str], None] | None = None) -> str:
        plan = load_plan(user_id, args["plan_id"])
        if not plan:
            return f"Plan {args['plan_id']} not found"
        step = next((s for s in plan.steps if s.id == args["step_id"]), None)
        if not step:
            return f"Step {args['step_id']} not found"
        if step.status == "done":
            return f"Step {step.id} already done"

        step.status = "running"
        plan.status = "active"
        save_plan(plan)
        if notify:
            notify(f"Running step: [{step.agent}] {step.title}")

        result = _call_agent(step.agent, _normalize_payload(step.agent, step.payload, step.title))
        step.result = result[:2000]
        step.status = "done" if "error" not in result.lower()[:50] else "failed"
        step.error = "" if step.status == "done" else result
        step.finished_at = datetime.utcnow().isoformat()
        save_plan(plan)

        return f"Step {step.id} {step.status}.\nResult: {result[:500]}"

    def _tool_execute_plan(self, user_id: int, args: dict, notify: Callable[[str], None] | None = None) -> str:
        plan = load_plan(user_id, args["plan_id"])
        if not plan:
            return f"Plan {args['plan_id']} not found"

        plan.status = "active"
        save_plan(plan)
        results = []

        for step in plan.steps:
            if step.status != "pending":
                continue
            res = self._tool_execute_step(user_id, {"plan_id": plan.id, "step_id": step.id}, notify)
            results.append(res)
            plan = load_plan(user_id, plan.id) or plan
            if step.status == "failed":
                plan.status = "failed"
                save_plan(plan)
                break
        else:
            plan = load_plan(user_id, plan.id) or plan
            if all(s.status == "done" for s in plan.steps):
                plan.status = "done"
                save_plan(plan)

        return "\n---\n".join(results) or "No pending steps."

    def _tool_get_plan_status(self, user_id: int, args: dict) -> str:
        plan = load_plan(user_id, args["plan_id"])
        if not plan:
            return f"Plan {args['plan_id']} not found"
        lines = [plan.summary()]
        for s in plan.steps:
            if s.result:
                lines.append(f"\nStep {s.id} result:\n{s.result[:300]}")
        return "\n".join(lines)

    def _tool_list_plans(self, user_id: int) -> str:
        plans = _list_plans(user_id)
        if not plans:
            return "No plans found."
        lines = []
        for p in plans[:10]:
            lines.append(f"• {p.id} [{p.status}] {p.title} ({len(p.steps)} steps)")
        return "\n".join(lines)

    def _tool_search_knowledge(self, args: dict) -> str:
        payload = {"query": args["query"], "top_k": args.get("top_k", 10)}
        return _call_agent("knomi", payload)

    def _tool_generate_document(self, args: dict) -> str:
        import uuid as _uuid
        payload = {
            "task_id": _uuid.uuid4().hex[:12],
            "user_request": args["content"],
            "doc_type": args.get("doc_type", "procedure"),
            "filtered_docs": args.get("filtered_docs", []),
            "industry": args.get("industry"),
            "level": args.get("level"),
        }
        return _call_agent("doci", payload)

    def _dispatch_tool(
        self,
        user_id: int,
        name: str,
        args: dict,
        notify: Callable[[str], None] | None,
    ) -> str:
        if name == "create_plan":
            return self._tool_create_plan(user_id, args)
        if name == "add_step":
            return self._tool_add_step(user_id, args)
        if name == "execute_step":
            return self._tool_execute_step(user_id, args, notify)
        if name == "execute_plan":
            return self._tool_execute_plan(user_id, args, notify)
        if name == "get_plan_status":
            return self._tool_get_plan_status(user_id, args)
        if name == "list_plans":
            return self._tool_list_plans(user_id)
        if name == "search_knowledge":
            return self._tool_search_knowledge(args)
        if name == "generate_document":
            return self._tool_generate_document(args)
        return f"Unknown tool: {name}"

    # ── main agent loop ───────────────────────────────────────────────────────

    def run(
        self,
        user_id: int,
        text: str,
        notify: Callable[[str], None] | None = None,
    ) -> str:
        history = self._get_history(user_id)
        history = self._trim_history(history)

        # Inject current plan context if any active plan exists
        active = latest_active_plan(user_id)
        context_injection = ""
        if active:
            context_injection = f"\n\n[Active plan: {active.id}]\n{active.summary()}"

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT + context_injection},
        ] + history + [
            {"role": "user", "content": text},
        ]

        max_iterations = 6
        for iteration in range(max_iterations):
            try:
                resp = _ollama_chat(messages, tools=TOOL_DEFINITIONS)
            except Exception as e:
                err = f"LLM error: {type(e).__name__}: {e}"
                log.error(err)
                return err

            msg = resp.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                # Final text response
                content = msg.get("content", "")
                history.append({"role": "user", "content": text})
                history.append({"role": "assistant", "content": content})
                self._history[user_id] = self._trim_history(history)
                return content

            # Execute tool calls
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    raw_args = fn.get("arguments", {})
                    args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                except Exception:
                    args = {}

                log.info("Tool call: %s(%s)", name, list(args.keys()))
                # Only notify for long-running agent calls, not plan bookkeeping
                if notify and name in ("execute_plan", "execute_step", "search_knowledge", "generate_document"):
                    notify(f"Working: {name}...")

                result = self._dispatch_tool(user_id, name, args, notify)

                messages.append({
                    "role": "tool",
                    "content": result,
                })

        # Fallback if max iterations reached
        history.append({"role": "user", "content": text})
        self._history[user_id] = self._trim_history(history)
        return "Task processing complete. Use /plans to see plan status."
