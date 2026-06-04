from __future__ import annotations

from pathlib import Path
from typing import Any


def _risk_summary(req: dict[str, Any]) -> str:
    flags = [
        k for k in (
            "secrets_related", "deletion_or_quarantine_related", "service_restart_related",
            "model_loading_related", "registry_modification_related", "training_related", "production_related"
        ) if req.get(k)
    ]
    return ", ".join(flags) if flags else "none"


def write_axi_pending_markdown(requests: list[dict[str, Any]], out_path: Path) -> None:
    pending = [r for r in requests if r.get("approval_status") == "PENDING_APPROVAL"]
    blocked = [r for r in requests if r.get("approval_status") == "BLOCKED_UNSAFE"]
    approved = [r for r in requests if r.get("approval_status") == "APPROVED"]
    rejected = [r for r in requests if r.get("approval_status") == "REJECTED"]

    lines: list[str] = [
        "# Axi Pending Skill Requests",
        "",
        f"- pending_count: {len(pending)}",
        f"- blocked_unsafe_count: {len(blocked)}",
        f"- approved_count: {len(approved)}",
        f"- rejected_count: {len(rejected)}",
        "",
        "## Batch Decision Instructions",
        "Use decisions JSON with fields: request_id, decision(APPROVE|REJECT), decided_by, reason.",
        "",
        "## Request Table",
        "| request_id | source_agent_id | proposed_owner_agent_id | requested_skill_name | domain | observed_count | risk_summary | recommended_decision | reason |",
        "|---|---|---|---|---|---:|---|---|---|",
    ]

    for r in requests:
        rec = r.get("policy_eval", {})
        reason = "; ".join(rec.get("blocking_reasons", []) or rec.get("warnings", []) or ["ok"])
        lines.append(
            "| {id} | {src} | {owner} | {name} | {dom} | {obs} | {risk} | {dec} | {reason} |".format(
                id=r.get("request_id", ""),
                src=r.get("source_agent_id", ""),
                owner=r.get("proposed_owner_agent_id", ""),
                name=r.get("requested_skill_name", ""),
                dom=r.get("requested_skill_domain", ""),
                obs=r.get("observed_count", 0),
                risk=_risk_summary(r),
                dec=rec.get("recommended_decision", "REVIEW"),
                reason=reason.replace("|", "/"),
            )
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
