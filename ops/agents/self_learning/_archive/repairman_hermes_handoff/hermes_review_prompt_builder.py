from __future__ import annotations

import datetime as dt
import json
from typing import Any


def build_hermes_prompt(dossier: dict[str, Any]) -> dict[str, Any]:
    rid = dossier["repair_case_id"]
    expected_schema = {
        "hermes_review_id": "string",
        "repair_case_id": rid,
        "diagnosis_quality": "LOW|MEDIUM|HIGH",
        "missing_evidence": ["string"],
        "incorrect_assumptions": ["string"],
        "better_root_cause_hypotheses": ["string"],
        "better_repair_plan": ["string"],
        "repairman_skill_gap": ["string"],
        "reusable_skill_pattern": "string",
        "suggested_skill_name": "string",
        "suggested_skill_scope": "string",
        "suggested_tests": ["string"],
        "suggested_adoption_target": "string",
        "risks": ["string"],
        "recommended_next_action": "string",
    }

    prompt_text = (
        "You are Hermes consultant for Repairman. Analyze ONLY this sanitized dossier and return RAW JSON only.\n"
        "No markdown, no explanations outside JSON.\n"
        "Required output schema:\n"
        + json.dumps(expected_schema, ensure_ascii=False, indent=2)
        + "\nDossier:\n"
        + json.dumps(dossier, ensure_ascii=False, indent=2)
    )

    return {
        "prompt_id": f"hermes_prompt_{rid}",
        "repair_case_id": rid,
        "target_consultant": "hermes",
        "consultant_model": dossier.get("hermes_consultant_model", "project1"),
        "mode": "review_only",
        "prompt_text": prompt_text,
        "expected_output_schema": expected_schema,
        "allowed_consultant_actions": [
            "analyze dossier",
            "critique reasoning",
            "propose skill pattern",
            "propose tests",
            "propose safer repair plan",
            "suggest Repairman improvement",
        ],
        "forbidden_consultant_actions": [
            "patch files",
            "run commands",
            "restart services",
            "load/unload models",
            "launch training",
            "access secrets",
            "become governor",
            "directly activate skill",
        ],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
