from __future__ import annotations


def build_gate_checklist(pkg: dict) -> dict:
    model_or_training_related = pkg.get("skill_domain") in {"training", "models", "eval", "engineering"}
    blocking = []

    chk = {
        "gate_checklist_id": pkg["gate_checklist_id"],
        "certification_candidate_id": pkg["certification_candidate_id"],
        "argus_gate_required": True,
        "argus_gate_passed": False,
        "logi_gate_required": True,
        "logi_gate_passed": False,
        "qa_gate_required": True,
        "qa_gate_passed": False,
        "traini_gate_required": bool(model_or_training_related),
        "traini_gate_passed": False,
        "registry_gate_required": True,
        "registry_gate_passed": False,
        "rollback_gate_required": True,
        "rollback_gate_passed": False,
        "evidence_gate_required": True,
        "evidence_gate_passed": False,
        "secrets_policy_passed": True,
        "production_policy_passed": True,
        "model_policy_passed": True,
        "dgx_policy_passed": True,
        "self_approval_absent": True,
        "runtime_activation_absent": True,
        "blocking_reasons": blocking,
        "gate_status": "PENDING_GATE_REVIEW",
    }
    # if strict expectation: mandatory gates still not passed now
    if not chk["argus_gate_passed"] or not chk["logi_gate_passed"] or not chk["qa_gate_passed"]:
        chk["blocking_reasons"].append("mandatory gates pending: argus/logi/qa")
    if chk["traini_gate_required"] and not chk["traini_gate_passed"]:
        chk["blocking_reasons"].append("traini gate pending")
    chk["gate_status"] = "BLOCKED_MISSING_GATE" if chk["blocking_reasons"] else "PENDING_GATE_REVIEW"
    return chk
