"""Test-only route wrapper for Omi document-dialogue-gap-check (Stage 4C).

This module is intentionally not wired into live Omi Telegram handlers.
It provides deterministic route-level mapping around the Stage 4A validator.
Includes passive telemetry emission for gap-check observability.
"""

from __future__ import annotations

import logging
from typing import Any

from omi_telegram.document_dialogue_gap_check import validate_document_dialogue_request

log = logging.getLogger(__name__)

ALLOWED_ROUTE_STATUSES = {
    "ROUTE_READY_FOR_HANDOFF",
    "ROUTE_NEEDS_CONTEXT",
    "ROUTE_BLOCKED",
    "ROUTE_NO_MATCH",
}


def _emit_omi_gap_check_telemetry(
    validator_status: str,
    route_result: dict[str, Any],
    runtime_activation: bool,
) -> None:
    """Emit passive telemetry for Omi gap-check (non-breaking, test-local by default)."""
    try:
        from agents.pipeline_telemetry import PipelineTelemetry

        telemetry = PipelineTelemetry()

        # Map validator status to gap-check status for telemetry
        status_map = {
            "READY_FOR_DOCI_OR_DOCS_HANDOFF": "READY_FOR_DOCI_OR_DOCS_HANDOFF",
            "READY_FOR_DOCI_OR_OMI_HANDOFF": "READY_FOR_DOCI_OR_OMI_HANDOFF",
            "NEEDS_CONTEXT": "NEEDS_CONTEXT",
            "BLOCK": "BLOCK",
        }
        telemetry_status = status_map.get(validator_status, validator_status)

        # Emit omi_gap_check event
        telemetry.emit_omi_gap_check_event(
            check_id=f"omi_gap_check_{id(route_result)}",
            status=telemetry_status,
            trigger_count=1,
            false_positive_review_flag=False,
            rollback_flag=False,
        )
    except Exception as exc:
        # Telemetry failures must never break routing behavior
        log.debug("Omi gap-check telemetry emission failed (non-fatal): %s", exc)


def _map_validator_status(validator_status: str) -> str:
    if validator_status in {"READY_FOR_DOCI_OR_DOCS_HANDOFF", "READY_FOR_DOCI_OR_OMI_HANDOFF"}:
        return "ROUTE_READY_FOR_HANDOFF"
    if validator_status == "NEEDS_CONTEXT":
        return "ROUTE_NEEDS_CONTEXT"
    if validator_status == "BLOCK":
        return "ROUTE_BLOCKED"
    return "ROUTE_NO_MATCH"


def route_document_dialogue_gap_check(
    payload: dict,
    *,
    runtime_activation: bool = False,
) -> dict[str, Any]:
    """Run test-only deterministic routing for document-dialogue-gap-check.

    Returns stable route schema and preserves runtime_activation flag visibility.
    """
    test_only = True

    if not isinstance(payload, dict):
        return {
            "route_status": "ROUTE_NEEDS_CONTEXT",
            "validator_status": "NEEDS_CONTEXT",
            "reason": "payload must be a dict",
            "missing_inputs": ["payload"],
            "recommended_handoff": "request_clarification",
            "safe_to_continue": False,
            "test_only": test_only,
            "runtime_activation": bool(runtime_activation),
            "evidence": ["stage4c_test_only_wrapper", "malformed_payload"],
        }

    user_text = payload.get("user_text")
    if not isinstance(user_text, str) or not user_text.strip():
        return {
            "route_status": "ROUTE_NEEDS_CONTEXT",
            "validator_status": "NEEDS_CONTEXT",
            "reason": "missing required field: user_text",
            "missing_inputs": ["user_text"],
            "recommended_handoff": "request_clarification",
            "safe_to_continue": False,
            "test_only": test_only,
            "runtime_activation": bool(runtime_activation),
            "evidence": ["stage4c_test_only_wrapper", "missing_user_text"],
        }

    available_documents = payload.get("available_documents")
    if available_documents is not None and not isinstance(available_documents, list):
        return {
            "route_status": "ROUTE_NEEDS_CONTEXT",
            "validator_status": "NEEDS_CONTEXT",
            "reason": "available_documents must be a list when provided",
            "missing_inputs": ["available_documents"],
            "recommended_handoff": "request_clarification",
            "safe_to_continue": False,
            "test_only": test_only,
            "runtime_activation": bool(runtime_activation),
            "evidence": ["stage4c_test_only_wrapper", "invalid_available_documents"],
        }

    context = payload.get("context")
    if context is not None and not isinstance(context, dict):
        return {
            "route_status": "ROUTE_NEEDS_CONTEXT",
            "validator_status": "NEEDS_CONTEXT",
            "reason": "context must be a dict when provided",
            "missing_inputs": ["context"],
            "recommended_handoff": "request_clarification",
            "safe_to_continue": False,
            "test_only": test_only,
            "runtime_activation": bool(runtime_activation),
            "evidence": ["stage4c_test_only_wrapper", "invalid_context"],
        }

    out = validate_document_dialogue_request(
        user_text,
        available_documents=available_documents,
        context=context,
    )

    validator_status = str(out.get("status") or "NEEDS_CONTEXT")
    route_status = _map_validator_status(validator_status)

    result = {
        "route_status": route_status,
        "validator_status": validator_status,
        "reason": out.get("reason", ""),
        "missing_inputs": out.get("missing_inputs", []),
        "recommended_handoff": out.get("recommended_handoff", "request_clarification"),
        "safe_to_continue": bool(out.get("safe_to_continue", False)),
        "test_only": test_only,
        "runtime_activation": bool(runtime_activation),
        "evidence": list(out.get("evidence", [])) + ["stage4c_test_only_wrapper"],
    }

    if result["route_status"] not in ALLOWED_ROUTE_STATUSES:
        result["route_status"] = "ROUTE_NO_MATCH"
        result["safe_to_continue"] = False
        result["reason"] = "unexpected validator mapping"

    # Emit passive telemetry (non-breaking, test-local by default)
    _emit_omi_gap_check_telemetry(validator_status, result, runtime_activation)

    return result
