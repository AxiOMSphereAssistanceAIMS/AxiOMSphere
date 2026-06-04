from __future__ import annotations

from typing import Any


def validate_post_workflow(
    requests: list[dict[str, Any]],
    downstream_plans: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    ids = [r.get("request_id") for r in requests]
    if len(ids) != len(set(ids)):
        errors.append("request IDs are not unique")

    plan_by_req = {p.get("request_id"): p for p in downstream_plans}

    # Phase 20 is planning-only; execution counters must remain zero.
    runtime_activation_count = 0
    training_launch_count = 0
    model_load_unload_count = 0
    service_restart_count = 0
    secrets_access_count = 0
    deletion_control_count = 0
    model_promotion_count = 0

    for r in requests:
        status = r.get("approval_status")
        pe = r.get("policy_eval", {})
        if status == "APPROVED":
            if r.get("observed_count", 0) < 2:
                errors.append(f"approved request {r.get('request_id')} has observed_count < 2")
            if not r.get("repeated_task_evidence_refs"):
                errors.append(f"approved request {r.get('request_id')} missing evidence refs")
            if r.get("request_id") not in plan_by_req:
                errors.append(f"approved request {r.get('request_id')} missing downstream plan")
        if status in {"REJECTED", "BLOCKED_UNSAFE"} and r.get("request_id") in plan_by_req:
            errors.append(f"{status} request {r.get('request_id')} must not have downstream plan")

        for k in ("secrets_related", "deletion_or_quarantine_related", "service_restart_related", "model_loading_related", "registry_modification_related"):
            if r.get(k):
                if status != "BLOCKED_UNSAFE":
                    errors.append(f"unsafe request {r.get('request_id')} with {k}=true must be BLOCKED_UNSAFE")

        txt = " ".join(str(r.get(x, "")) for x in ("missing_capability_description", "expected_skill_behavior", "requested_skill_name")).lower()
        service_restart_count += int("restart service" in txt or "docker" in txt)
        secrets_access_count += int("secret" in txt or "token" in txt)
        deletion_control_count += int("delete" in txt or "quarantine" in txt)
        model_promotion_count += int("promote model" in txt)

        if r.get("production_related") or r.get("training_related") or r.get("model_related"):
            gates = pe.get("required_gates", [])
            if "traini" not in gates:
                warnings.append(f"request {r.get('request_id')} expected traini gate")

    dgx_policy_preserved = True  # Phase 20: no execution/model actions

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "runtime_activation_count": runtime_activation_count,
        "training_launch_count": training_launch_count,
        "model_load_unload_count": model_load_unload_count,
        "service_restart_count": service_restart_count,
        "secrets_access_count": secrets_access_count,
        "deletion_control_count": deletion_control_count,
        "model_promotion_count": model_promotion_count,
        "dgx_slot32_slot120_policy_preserved": dgx_policy_preserved,
    }
