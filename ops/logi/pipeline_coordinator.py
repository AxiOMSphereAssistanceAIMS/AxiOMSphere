"""PipelineCoordinator — Stateless coordinator for AIMS Document Factory V2.

Coordinates the 7-step document pipeline and the self-healing loop.
Uses Tool Registry to call all agents. Applies Context Filter before DociAgent.

NOT an LLM itself — pure FastAPI service that routes and coordinates.
NemoClaw (Nemotron 120B) is the reasoning layer that calls this coordinator.
ConversationalOrchestrator (Qwen3:14b) handles interactive chat workflows.
"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

# Allow imports from parent ops/ directory when run directly
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from logi.context_filter import context_filter
from logi.tool_registry import TOOL_REGISTRY, call_tool

try:
    from factory.supervisor import SupervisedPipeline  # noqa: F401
    _FACTORY_AVAILABLE = True
except ImportError:
    _FACTORY_AVAILABLE = False

log = logging.getLogger("aims.pipeline_coordinator")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(title="PipelineCoordinator", version="2.0.0")


# ── request / response models ──────────────────────────────────────────────────

class TaskRequest(BaseModel):
    # required
    content: str
    # optional with sensible defaults
    doc_type: str = "procedure"
    department: str = "operations"
    requester: str = "axi_client"
    # allow arbitrary extra fields (metadata, context, etc.)
    model_config = {"extra": "allow"}


class HealthEventRequest(BaseModel):
    source: str = "unknown"
    level: str = "INFO"
    type: str = "unknown"
    service: str | None = None
    health_score: int | None = None
    services: dict | None = None
    timestamp: str | None = None
    model_config = {"extra": "allow"}


class TrainingMetricsRequest(BaseModel):
    training_pairs: int = 0
    eval_quality: float = 100.0
    corrections: int = 0
    model_config = {"extra": "allow"}


# ── orchestrator class ─────────────────────────────────────────────────────────

class PipelineCoordinator:
    """Core V2 stateless pipeline coordinator.

    Coordinates the 7-step document pipeline and the self-healing repair loop.
    Pure routing logic — no LLM reasoning.
    """

    def __init__(self) -> None:
        self.tool_registry = TOOL_REGISTRY
        log.info("PipelineCoordinator initialised with %d tools", len(self.tool_registry))

    # ── document pipeline ──────────────────────────────────────────────────────

    def handle_task(self, task: dict) -> dict:
        """Run the 7-step document factory pipeline.

        Step 1 — KnomiSearch: retrieve relevant knowledge chunks
        Step 2 — ContextFilter: filter to approved, high-quality, type-matched docs
        Step 3 — DociCompose: generate the document using Nemotron 120B
        Step 4 — CloudValidate: quality gate via DeepSeek-R1:672B
        Step 5 — PoliCheck: policy approval for writing to master registry
        Step 6 — OmiStore: persist to master registry
        Step 7 — Return success payload
        """
        log.info(
            "handle_task content_len=%d doc_type=%s department=%s requester=%s",
            len(str(task.get("content", ""))),
            task.get("doc_type"),
            task.get("department"),
            task.get("requester"),
        )

        # Step 1: Knowledge retrieval
        log.info("step 1 — knomi_search")
        knomi_result = call_tool("knomi_search", {"query": task["content"], "top_k": 20})
        if "error" in knomi_result:
            log.error("step 1 failed: %s", knomi_result["error"])
            return {"status": "error", "step": 1, "detail": knomi_result["error"]}

        # Step 2: Context filtering
        log.info("step 2 — context_filter")
        raw_results = knomi_result.get("results", [])
        filtered_docs = context_filter(raw_results, task)
        log.info("step 2 — filtered %d → %d docs", len(raw_results), len(filtered_docs))

        # Step 3: Document composition
        log.info("step 3 — doci_compose")
        doc_result = call_tool("doci_compose", {
            "task_id": str(uuid.uuid4()),
            "user_request": task.get("content", ""),
            "doc_type": task.get("doc_type", "procedure"),
            "filtered_docs": filtered_docs,
            "industry": task.get("industry"),
        })
        if "error" in doc_result:
            log.error("step 3 failed: %s", doc_result["error"])
            return {"status": "error", "step": 3, "detail": doc_result["error"]}

        # Step 4: Cloud validation / quality gate
        log.info("step 4 — cloud_validate")
        validation = call_tool(
            "cloud_validate",
            {
                "task_id": doc_result.get("task_id", str(uuid.uuid4())),
                "user_request": task.get("content", ""),
                "document_text": doc_result.get("preview", ""),
                "doc_path": doc_result.get("doc_path"),
                "doc_type": task.get("doc_type", "procedure"),
            },
        )
        if "error" in validation:
            log.error("step 4 failed: %s", validation["error"])
            return {"status": "error", "step": 4, "detail": validation["error"]}

        # cloud_validate returns overall_status: APPROVED | TRAINING_PAIR | RETRY
        overall_status = validation.get("overall_status", "")
        log.info("step 4 overall_status=%s quality_score=%s", overall_status, validation.get("quality_score"))

        if overall_status == "RETRY":
            log.warning("validation RETRY — returning gap report")
            return {
                "status": "gap_report",
                "gaps": validation.get("compliance", {}).get("gaps", []),
                "doc": doc_result,
            }

        if overall_status == "TRAINING_PAIR":
            log.info("validation TRAINING_PAIR — storing pair and returning")
            call_tool("omi_store", {"document": doc_result, "status": "training_pair"})
            return {"status": "training_pair_saved"}

        # APPROVED — proceed to step 5
        if overall_status != "APPROVED":
            log.warning("unexpected overall_status='%s' — treating as RETRY", overall_status)
            return {
                "status": "gap_report",
                "gaps": [f"unexpected_status:{overall_status}"],
                "doc": doc_result,
            }

        # Step 5: Policy check before writing to master
        log.info("step 5 — poli_check")
        poli = call_tool(
            "poli_check",
            {
                "action_type": "write_document",
                "params": {"department": task.get("department", "operations")},
                "requester": task.get("requester", "axi_client"),
                "department": task.get("department", "operations"),
            },
        )
        if "error" in poli:
            log.error("step 5 failed: %s", poli["error"])
            return {"status": "error", "step": 5, "detail": poli["error"]}

        if not poli.get("allowed", False):
            log.warning("step 5 — blocked by policy: %s", poli.get("reason"))
            return {"status": "blocked_by_policy", "reason": poli["reason"]}

        # Step 6: Store as master document
        log.info("step 6 — omi_store (master)")
        call_tool(
            "omi_store",
            {
                "document": doc_result,
                "status": "master",
                "audit_id": poli.get("audit_id", ""),
            },
        )

        # Step 7: Return success
        log.info("handle_task complete — success")
        return {
            "status": "success",
            "document": doc_result,
            "quality_score": validation.get("quality_score"),
            "overall_status": overall_status,
            "compliance": validation.get("compliance"),
        }

    # ── self-healing loop ──────────────────────────────────────────────────────

    def on_health_event(self, event: dict) -> dict:
        """Handle a health event emitted by ArgusAgent.

        Routes to RepairmanAPI for automated diagnosis and repair.
        Critical events trigger repairman_fix, warnings trigger repairman_inspect.
        All actions require PoliAgent approval (handled by RepairmanAPI).
        """
        level = event.get("level", "")
        etype = event.get("type", "")
        source = event.get("source", "argus_agent")
        health_score = event.get("health_score", 100)
        services = event.get("services", {})

        log.info("on_health_event level=%s type=%s health_score=%d", level, etype, health_score)

        # Determine repairman mode based on severity
        if level == "CRITICAL":
            mode = "fix"
            task = f"CRITICAL health event: {etype}\nHealth score: {health_score}\nServices: {services}\nRestore system operability."
        elif level == "WARNING":
            mode = "inspect"
            task = f"WARNING health event: {etype}\nHealth score: {health_score}\nServices: {services}\nInspect and diagnose issues."
        else:
            log.info("non-critical event, no action needed")
            return {"repair_dispatched": False, "reason": "non_critical_event"}

        # Call RepairmanAPI
        result = call_tool(
            "repairman_trigger",
            {
                "task": task,
                "mode": mode,
                "source": source,
            },
        )

        if "error" in result:
            log.error("repairman_trigger failed: %s", result["error"])
            return {"repair_dispatched": False, "reason": result["error"]}

        log.info("repairman dispatched: mode=%s status=%s", mode, result.get("status"))
        return {"repair_dispatched": True, "result": result}

    # ── training trigger ───────────────────────────────────────────────────────

    def check_training_triggers(self, metrics: dict) -> dict:
        """Check if accumulated metrics warrant triggering a fine-tuning cycle.

        Triggers when any of:
        - training_pairs >= 50
        - eval_quality < 82
        - corrections >= 50
        """
        training_pairs = metrics.get("training_pairs", 0)
        eval_quality = metrics.get("eval_quality", 100)
        corrections = metrics.get("corrections", 0)

        should_trigger = (
            training_pairs >= 50
            or eval_quality < 82
            or corrections >= 50
        )

        if should_trigger:
            log.info(
                "training trigger met: pairs=%d eval_quality=%.1f corrections=%d",
                training_pairs, eval_quality, corrections,
            )
            result = call_tool(
                "traini_trigger",
                {"reason": "threshold_met", "metrics": metrics},
            )
            return {"triggered": True, "result": result}

        log.debug(
            "no training trigger: pairs=%d eval_quality=%.1f corrections=%d",
            training_pairs, eval_quality, corrections,
        )
        return {"triggered": False}


# ── shared orchestrator instance ───────────────────────────────────────────────

_coordinator = PipelineCoordinator()


# ── FastAPI endpoints ──────────────────────────────────────────────────────────

@app.post("/task")
def task_endpoint(req: TaskRequest) -> dict:
    """Run the 7-step document factory pipeline."""
    task = req.model_dump()
    return _coordinator.handle_task(task)


@app.post("/supervised_task")
def supervised_task_endpoint(req: TaskRequest) -> dict:
    """Run pipeline via SupervisedPipeline factory (with monitor + repair)."""
    if not _FACTORY_AVAILABLE:
        return _coordinator.handle_task(req.model_dump())
    from agents.supervisor_agent import run_supervised_task, SupervisedTaskRequest
    sr = SupervisedTaskRequest(**req.model_dump())
    return run_supervised_task(sr).model_dump()


@app.post("/health_event")
def health_event_endpoint(event: HealthEventRequest) -> dict:
    """Receive a health event from ArgusAgent and dispatch repair if needed."""
    return _coordinator.on_health_event(event.model_dump())


@app.post("/check_training")
def check_training_endpoint(metrics: TrainingMetricsRequest) -> dict:
    """Check training thresholds and trigger fine-tuning if warranted."""
    return _coordinator.check_training_triggers(metrics.model_dump())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "pipeline_coordinator", "port": 8000}


@app.get("/status")
def status() -> dict:
    return {"status": "ok", "version": "v2"}


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "pipeline_coordinator:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )
