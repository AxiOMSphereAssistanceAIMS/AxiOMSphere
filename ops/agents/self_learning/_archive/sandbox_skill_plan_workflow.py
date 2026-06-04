"""
AIMS Self-Learning — Sandbox Skill Plan Workflow.

Orchestrates: load candidate JSON → filter READY candidates →
generate plans → validate plans → write JSON output.
No model calls, no runtime changes.
"""
from __future__ import annotations

import datetime
import json
import pathlib
from typing import Any

from .sandbox_skill_plan_generator import generate_plans
from .sandbox_skill_plan_validator import SandboxSkillPlanValidator
from .skill_candidate_schema import CANDIDATE_STATUS_READY

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_CANDIDATE_JSON = (
    _REPO_ROOT / "aims_workspace" / "self_learning" / "generated_candidate_skills.json"
)
_OUTPUT_DIR = _REPO_ROOT / "aims_workspace" / "self_learning"
_JSON_OUTPUT = _OUTPUT_DIR / "generated_sandbox_skill_plans.json"

_NEXT_PHASE = "AIMS_SANDBOX_SKILL_EXECUTION_HARNESS"


def _load_candidates() -> list[dict[str, Any]]:
    if not _CANDIDATE_JSON.exists():
        raise FileNotFoundError(
            f"Candidate skills JSON not found: {_CANDIDATE_JSON}\n"
            "Run Phase 7 (aims_skill_candidate_workflow_smoke.py) first."
        )
    data = json.loads(_CANDIDATE_JSON.read_text(encoding="utf-8"))
    return data.get("candidates", [])


def run_plan_workflow() -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    all_candidates = _load_candidates()
    ready_candidates = [
        c for c in all_candidates
        if c.get("candidate_status") == CANDIDATE_STATUS_READY
    ]

    plans = generate_plans(ready_candidates)

    validator = SandboxSkillPlanValidator()
    plan_dicts: list[dict[str, Any]] = []
    plan_errors: list[dict[str, Any]] = []
    plan_warnings: list[str] = []

    for plan in plans:
        d = plan.to_dict()
        if validator.validate(d):
            plan_dicts.append(d)
        else:
            plan_errors.append({"plan_id": d.get("plan_id"), "errors": validator.errors})
            plan_dicts.append(d)
        plan_warnings.extend(validator.warnings)

    result: dict[str, Any] = {
        "phase": "8",
        "created_at": created_at,
        "total_candidates_input": len(all_candidates),
        "ready_candidates": len(ready_candidates),
        "total_plans_generated": len(plan_dicts),
        "plans_valid": len([d for d in plan_dicts if d not in [e["plan_id"] for e in plan_errors]]),
        "plan_errors": plan_errors,
        "plan_warnings": plan_warnings,
        "plans": plan_dicts,
        "workflow_valid": len(plan_errors) == 0,
        "next_allowed_phase": _NEXT_PHASE,
    }

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _JSON_OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    result["report_json"] = str(_JSON_OUTPUT)
    return result


if __name__ == "__main__":
    r = run_plan_workflow()
    print("=" * 60)
    print("AIMS Phase 8 — Sandbox Skill Plan Workflow")
    print("=" * 60)
    print(f"Candidates input   : {r['total_candidates_input']}")
    print(f"Ready candidates   : {r['ready_candidates']}")
    print(f"Plans generated    : {r['total_plans_generated']}")
    print(f"Workflow valid     : {r['workflow_valid']}")
    print(f"Next phase         : {r['next_allowed_phase']}")
    print(f"JSON               : {r['report_json']}")
