"""
AIMS Self-Learning — Sandbox Execution Workflow.

Orchestrates Phase 9: load Phase 8 plans → match fixture inputs →
run dry-run executions via harness → validate results → write reports.
No model calls, no runtime changes.
"""
from __future__ import annotations

import datetime
import json
import pathlib
from typing import Any

from .sandbox_execution_harness import run_execution
from .sandbox_execution_schema import (
    EXEC_STATUS_PASS,
    EXEC_STATUS_REJECTED,
    SandboxExecutionRequest,
)
from .sandbox_execution_validator import SandboxExecutionValidator

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_PLANS_JSON = (
    _REPO_ROOT / "aims_workspace" / "self_learning" / "generated_sandbox_skill_plans.json"
)
_FIXTURES_DIR = (
    _REPO_ROOT / "ops" / "evals" / "fixtures" / "self_learning" / "sandbox_execution_inputs"
)
_OUTPUT_DIR = _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "sandbox_runs"
_JSON_OUTPUT = _OUTPUT_DIR / "sandbox_execution_report.json"
_MD_OUTPUT = _OUTPUT_DIR / "sandbox_execution_report.md"
_EVIDENCE_OUTPUT = _OUTPUT_DIR / "sandbox_execution_evidence_pack.json"

_NEXT_PHASE = "AIMS_SANDBOX_SKILL_CERTIFICATION"

# Fixture assignments: skill_id suffix → fixture filename
_FIXTURE_MAP = {
    "doc-draft-rewrite-cycle": "document_qa_sample_input.txt",
    "subagent-task-decomposition": "document_qa_sample_input.txt",
    "ocr-extract-index-sync": "document_qa_sample_input.txt",
    "argus-systematic-debug-loop": "repair_diagnosis_sample_log.txt",
    "tdd-smoke-before-promote": "repair_diagnosis_sample_log.txt",
    "codebase-inspect-before-pr": "repair_diagnosis_sample_log.txt",
    "lm-eval-quality-gate": "model_readiness_sample_eval.json",
    "vllm-serving-readiness-check": "model_readiness_sample_eval.json",
}
_DEFAULT_FIXTURE = "document_qa_sample_input.txt"


def _resolve_fixture(skill_id: str) -> str:
    for key, fname in _FIXTURE_MAP.items():
        if key in skill_id:
            return str(_FIXTURES_DIR / fname)
    return str(_FIXTURES_DIR / _DEFAULT_FIXTURE)


def _load_plans() -> list[dict[str, Any]]:
    if not _PLANS_JSON.exists():
        raise FileNotFoundError(
            f"Sandbox skill plans JSON not found: {_PLANS_JSON}\n"
            "Run Phase 8 (aims_sandbox_skill_plan_workflow_smoke.py) first."
        )
    data = json.loads(_PLANS_JSON.read_text(encoding="utf-8"))
    return data.get("plans", [])


def _write_md_report(result_data: dict[str, Any]) -> None:
    lines = [
        "# AIMS Phase 9 — Sandbox Execution Report",
        "",
        f"**Generated:** {result_data['created_at']}",
        f"**Plans executed:** {result_data['total_executions']}",
        f"**PASS:** {result_data['pass_count']}",
        f"**WARN:** {result_data['warn_count']}",
        f"**FAIL:** {result_data['fail_count']}",
        f"**REJECTED:** {result_data['rejected_count']}",
        f"**Workflow valid:** {result_data['workflow_valid']}",
        f"**Next phase:** {result_data['next_allowed_phase']}",
        "",
        "## Execution Results",
        "",
    ]
    for r in result_data.get("results", []):
        status = r.get("status", "UNKNOWN")
        icon = "✅" if status == "SANDBOX_PASS" else ("⚠️" if status == "SANDBOX_WARN" else "❌")
        lines.append(f"### {icon} {r.get('execution_id')} — {r.get('skill_id')}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Plan:** {r.get('plan_id')}")
        lines.append(f"- **Secrets detected:** {not r.get('no_secrets_detected', True)}")
        if r.get("assertion_failures"):
            lines.append(f"- **Failures:** {r['assertion_failures']}")
        lines.append("")

    _MD_OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def run_execution_workflow() -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    plans = _load_plans()

    validator = SandboxExecutionValidator()
    results: list[dict[str, Any]] = []
    result_errors: list[dict[str, Any]] = []
    evidence_pack: dict[str, Any] = {}

    for plan in plans:
        fixture_path = _resolve_fixture(plan.get("skill_id", ""))
        request = SandboxExecutionRequest.from_plan(plan, fixture_path)
        result = run_execution(request, plan)
        result_dict = result.to_dict()

        if validator.validate(result_dict):
            results.append(result_dict)
        else:
            result_errors.append({
                "execution_id": result_dict.get("execution_id"),
                "errors": validator.errors,
            })
            results.append(result_dict)

        evidence_pack[result.execution_id] = result.evidence_pack

    pass_count = sum(1 for r in results if r.get("status") == EXEC_STATUS_PASS)
    warn_count = sum(1 for r in results if r.get("status") == "SANDBOX_WARN")
    fail_count = sum(1 for r in results if r.get("status") == "SANDBOX_FAIL")
    rejected_count = sum(1 for r in results if r.get("status") == EXEC_STATUS_REJECTED)

    output: dict[str, Any] = {
        "phase": "9",
        "created_at": created_at,
        "total_plans_input": len(plans),
        "total_executions": len(results),
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "rejected_count": rejected_count,
        "result_errors": result_errors,
        "workflow_valid": len(result_errors) == 0 and fail_count == 0 and rejected_count == 0,
        "next_allowed_phase": _NEXT_PHASE,
        "results": results,
    }

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _JSON_OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    _EVIDENCE_OUTPUT.write_text(json.dumps(evidence_pack, indent=2, ensure_ascii=False))
    _write_md_report(output)

    output["report_json"] = str(_JSON_OUTPUT)
    output["report_md"] = str(_MD_OUTPUT)
    output["evidence_json"] = str(_EVIDENCE_OUTPUT)
    return output


if __name__ == "__main__":
    r = run_execution_workflow()
    print("=" * 60)
    print("AIMS Phase 9 — Sandbox Execution Workflow")
    print("=" * 60)
    print(f"Plans input        : {r['total_plans_input']}")
    print(f"Executions         : {r['total_executions']}")
    print(f"PASS               : {r['pass_count']}")
    print(f"WARN               : {r['warn_count']}")
    print(f"FAIL               : {r['fail_count']}")
    print(f"REJECTED           : {r['rejected_count']}")
    print(f"Workflow valid     : {r['workflow_valid']}")
    print(f"Next phase         : {r['next_allowed_phase']}")
    print(f"JSON               : {r['report_json']}")
    print(f"MD                 : {r['report_md']}")
