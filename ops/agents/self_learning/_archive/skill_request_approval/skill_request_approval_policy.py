from __future__ import annotations

from typing import Any

KNOWN_AGENTS = {
    "logi", "axi", "architect", "security", "poli", "qa-agent", "release-agent",
    "argus", "watchdog-agent", "traini", "doci", "docs-agent", "omi", "knomi",
    "repairman", "control-plane", "scheduler",
}

UNSAFE_FLAGS = (
    "secrets_related",
    "deletion_or_quarantine_related",
    "service_restart_related",
    "model_loading_related",
    "registry_modification_related",
)


def evaluate_request_policy(req: dict[str, Any]) -> dict[str, Any]:
    blocking: list[str] = []
    warnings: list[str] = []
    required_gates = ["argus", "logi", "qa"]

    if req.get("source_agent_id") not in KNOWN_AGENTS:
        blocking.append("unknown source_agent_id")
    if req.get("proposed_owner_agent_id") not in KNOWN_AGENTS:
        blocking.append("unknown proposed_owner_agent_id")
    if int(req.get("observed_count", 0)) < 2:
        blocking.append("observed_count < 2")
    if not req.get("repeated_task_evidence_refs"):
        blocking.append("repeated_task_evidence_refs is empty")

    for flag in UNSAFE_FLAGS:
        if req.get(flag) is True:
            blocking.append(f"unsafe flag: {flag}")

    if req.get("requested_creator") == req.get("source_agent_id") and req.get("approved_by") == req.get("source_agent_id"):
        blocking.append("self-approval is forbidden")

    text_blob = " ".join(
        str(req.get(k, "")) for k in (
            "missing_capability_description", "expected_skill_behavior", "requested_skill_name"
        )
    ).lower()

    forbidden_phrases = [
        "skip gates", "activate active_runtime_skill", "launch training directly",
        "promote model directly", "bypass dgx", "self-approve",
    ]
    for phrase in forbidden_phrases:
        if phrase in text_blob:
            blocking.append(f"forbidden phrase: {phrase}")

    if req.get("production_related") or req.get("training_related") or req.get("model_related"):
        if "traini" not in required_gates:
            required_gates.append("traini")
        warnings.append("extra gates required for production/training/model related request")

    allowed = len(blocking) == 0
    recommended = "APPROVE" if allowed else "BLOCK_UNSAFE"

    return {
        "allowed_for_approval": allowed,
        "blocking_reasons": blocking,
        "warnings": warnings,
        "required_gates": required_gates,
        "recommended_decision": recommended,
    }
