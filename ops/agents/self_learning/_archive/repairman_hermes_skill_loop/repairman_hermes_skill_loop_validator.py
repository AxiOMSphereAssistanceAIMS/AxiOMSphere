from __future__ import annotations

from pathlib import Path


def validate(report: dict, out_dir: Path) -> dict:
    errors = []
    if report.get("model_endpoint_calls") != 0:
        errors.append("model_endpoint_calls_nonzero")
    if report.get("hermes_invocations") != 0:
        errors.append("hermes_invocations_nonzero")
    if report.get("production_patches") != 0:
        errors.append("production_patches_nonzero")
    if report.get("service_restarts") != 0:
        errors.append("service_restarts_nonzero")
    if report.get("dossiers_sanitized", 0) < report.get("dossiers_created", 0):
        errors.append("not_all_dossiers_sanitized")
    needed = [
        "repair_case_dossiers.json",
        "hermes_review_prompts.json",
        "hermes_review_results.json",
        "skill_incubation_signals.json",
        "hermes_repair_skill_packages.json",
        "hermes_skill_test_reports.json",
        "hermes_incubated_skill_candidates.json",
        "aims_adapted_skill_candidates.json",
        "repairman_adoption_plans.json",
        "repairman_adoption_test_results.json",
        "repairman_scope_approval_requests.json",
        "repairman_active_skill_registry.json",
        "repairman_owner_skill_bindings.json",
        "repairman_controlled_first_use_records.json",
        "repairman_skill_feedback_events.json",
    ]
    for n in needed:
        if not (out_dir / n).exists():
            errors.append(f"missing_artifact:{n}")
    return {"ok": not errors, "errors": errors}
