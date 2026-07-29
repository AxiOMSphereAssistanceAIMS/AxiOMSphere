"""Deterministic Poli review for Codex-reviewed Fullstack changes.

Poli is the policy holder, not another language-model reviewer.  Codex
provides technical evidence; this module decides whether that evidence fits
the current project strategy and preserves certified pipelines.
"""
from __future__ import annotations

from typing import Any

from ops.agents.poli_checklist import build_checklist_packet


def evaluate_fullstack_change(
    proposal: dict[str, Any],
    codex_audit: dict[str, Any],
) -> dict[str, Any]:
    """Return an auditable ALLOW/DENY decision; missing evidence fails closed."""
    checklist = build_checklist_packet(proposal, codex_audit)
    reasons: list[str] = []
    risks: list[str] = []
    if str(codex_audit.get("status", "")).upper() != "PASSED":
        reasons.append("Codex CLI audit is not PASSED")
    if not codex_audit.get("auditor_available"):
        reasons.append("Codex CLI auditor is unavailable")
    blocking = [f for f in codex_audit.get("findings", []) if str(f.get("severity", "")).upper() == "BLOCKING"]
    if blocking:
        reasons.append(f"Codex reported {len(blocking)} BLOCKING finding(s)")
    if proposal.get("strategy_change") is True:
        reasons.append("proposal changes project strategy")
    if proposal.get("concept_preserved") is not True:
        reasons.append("concept_preserved=true evidence is missing")
    if proposal.get("restorative") is not True:
        reasons.append("restorative=true evidence is missing")
    if proposal.get("production_mutation") is True:
        reasons.append("production mutation is outside this bounded Poli route")
    if proposal.get("certified_pipeline_compatibility") is not True:
        reasons.append("certified pipeline compatibility evidence is missing")
    if proposal.get("provenance_complete") is not True:
        reasons.append("provenance/data-lineage evidence is missing")
    if not proposal.get("rollback_plan"):
        reasons.append("rollback plan is missing")
    if not reasons:
        reasons.extend(
            f"Poli checklist blocked: {item}"
            for item in checklist["blocked_checks"]
            if item not in reasons
        )
    if reasons:
        risks.append("change must not be executed; create a rework case with these gaps")
        return {
            "decision": "DENY",
            "allowed": False,
            "holder": "Poli",
            "auditor": "CodexCLI",
            "reasons": reasons,
            "risks": risks,
            "telegram_action": "result_only",
            "checklist": checklist,
        }
    return {
        "decision": "ALLOW",
        "allowed": True,
        "holder": "Poli",
        "auditor": "CodexCLI",
        "reasons": [
            "Codex technical audit PASSED",
            "change preserves strategy and certified pipelines",
            "bounded restorative execution with rollback is declared",
        ],
        "risks": [],
        "telegram_action": "result_only",
        "checklist": checklist,
    }


__all__ = ["evaluate_fullstack_change"]
