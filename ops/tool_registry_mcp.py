"""AIMS Tool Registry — MCP server exposing all AIMS agents to NemoClaw/OpenClaw.

Run:
  python ops/tool_registry_mcp.py

Project MCP config (.mcp.json):
  {
    "mcpServers": {
      "aims": {
        "command": "python",
        "args": ["ops/tool_registry_mcp.py"],
        "env": {
          "DOC_AGENT_API_URL": "http://127.0.0.1:8767",
          "OMI_API_URL":       "http://127.0.0.1:8765",
          "TASK_REGISTRY_URL": "http://127.0.0.1:8765",
          "QDRANT_BASE_URL":   "http://127.0.0.1:6333",
          "KNOMI_API_URL":     "http://127.0.0.1:8768",
          "ARGUS_API_URL":     "http://127.0.0.1:8770"
        }
      }
    }
  }
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

# ── sys.path so sibling modules resolve when run from any cwd ──────────────
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

log = logging.getLogger("aims.tool_registry")

# ── service addresses (override via env) ──────────────────────────────────
_DOC_AGENT_URL  = os.environ.get("DOC_AGENT_API_URL",  "http://localhost:8767")
_OMI_API_URL    = os.environ.get("OMI_API_URL",         "http://localhost:8765")
_TASK_REG_URL   = os.environ.get("TASK_REGISTRY_URL",   "http://localhost:8765")
_QDRANT_URL     = os.environ.get("QDRANT_BASE_URL",     "http://localhost:6333")
_KNOMI_API_URL  = os.environ.get("KNOMI_API_URL",       "http://localhost:8768")
_ARGUS_API_URL  = os.environ.get("ARGUS_API_URL",       "http://localhost:8770")

mcp = FastMCP("AIMS Tool Registry")

# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _http(method: str, url: str, body: dict | None = None, timeout: int = 60) -> dict:
    try:
        if method == "GET":
            r = requests.get(url, timeout=timeout)
        else:
            r = requests.post(url, json=body or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": f"service unreachable: {url}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────
# DociAgent — document generation
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def doci_generate(
    user_request: str,
    title: str = "",
    doc_type: str = "",
) -> str:
    """Generate a document via DociAgent (single-pipeline, fast).

    Args:
        user_request: Full description of what document to generate.
        title:        Optional document title.
        doc_type:     Optional document type hint (e.g. 'procedure', 'strategy').
    Returns:
        JSON with path, preview, title.
    """
    body: dict = {"user_request": user_request}
    if title:
        body["title"] = title
    if doc_type:
        body["doc_type"] = doc_type
    result = _http("POST", f"{_DOC_AGENT_URL}/v1/generate", body)
    return _json(result)


@mcp.tool()
def doci_generate_quality(
    user_request: str,
    title: str = "",
) -> str:
    """Generate a document via DociAgent dual-pipeline with NVIDIA NIM DeepSeek-R1 671B quality gate.

    Use this when quality ≥ 85% is required (master documents, ISO-level docs).
    Slower than doci_generate but returns quality_score and feedback.

    Args:
        user_request: Full description of what document to generate.
        title:        Optional document title.
    Returns:
        JSON with path, preview, quality_score (0-1), compliance_pct, feedback.
    """
    body: dict = {"user_request": user_request}
    if title:
        body["title"] = title
    result = _http("POST", f"{_DOC_AGENT_URL}/v1/generate_dual", body)
    return _json(result)


# ─────────────────────────────────────────────────────────────────────────
# KnomiAgent — RAG / knowledge base search
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def knomi_search(
    question: str,
    top_k: int = 8,
    doc_type: str = "",
) -> str:
    """Search AIMS knowledge base and standards (RAG) via KnomiAgent.

    Searches indexed ISO/AIMS standards in Qdrant and generates a grounded answer.

    Args:
        question: Natural-language question or topic to search for.
        top_k:    Number of clauses to retrieve (default 8).
        doc_type: Optional filter by document type (e.g. 'ISO 45001').
    Returns:
        JSON with answer, clauses (citations), context.
    """
    body: dict = {"question": question, "top_k": top_k}
    if doc_type:
        body["doc_type"] = doc_type
    result = _http("POST", f"{_KNOMI_API_URL}/api/v1/search", body)
    if result.get("ok") is False:
        result = _http("POST", f"{_DOC_AGENT_URL}/v1/standards_search", body)
    return _json(result)


# ─────────────────────────────────────────────────────────────────────────
# OmiAgent — document registry / SSoT / OCR
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def omi_search(
    query: str,
    limit: int = 20,
) -> str:
    """Search document registry (OmiAgent).

    Searches registered documents by text/semantic similarity.

    Args:
        query: Search query.
        limit: Max results (default 20).
    Returns:
        JSON list of matching documents with metadata.
    """
    result = _http("POST", f"{_OMI_API_URL}/registry/search",
                   {"query": query, "limit": limit})
    return _json(result)


@mcp.tool()
def omi_status() -> str:
    """Get Omi system status: DB counts, last activity, health.

    Returns:
        JSON with registry stats, health indicators.
    """
    result = _http("GET", f"{_OMI_API_URL}/status")
    return _json(result)


# ─────────────────────────────────────────────────────────────────────────
# ArgusAgent — system monitoring
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def argus_status() -> str:
    """Get system health snapshot from ArgusAgent.

    Reports: GPU/VRAM, running containers, task queue depth, Ollama model status.

    Returns:
        JSON with vram_used_gb, containers, queue_depth, ollama_model, alerts.
    """
    # Try Argus API first; fall back to local subprocess probes
    api_result = _http("GET", f"{_ARGUS_API_URL}/api/v1/health", timeout=10)
    if api_result.get("ok") is not False:
        return _json(api_result)

    data: dict = {}

    # VRAM via nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            timeout=10, text=True,
        ).strip()
        parts = [p.strip() for p in out.split(",")]
        data["vram"] = {
            "used_mb": int(parts[0]),
            "total_mb": int(parts[1]),
            "temp_c": int(parts[2]),
            "used_pct": round(int(parts[0]) / int(parts[1]) * 100, 1),
        }
    except Exception as exc:
        data["vram"] = {"error": str(exc)}

    # Running containers
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            timeout=10, text=True,
        ).strip()
        containers = {}
        for line in out.splitlines():
            if "\t" in line:
                name, status = line.split("\t", 1)
                containers[name] = status
        data["containers"] = containers
    except Exception as exc:
        data["containers"] = {"error": str(exc)}

    # Task queue depth from Task Registry
    try:
        r = requests.get(f"{_TASK_REG_URL}/tasks?limit=5&status=pending", timeout=5)
        r.raise_for_status()
        tasks = r.json()
        data["queue_depth"] = len(tasks) if isinstance(tasks, list) else tasks.get("count", "?")
    except Exception:
        data["queue_depth"] = "unavailable"

    # Ollama model
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        data["ollama_models"] = models
    except Exception:
        data["ollama_models"] = []

    data["ok"] = True
    return _json(data)


# ─────────────────────────────────────────────────────────────────────────
# PoliAgent — policy gate
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def poli_check(
    action_type: str,
    target: str = "",
    model: str = "",
) -> str:
    """Check whether an action is allowed by AIMS policy (PoliAgent).

    Always call this BEFORE mainy_repair. Returns allow/deny with reason.

    Args:
        action_type: One of: restart_container, switch_model, clear_queue,
                     reload_config, pause_worker, resume_worker.
        target:      Target name (e.g. container name for restart_container).
        model:       Model name (required for switch_model).
    Returns:
        JSON with allowed (bool), reason (str).
    """
    try:
        # Import here to avoid circular deps at module load
        from self_healing.policy_gate import SysPolic, PolicyDenied

        action: dict = {"type": action_type}
        if target:
            action["target"] = target
        if model:
            action["model"] = model

        poli = SysPolic()
        try:
            poli.allow(action)
            return _json({"allowed": True, "reason": "action is in SAFE_ACTIONS whitelist"})
        except PolicyDenied as e:
            return _json({"allowed": False, "reason": str(e)})
    except ImportError:
        # Fallback: inline the same logic
        SAFE = {"restart_container", "switch_model", "clear_queue",
                "reload_config", "pause_worker", "resume_worker"}
        DANGEROUS = {"delete_db", "exec_shell", "wipe_storage",
                     "drop_table", "rm_rf", "push_to_prod"}
        RESTARTABLE = {"axi-bot", "omi-bot", "argus-bot", "logi-bot", "aims-api", "aims-worker",
                       "aims-orchestrator", "queue-api", "task-registry", "doc-agent", "knomi-agent",
                       "poli-agent", "mainy-repair-agent", "omi-api", "qdrant", "aims-redis", "schedule"}

        if action_type in DANGEROUS:
            return _json({"allowed": False, "reason": f"'{action_type}' is DANGEROUS"})
        if action_type == "restart_container" and target not in RESTARTABLE:
            return _json({"allowed": False,
                          "reason": f"container '{target}' not in RESTARTABLE_CONTAINERS"})
        if action_type == "switch_model" and not model:
            return _json({"allowed": False, "reason": "switch_model requires 'model' field"})
        if action_type not in SAFE:
            return _json({"allowed": False,
                          "reason": f"'{action_type}' not in SAFE_ACTIONS whitelist"})
        return _json({"allowed": True, "reason": "action is in SAFE_ACTIONS whitelist"})


# ─────────────────────────────────────────────────────────────────────────
# MainyRepairAgent — runtime repair executor
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def mainy_repair(
    action_type: str,
    target: str = "",
    model: str = "",
) -> str:
    """Execute a runtime repair action via MainyRepairAgent.

    Goes through PoliAgent gate automatically — denied actions are NOT executed.
    Claude Code PROPOSES; Mainy EXECUTES. Never call this without prior reasoning.

    Args:
        action_type: restart_container | switch_model | clear_queue |
                     reload_config | pause_worker | resume_worker
        target:      Target name (container / worker).
        model:       New model name (for switch_model only).
    Returns:
        JSON with ok (bool), action, detail.
    """
    # Explicit policy gate before any execution
    gate = json.loads(poli_check(action_type=action_type, target=target, model=model))
    if not gate.get("allowed"):
        return _json({"ok": False, "action": action_type,
                      "detail": f"DENIED by PoliAgent: {gate.get('reason')}"})

    try:
        from self_healing.repair_executor import RepairExecutor
        from self_healing.policy_gate import PolicyDenied

        action: dict = {"type": action_type}
        if target:
            action["target"] = target
        if model:
            action["model"] = model

        executor = RepairExecutor()
        try:
            result = executor.execute(action)
            return _json(result)
        except PolicyDenied as e:
            return _json({"ok": False, "action": action_type,
                          "detail": f"DENIED by PoliAgent: {e}"})
    except ImportError as exc:
        return _json({"ok": False, "error": f"RepairExecutor not importable: {exc}",
                      "hint": "Run from aims-workspace/ops/ directory"})


# ─────────────────────────────────────────────────────────────────────────
# TrainiAgent — fine-tuning lifecycle
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def traini_status() -> str:
    """Get fine-tuning pipeline status (TrainiAgent).

    Returns:
        JSON with current model queue, last eval scores, pending training pairs.
    """
    state_dir = _HERE / "ft" / "state"
    data: dict = {}

    # model registry
    reg_file = state_dir / "model_registry.json"
    if reg_file.exists():
        try:
            data["model_registry"] = json.loads(reg_file.read_text())
        except Exception:
            data["model_registry"] = "unreadable"

    # count pending training pairs
    pairs_dir = _HERE.parent / "aims_workspace" / "training" / "quality_pairs"
    if pairs_dir.exists():
        data["pending_pairs"] = len(list(pairs_dir.glob("*.json")))
    else:
        data["pending_pairs"] = 0

    # last eval file
    eval_files = sorted((_HERE / "ft").glob("eval_*.json"))
    if eval_files:
        try:
            last = json.loads(eval_files[-1].read_text())
            data["last_eval"] = {
                "file": eval_files[-1].name,
                "pass_rate": last.get("pass_rate"),
                "version": last.get("version"),
            }
        except Exception:
            data["last_eval"] = eval_files[-1].name

    data["ok"] = True
    return _json(data)


@mcp.tool()
def traini_trigger(force: bool = False) -> str:
    """Trigger a fine-tuning cycle (TrainiAgent).

    Only triggers if conditions are met (GPU temp, pending pairs, eval score)
    unless force=True.

    Args:
        force: Skip readiness checks and trigger immediately.
    Returns:
        JSON with triggered (bool), version, reason.
    """
    try:
        ft_dir = _HERE / "ft"
        workers_dir = _HERE / "workers"

        # try importing ft_pipeline
        for d in [workers_dir, ft_dir]:
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))

        from ft_pipeline import maybe_trigger

        store: dict = {}
        try:
            result = maybe_trigger(store, run_id=None, force=force)
        except TypeError:
            result = maybe_trigger(store, run_id=None)
            result["force_requested"] = force
        return _json(result)
    except ImportError as exc:
        return _json({"ok": False, "triggered": False,
                      "reason": f"ft_pipeline not importable: {exc}"})
    except Exception as exc:
        return _json({"ok": False, "triggered": False, "reason": str(exc)})


# ─────────────────────────────────────────────────────────────────────────
# Task Registry (cross-cutting — used by all agents)
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool()
def task_list(
    limit: int = 20,
    status: str = "",
) -> str:
    """List recent tasks from AIMS Task Registry.

    Args:
        limit:  Max results (default 20).
        status: Filter by status: pending | in_progress | done | stuck | failed.
    Returns:
        JSON list of tasks.
    """
    url = f"{_TASK_REG_URL}/tasks?limit={limit}"
    if status:
        url += f"&status={status}"
    result = _http("GET", url)
    return _json(result)


@mcp.tool()
def task_register(
    source: str,
    intent: str,
    priority: int = 5,
    payload: str = "",
) -> str:
    """Register a new task in AIMS Task Registry.

    Args:
        source:   Who is creating the task (e.g. 'nemoclaw', 'argus', 'axi').
        intent:   Task description / intent string.
        priority: Priority 1-10 (default 5).
        payload:  Optional JSON payload as string.
    Returns:
        JSON with task_id, status.
    """
    body: dict = {"source": source, "intent": intent, "priority": priority}
    if payload:
        try:
            body["payload"] = json.loads(payload)
        except Exception:
            body["payload"] = payload
    result = _http("POST", f"{_TASK_REG_URL}/tasks", body)
    return _json(result)


# ─────────────────────────────────────────────────────────────────────────
# Entry point
# ─��───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
