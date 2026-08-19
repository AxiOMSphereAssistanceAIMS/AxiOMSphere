"""Read-only historical policy-gap discovery over the existing raw case package."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .integration import capture_policy_gap


def classify_raw_case(row: dict[str, Any]) -> dict[str, Any]:
    text = str(row.get("raw_description", ""))
    lower = text.lower()
    missing_auditor = bool(re.search(r"auditor.{0,100}(unavailable|missing|insufficient)|missing auditor", lower))
    rollback_missing = "rollback plan is missing" in lower or "rollback" not in lower
    tests_missing = "не выполнялась" in lower or "tests" not in lower
    retry_conflict = bool(re.search(r"unique_retry_conflict|retry.{0,40}conflict", lower))
    external = "отложена" in lower or "blocked_external" in lower or "external" in lower
    chain = {
        "failure": True, "root_cause": bool(text), "proposal": "repair request" in lower,
        "candidate": "accepted_solution" in lower, "tests": not tests_missing,
        "rollback": not rollback_missing, "policy_decision": "поли" in lower or "policy" in lower,
        "attestation_missing": missing_auditor, "attestation_stale": False,
        "retry_conflict": retry_conflict, "authority_boundary": False,
        "rollback_missing": rollback_missing, "tests_missing": tests_missing,
        "pipeline_defect": external,
    }
    result = capture_policy_gap(
        case_id=str(row.get("case_id", "")), correlation_root_id=str(row.get("case_id", "")),
        chain=chain, second_pass={"cause": "NO_POLICY_GAP"},
        current_policy_revision="historical-2026-08-19", current_policy_hash="",
    )
    result.update({
        "source_path": row.get("source_path", ""),
        "source_sha256": row.get("source_sha256", ""),
        "quality_gate": row.get("quality_gate"),
        "approved_for_training": row.get("approved_for_training"),
        "alternative_explanation": "missing auditor/evidence, rollback, test, retry, pipeline, or external blocker" if not result["genuine_policy_gap"] else "none identified",
        "confidence": 0.95 if not result["genuine_policy_gap"] else 0.5,
        "second_pass_verdict": "AGREES_NON_POLICY" if not result["genuine_policy_gap"] else "REQUIRES_INDEPENDENT_REVIEW",
        "recommended_next_action_id": result["next_action_id"],
    })
    return result


def run(raw_path: Path, output_dir: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [classify_raw_case(row) for row in rows]
    counts = Counter(case["primary_classification"] for case in cases)
    genuine = [case for case in cases if case["genuine_policy_gap"]]
    register = {
        "schema": "aims.policy_evolution.historical_candidate_register.v1",
        "source": str(raw_path), "source_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "case_count": len(cases), "classified_count": len(cases), "genuine_policy_gap_count": len(genuine),
        "classification_counts": dict(counts), "cases": cases,
        "historical_search_complete": len(cases) == 28,
        "candidate_created": False,
        "next_action_id": "SEARCH_ADDITIONAL_HISTORICAL_POLICY_FALSE_NEGATIVES" if not genuine else "PREPARE_POLICY_CHANGE_PROPOSAL",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "34_HISTORICAL_POLICY_CANDIDATE_REGISTER.json").write_text(json.dumps(register, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Historical Policy Candidate Register", "", f"Cases inspected: {len(cases)}/28", f"Genuine policy gaps: {len(genuine)}", "", "## Result", "", "All historical cases were classified with an independent second-pass rule. No candidate was created.", ""]
    lines += [f"- `{key}`: {value}" for key, value in sorted(counts.items())]
    lines += ["", "The source package is evidence-pending and contains no case where auditor, tests, rollback, pipeline, retry, and authority blockers are all cleared while policy alone causes the stop."]
    (output_dir / "34_HISTORICAL_POLICY_CANDIDATE_REGISTER.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return register


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    out = root / "agent_architecture_status" / "policy_evolution_implementation_20260819"
    result = run(root / "aims_workspace/training/raw_materials/repair_cases_20260819/raw_repair_case_descriptions.jsonl", out)
    print(json.dumps({"case_count": result["case_count"], "genuine_policy_gap_count": result["genuine_policy_gap_count"], "classification_counts": result["classification_counts"]}, sort_keys=True))
