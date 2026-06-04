"""
AIMS Self-Learning — Skill Candidate Workflow.

Orchestrates: load fixtures → validate patterns → generate candidates →
validate candidates → write JSON output. No model calls, no runtime changes.
"""
from __future__ import annotations

import datetime
import json
import pathlib
from typing import Any

from .observed_pattern_schema import ObservedPattern
from .skill_candidate_generator import generate_candidates
from .skill_candidate_validator import PatternValidator, CandidateValidator
from .skill_candidate_schema import (
    CANDIDATE_STATUS_READY,
    CANDIDATE_STATUS_REVIEW,
    CANDIDATE_STATUS_REJECTED,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "ops" / "evals" / "fixtures" / "self_learning"
_OUTPUT_DIR = _REPO_ROOT / "aims_workspace" / "self_learning"
_JSON_OUTPUT = _OUTPUT_DIR / "generated_candidate_skills.json"

_FIXTURE_FILES = (
    _FIXTURE_DIR / "repeated_document_task_patterns.json",
    _FIXTURE_DIR / "repeated_repair_task_patterns.json",
    _FIXTURE_DIR / "rejected_unsafe_patterns.json",
)

_NEXT_PHASE = "AIMS_SANDBOX_SKILL_PLAN_WORKFLOW"


def _load_fixtures() -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    for path in _FIXTURE_FILES:
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            patterns.extend(data)
        elif isinstance(data, dict) and "patterns" in data:
            patterns.extend(data["patterns"])
        else:
            raise ValueError(f"Unexpected fixture format in {path}")
    return patterns


def run_candidate_workflow() -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Load all patterns from fixtures
    raw_patterns = _load_fixtures()

    # Validate each pattern
    pval = PatternValidator()
    valid_patterns: list[dict[str, Any]] = []
    pattern_errors: list[dict[str, Any]] = []
    for p in raw_patterns:
        if pval.validate(p):
            valid_patterns.append(p)
        else:
            pattern_errors.append({"pattern_id": p.get("pattern_id"), "errors": pval.errors})

    # Generate candidates from valid patterns
    candidates = generate_candidates(valid_patterns)

    # Validate each generated candidate
    cval = CandidateValidator()
    candidate_dicts: list[dict[str, Any]] = []
    candidate_errors: list[dict[str, Any]] = []
    candidate_warnings: list[str] = []
    for c in candidates:
        d = c.to_dict()
        if cval.validate(d):
            candidate_dicts.append(d)
        else:
            candidate_errors.append({"skill_id": d.get("skill_id"), "errors": cval.errors})
            candidate_dicts.append(d)  # include even invalid for visibility
        candidate_warnings.extend(cval.warnings)

    # Tally statuses
    ready = [c for c in candidate_dicts if c.get("candidate_status") == CANDIDATE_STATUS_READY]
    review = [c for c in candidate_dicts if c.get("candidate_status") == CANDIDATE_STATUS_REVIEW]
    rejected = [c for c in candidate_dicts if c.get("candidate_status") == CANDIDATE_STATUS_REJECTED]

    result: dict[str, Any] = {
        "phase": "7",
        "created_at": created_at,
        "total_patterns_loaded": len(raw_patterns),
        "patterns_valid": len(valid_patterns),
        "patterns_invalid": len(pattern_errors),
        "pattern_errors": pattern_errors,
        "total_candidates": len(candidate_dicts),
        "candidates_ready": len(ready),
        "candidates_needs_review": len(review),
        "candidates_rejected": len(rejected),
        "candidate_errors": candidate_errors,
        "candidate_warnings": candidate_warnings,
        "candidates": candidate_dicts,
        "workflow_valid": len(pattern_errors) == 0 and len(candidate_errors) == 0,
        "next_allowed_phase": _NEXT_PHASE,
    }

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _JSON_OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    result["report_json"] = str(_JSON_OUTPUT)
    return result


if __name__ == "__main__":
    r = run_candidate_workflow()
    print("=" * 60)
    print("AIMS Phase 7 — Skill Candidate Workflow")
    print("=" * 60)
    print(f"Patterns loaded  : {r['total_patterns_loaded']}")
    print(f"Patterns valid   : {r['patterns_valid']}")
    print(f"Candidates total : {r['total_candidates']}")
    print(f"  READY          : {r['candidates_ready']}")
    print(f"  NEEDS_REVIEW   : {r['candidates_needs_review']}")
    print(f"  REJECTED       : {r['candidates_rejected']}")
    print(f"Workflow valid   : {r['workflow_valid']}")
    print(f"Next phase       : {r['next_allowed_phase']}")
    print(f"JSON             : {r['report_json']}")
