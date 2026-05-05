"""SupervisorAgent — port 8009.

HTTP service wrapping the factory SupervisedPipeline and AgentTestRunner.

Endpoints:
  POST /run              run supervised pipeline, block until done
  POST /test/{agent}     run fixture tests for one agent
  POST /test/all         run all agent fixture tests (~2-3 min)
  GET  /task/{task_id}   fetch supervision report
  GET  /health           service health
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.service_auth import service_headers
from factory.supervisor import SupervisedPipeline, SupervisionReport
from factory.test_runner import AgentTestRunner, TestReport

log = logging.getLogger("aims.agents.supervisor")

app = FastAPI(title="SupervisorAgent", version="1.0.0")

# In-memory task store
_tasks: dict[str, SupervisionReport] = {}
_lock  = threading.Lock()

KNOMI_URL  = "http://localhost:8002/search"
DOCI_URL   = "http://localhost:8001/compose_and_generate"
CLOUD_URL  = "http://localhost:8003/validate"
POLI_URL   = "http://localhost:8004/check"
OMI_URL    = "http://localhost:8008/documents"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SupervisedTaskRequest(BaseModel):
    content:  str  = Field(..., description="User request / document scope")
    doc_type: str  = Field("procedure", description="procedure | policy | work_instruction")
    task_id:  str  = Field(default_factory=lambda: uuid.uuid4().hex[:12])


class SupervisedTaskResponse(BaseModel):
    task_id:    str
    status:     str
    doc_path:   str | None = None
    doc_id:     str | None = None
    quality_score: float | None = None
    report_url: str


# ---------------------------------------------------------------------------
# Low-level tool caller (synchronous, httpx)
# ---------------------------------------------------------------------------

def _call(url: str, payload: dict, timeout: float = 120.0) -> dict:
    try:
        resp = httpx.post(url, json=payload, headers=service_headers(), timeout=timeout)
        data = resp.json()
        if resp.status_code >= 400:
            return {"error": f"HTTP {resp.status_code}: {data}"}
        return data
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Context filter (in-process, no HTTP)
# ---------------------------------------------------------------------------

def _context_filter(raw_results: list[dict], task_id: str, user_request: str) -> list[dict]:
    """Simple relevance pass — keep top 10 results, strip low-score entries."""
    filtered = [r for r in raw_results if isinstance(r, dict)]
    filtered = sorted(filtered, key=lambda r: r.get("score", 0.0), reverse=True)
    return filtered[:10]


# ---------------------------------------------------------------------------
# /run
# ---------------------------------------------------------------------------

@app.post("/run", response_model=SupervisedTaskResponse)
def run_supervised_task(req: SupervisedTaskRequest) -> SupervisedTaskResponse:
    task_id = req.task_id
    _state: dict[str, Any] = {}

    def step_knomi() -> dict:
        r = _call(KNOMI_URL, {"query": req.content, "top_k": 20})
        if "error" not in r:
            _state["knomi_results"] = r.get("results", [])
        return r

    def step_filter() -> dict:
        raw = _state.get("knomi_results", [])
        filtered = _context_filter(raw, task_id, req.content)
        _state["filtered_docs"] = filtered
        return {"filtered": filtered}

    def step_doci() -> dict:
        r = _call(DOCI_URL, {
            "task_id":      task_id,
            "user_request": req.content,
            "doc_type":     req.doc_type,
            "filtered_docs": _state.get("filtered_docs", []),
        })
        if "error" not in r:
            _state["doci_result"] = r
        return r

    def step_cloud_validate() -> dict:
        doci = _state.get("doci_result", {})
        doc_text = doci.get("preview", "") or doci.get("document_text", "")
        r = _call(CLOUD_URL, {
            "task_id":       task_id,
            "user_request":  req.content,
            "document_text": doc_text,
            "doc_path":      doci.get("doc_path", ""),
            "doc_type":      req.doc_type,
        })
        if "error" not in r:
            _state["cloud_result"] = r
        return r

    def step_poli() -> dict:
        doci = _state.get("doci_result", {})
        r = _call(POLI_URL, {
            "action_type": "write_document",
            "params": {
                "type":        "write_document",
                "target":      doci.get("doc_path", ""),
                "doc_type":    req.doc_type,
                "quality_score": _state.get("cloud_result", {}).get("quality_score"),
            },
            "requester":  "supervisor_pipeline",
            "department": "system",
        })
        if "error" not in r and not r.get("allowed", False):
            return {"error": f"policy_denied: {r.get('reason', 'no reason')}"}
        return r

    def step_omi_store() -> dict:
        doci  = _state.get("doci_result", {})
        cloud = _state.get("cloud_result", {})
        r = _call(OMI_URL, {
            "task_id":      task_id,
            "title":        req.content[:120],
            "doc_type":     req.doc_type,
            "status":       "master",
            "quality_score": cloud.get("quality_score"),
            "file_path":    doci.get("doc_path", ""),
            "summary":      doci.get("preview", "")[:500] if doci.get("preview") else "",
        })
        if "error" not in r:
            _state["omi_result"] = r
        return r

    pipeline = SupervisedPipeline(task_id=task_id)
    report   = pipeline.run([
        ("knomi_search",    step_knomi),
        ("context_filter",  step_filter),
        ("doci_compose",    step_doci),
        ("cloud_validate",  step_cloud_validate),
        ("poli_check",      step_poli),
        ("omi_store",       step_omi_store),
    ])

    with _lock:
        _tasks[task_id] = report

    doci_r  = _state.get("doci_result", {})
    cloud_r = _state.get("cloud_result", {})
    omi_r   = _state.get("omi_result", {})

    return SupervisedTaskResponse(
        task_id=task_id,
        status=report.status,
        doc_path=doci_r.get("doc_path"),
        doc_id=omi_r.get("doc_id"),
        quality_score=cloud_r.get("quality_score"),
        report_url=f"http://localhost:8009/task/{task_id}",
    )


# ---------------------------------------------------------------------------
# /test/{agent}  and  /test/all
# ---------------------------------------------------------------------------

class AgentTestResponse(BaseModel):
    agent:     str
    total:     int
    passed:    int
    failed:    int
    pass_rate: float
    results:   list[dict]
    run_at:    str


class AllTestsResponse(BaseModel):
    reports:     dict[str, dict]
    total:       int
    total_passed: int
    overall_pass_rate: float


@app.post("/test/all", response_model=AllTestsResponse)
def test_all() -> AllTestsResponse:
    runner  = AgentTestRunner()
    reports = runner.run_all()

    total        = sum(r.total  for r in reports.values())
    total_passed = sum(r.passed for r in reports.values())

    return AllTestsResponse(
        reports={agent: r.to_dict() for agent, r in reports.items()},
        total=total,
        total_passed=total_passed,
        overall_pass_rate=round(total_passed / total, 3) if total else 0.0,
    )


@app.post("/test/{agent}", response_model=AgentTestResponse)
def test_agent(agent: str) -> AgentTestResponse:
    runner = AgentTestRunner()
    report = runner.run_agent(agent)
    d = report.to_dict()
    return AgentTestResponse(**d)


# ---------------------------------------------------------------------------
# /task/{task_id}
# ---------------------------------------------------------------------------

@app.get("/task/{task_id}")
def get_task(task_id: str) -> dict:
    with _lock:
        report = _tasks.get(task_id)
    if not report:
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "task_id":             report.task_id,
        "status":              report.status,
        "started_at":          report.started_at,
        "finished_at":         report.finished_at,
        "step_results":        [s.to_dict() for s in report.step_results],
        "repairs":             report.repairs,
        "health_timeline":     report.health_timeline,
        "training_pair_saved": report.training_pair_saved,
        "final_result":        report.final_result,
    }


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    with _lock:
        tracked = len(_tasks)
    return {"status": "ok", "tasks_tracked": tracked}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8009, log_level="info")
