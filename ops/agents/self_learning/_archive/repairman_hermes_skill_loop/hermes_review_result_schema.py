from __future__ import annotations

REQUIRED_HERMES_REVIEW_RESULT_FIELDS = {
    "hermes_review_id",
    "repair_case_id",
    "diagnosis_quality",
    "missing_evidence",
    "incorrect_assumptions",
    "better_root_cause_hypotheses",
    "better_repair_plan",
    "repairman_skill_gap",
    "reusable_skill_pattern",
    "suggested_skill_name",
    "suggested_skill_scope",
    "suggested_tests",
    "suggested_adoption_target",
    "risks",
    "recommended_next_action",
}

def validate_review_result(obj: dict) -> list[str]:
    missing = REQUIRED_HERMES_REVIEW_RESULT_FIELDS - set(obj)
    return [f"missing:{k}" for k in sorted(missing)]
