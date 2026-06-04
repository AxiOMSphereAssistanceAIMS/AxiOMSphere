"""
AIMS Self-Learning — Runtime Activation Approval Workflow.

CLI: PYTHONPATH=ops python3 ops/agents/self_learning/runtime_activation_approval_workflow.py \
  --proposals aims_workspace/agent_self_learning/runtime_activation_proposals/runtime_activation_proposals.json \
  --out aims_workspace/agent_self_learning/runtime_activation_approval

Loads Phase 12 proposals, generates default-BLOCKED approval manifest,
evaluates gate matrix, and writes JSON + MD reports. No model calls, no activation.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
from typing import Any

_OPS = pathlib.Path(__file__).resolve().parents[2]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

try:
    from .runtime_activation_approval_schema import (
        RuntimeActivationApprovalEntry,
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_DRY_RUN,
        APPROVAL_STATUS_REJECTED,
        APPROVAL_STATUS_PENDING,
        REQUIRED_GATES_BASE,
        APPROVAL_VERSION,
    )
    from .runtime_activation_approval_validator import RuntimeActivationApprovalValidator
    from .runtime_activation_gate_evaluator import evaluate_gate_status, build_gate_matrix
except ImportError:
    from agents.self_learning.runtime_activation_approval_schema import (  # type: ignore
        RuntimeActivationApprovalEntry,
        APPROVAL_STATUS_BLOCKED,
        APPROVAL_STATUS_DRY_RUN,
        APPROVAL_STATUS_REJECTED,
        APPROVAL_STATUS_PENDING,
        REQUIRED_GATES_BASE,
        APPROVAL_VERSION,
    )
    from agents.self_learning.runtime_activation_approval_validator import RuntimeActivationApprovalValidator  # type: ignore
    from agents.self_learning.runtime_activation_gate_evaluator import evaluate_gate_status, build_gate_matrix  # type: ignore

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_PROPOSALS = (
    _REPO_ROOT
    / "aims_workspace"
    / "agent_self_learning"
    / "runtime_activation_proposals"
    / "runtime_activation_proposals.json"
)
_DEFAULT_OUT_DIR = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "runtime_activation_approval"
)
_NEXT_PHASE = "AIMS_RUNTIME_ACTIVATION_APPROVAL_GATE_COMPLETE"


def _load_proposals(proposals_path: pathlib.Path) -> list[dict[str, Any]]:
    if not proposals_path.exists():
        raise FileNotFoundError(f"Proposals not found: {proposals_path}")
    data = json.loads(proposals_path.read_text(encoding="utf-8"))
    return data.get("proposals", [])


def _make_approval_entry(proposal: dict[str, Any]) -> RuntimeActivationApprovalEntry:
    return RuntimeActivationApprovalEntry(
        proposal_id=proposal.get("proposal_id", ""),
        certified_skill_id=proposal.get("certified_skill_id", ""),
        owner_agent_id=proposal.get("owner_agent_id") or "aims_self_learning_pipeline",
        skill_domain=proposal.get("skill_domain", ""),
        current_lifecycle_state=proposal.get("current_lifecycle_state", "CERTIFIED_SKILL"),
        proposed_lifecycle_state=proposal.get("proposed_lifecycle_state", "ACTIVE_RUNTIME_SKILL"),
        model_related=bool(proposal.get("model_related")),
        production_related=bool(proposal.get("production_related")),
        approval_status=APPROVAL_STATUS_BLOCKED,
        blocking_reasons=["all gates pending — no approvals received"],
        metadata=dict(proposal.get("metadata", {})),
    )


def _build_manifest_template(
    entry_dicts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "manifest_version": APPROVAL_VERSION,
        "description": (
            "Runtime Activation Approval Manifest Template — "
            "all entries default BLOCKED, all gates False. "
            "Fill in gate booleans and re-run gate evaluator to advance status."
        ),
        "entries": entry_dicts,
    }


def _write_md_report(output: dict[str, Any], out_dir: pathlib.Path) -> None:
    lines = [
        "# AIMS Phase 13 — Runtime Activation Approval Gate Report",
        "",
        f"**Generated:** {output['created_at']}",
        f"**Proposals loaded:** {output['proposals_loaded']}",
        f"**Approval entries created:** {output['approval_entries_created']}",
        f"**Approved for dry-run only:** {output['approved_for_dry_run_only']}",
        f"**Blocked:** {output['blocked']}",
        f"**Rejected:** {output['rejected']}",
        f"**Pending:** {output['pending']}",
        f"**Next phase:** {output['next_allowed_phase']}",
        "",
        "## Safety Invariants",
        "",
        "- All entries default to **BLOCKED**",
        "- `human_approved` = **False** for all entries",
        "- All gate booleans = **False** for all entries",
        "- No entry defaults to approved",
        "- Runtime activation remains **disabled**",
        "- Active runtime registry **not modified**",
        "- No activation occurred",
        "",
        "## Approval Gate Status",
        "",
    ]

    for entry in output.get("entries", []):
        status = entry.get("approval_status", "UNKNOWN")
        icon = "🔒" if status == APPROVAL_STATUS_BLOCKED else (
            "✅" if status == APPROVAL_STATUS_DRY_RUN else "❌"
        )
        lines.append(f"### {icon} {entry.get('proposal_id')} — {entry.get('skill_domain')}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Certified ID:** {entry.get('certified_skill_id')}")
        lines.append(f"- **Model related:** {entry.get('model_related')}")
        lines.append(f"- **Human approved:** {entry.get('human_approved')}")
        lines.append(f"- **Argus gate:** {entry.get('argus_gate_passed')}")
        lines.append(f"- **Logi gate:** {entry.get('logi_task_ledger_registered')}")
        lines.append(f"- **QA gate:** {entry.get('qa_validation_passed')}")
        lines.append(f"- **DGX policy:** {entry.get('dgx_policy_verified')}")
        lines.append(f"- **Blocking reasons:** {len(entry.get('blocking_reasons', []))}")
        lines.append("")

    path = out_dir / "runtime_activation_approval_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def run_approval_workflow(
    proposals_path: pathlib.Path = _DEFAULT_PROPOSALS,
    out_dir: pathlib.Path = _DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    proposals = _load_proposals(proposals_path)

    entries: list[RuntimeActivationApprovalEntry] = [
        _make_approval_entry(p) for p in proposals
    ]
    entry_dicts = [e.to_dict() for e in entries]

    gate_matrix = build_gate_matrix(entry_dicts)

    validator = RuntimeActivationApprovalValidator()
    validation_errors: list[dict[str, Any]] = []
    for d in entry_dicts:
        if not validator.validate(d):
            validation_errors.append({
                "proposal_id": d.get("proposal_id"),
                "errors": validator.errors,
            })

    blocked = sum(1 for d in entry_dicts if d.get("approval_status") == APPROVAL_STATUS_BLOCKED)
    dry_run = sum(1 for d in entry_dicts if d.get("approval_status") == APPROVAL_STATUS_DRY_RUN)
    rejected = sum(1 for d in entry_dicts if d.get("approval_status") == APPROVAL_STATUS_REJECTED)
    pending = sum(1 for d in entry_dicts if d.get("approval_status") == APPROVAL_STATUS_PENDING)

    output: dict[str, Any] = {
        "phase": "13",
        "created_at": created_at,
        "proposals_loaded": len(proposals),
        "approval_entries_created": len(entry_dicts),
        "approved_for_dry_run_only": dry_run,
        "blocked": blocked,
        "rejected": rejected,
        "pending": pending,
        "validation_errors": validation_errors,
        "registry_valid": len(validation_errors) == 0,
        "next_allowed_phase": _NEXT_PHASE,
        "entries": entry_dicts,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = _build_manifest_template(entry_dicts)
    manifest_path = out_dir / "runtime_activation_approval_manifest.template.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    report_path = out_dir / "runtime_activation_approval_report.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    gate_matrix_path = out_dir / "runtime_activation_gate_matrix.json"
    gate_matrix_path.write_text(json.dumps(gate_matrix, indent=2, ensure_ascii=False))

    _write_md_report(output, out_dir)

    output["manifest_json"] = str(manifest_path)
    output["report_json"] = str(report_path)
    output["gate_matrix_json"] = str(gate_matrix_path)
    output["report_md"] = str(out_dir / "runtime_activation_approval_report.md")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIMS Phase 13 — Runtime Activation Approval Workflow"
    )
    parser.add_argument(
        "--proposals",
        type=pathlib.Path,
        default=_DEFAULT_PROPOSALS,
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_DEFAULT_OUT_DIR,
    )
    args = parser.parse_args()

    r = run_approval_workflow(
        proposals_path=args.proposals,
        out_dir=args.out,
    )

    print("=" * 60)
    print("AIMS Phase 13 — Runtime Activation Approval Workflow")
    print("=" * 60)
    print(f"proposals_loaded              : {r['proposals_loaded']}")
    print(f"approval_entries_created      : {r['approval_entries_created']}")
    print(f"approved_for_dry_run_only     : {r['approved_for_dry_run_only']}")
    print(f"blocked                       : {r['blocked']}")
    print(f"rejected                      : {r['rejected']}")
    print(f"pending                       : {r['pending']}")
    print(f"output_dir                    : {args.out}")
    print(f"manifest JSON                 : {r['manifest_json']}")
    print(f"report JSON                   : {r['report_json']}")
    print(f"gate matrix JSON              : {r['gate_matrix_json']}")
    print(f"report MD                     : {r['report_md']}")


if __name__ == "__main__":
    main()
