"""
AIMS Self-Learning — Runtime Activation Proposal Workflow.

CLI: PYTHONPATH=ops python3 ops/agents/self_learning/runtime_activation_proposal_workflow.py \
  --staged-registry aims_workspace/agent_self_learning/staged_registry/staged_certified_skills.json \
  --out aims_workspace/agent_self_learning/runtime_activation_proposals

Reads Phase 11 staged registry, generates proposal packages, validates them,
and writes JSON + MD reports. No model calls, no runtime changes.
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
    from .runtime_activation_proposal_builder import build_proposals, load_staged_entries
    from .runtime_activation_proposal_validator import RuntimeActivationProposalValidator
    from .runtime_activation_proposal_schema import (
        PROPOSAL_STATUS_BLOCKED,
        PROPOSAL_STATUS_MANUAL,
        PROPOSAL_STATUS_REJECTED,
    )
except ImportError:
    from agents.self_learning.runtime_activation_proposal_builder import build_proposals, load_staged_entries  # type: ignore
    from agents.self_learning.runtime_activation_proposal_validator import RuntimeActivationProposalValidator  # type: ignore
    from agents.self_learning.runtime_activation_proposal_schema import (  # type: ignore
        PROPOSAL_STATUS_BLOCKED,
        PROPOSAL_STATUS_MANUAL,
        PROPOSAL_STATUS_REJECTED,
    )

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_STAGED_REGISTRY = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "staged_registry" / "staged_certified_skills.json"
)
_DEFAULT_OUT_DIR = _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "runtime_activation_proposals"

_NEXT_PHASE = "AIMS_RUNTIME_ACTIVATION_PROPOSAL_COMPLETE"


def _write_md_report(output: dict[str, Any], out_dir: pathlib.Path) -> None:
    lines = [
        "# AIMS Phase 12 — Runtime Activation Proposal Report",
        "",
        f"**Generated:** {output['created_at']}",
        f"**Staged entries loaded:** {output['staged_entries_loaded']}",
        f"**Proposals created:** {output['proposals_created']}",
        f"**Proposals blocked:** {output['proposals_blocked']}",
        f"**Proposals requiring manual approval:** {output['proposals_requiring_manual_approval']}",
        f"**Proposals rejected:** {output['proposals_rejected']}",
        f"**Registry valid:** {output['registry_valid']}",
        f"**Next phase:** {output['next_allowed_phase']}",
        "",
        "## Safety Invariants",
        "",
        "- `runtime_activation_allowed` = **False** for all proposals",
        "- `self_approval_allowed` = **False** for all proposals",
        "- `active_runtime_requested` = **False** for all proposals",
        "- `current_lifecycle_state` = **CERTIFIED_SKILL** for all proposals",
        "- `proposed_lifecycle_state` = **ACTIVE_RUNTIME_SKILL** as proposal target only",
        "- No runtime registry was modified",
        "- All runtime gates and approvals still required before any activation",
        "",
        "## Proposals",
        "",
    ]

    for p in output.get("proposals", []):
        status = p.get("proposal_status", "UNKNOWN")
        icon = "🔒" if status == PROPOSAL_STATUS_BLOCKED else ("⚠️" if status == PROPOSAL_STATUS_MANUAL else "❌")
        lines.append(f"### {icon} {p.get('proposal_id')} — {p.get('proposed_name')}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Domain:** {p.get('skill_domain')}")
        lines.append(f"- **Certified ID:** {p.get('certified_skill_id')}")
        lines.append(f"- **Model related:** {p.get('model_related')}")
        lines.append(f"- **Production related:** {p.get('production_related')}")
        lines.append(f"- **Activation:** {p.get('activation_request_status')}")
        lines.append(f"- **Required approvals:** {len(p.get('required_approvals', []))}")
        lines.append(f"- **Required gates:** {len(p.get('required_runtime_gates', []))}")
        lines.append(f"- **Activation blockers:** {len(p.get('activation_blockers', []))}")
        lines.append("")

    if output.get("rejected"):
        lines.append("## Rejected from Proposal Building")
        lines.append("")
        for r in output["rejected"]:
            lines.append(f"- `{r.get('staged_skill_id')}`: {r.get('reason')}")
        lines.append("")

    path = out_dir / "runtime_activation_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def run_proposal_workflow(
    staged_registry_path: pathlib.Path = _DEFAULT_STAGED_REGISTRY,
    out_dir: pathlib.Path = _DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    staged_entries = load_staged_entries(staged_registry_path)

    proposals, rejected = build_proposals(staged_entries)

    validator = RuntimeActivationProposalValidator()
    proposal_dicts: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []

    for proposal in proposals:
        d = proposal.to_dict()
        if validator.validate(d):
            proposal_dicts.append(d)
        else:
            validation_errors.append({
                "proposal_id": d.get("proposal_id"),
                "errors": validator.errors,
            })
            proposal_dicts.append(d)

    blocked_count = sum(1 for d in proposal_dicts if d.get("proposal_status") == PROPOSAL_STATUS_BLOCKED)
    manual_count = sum(1 for d in proposal_dicts if d.get("proposal_status") == PROPOSAL_STATUS_MANUAL)

    output: dict[str, Any] = {
        "phase": "12",
        "created_at": created_at,
        "staged_entries_loaded": len(staged_entries),
        "proposals_created": len(proposal_dicts),
        "proposals_blocked": blocked_count,
        "proposals_requiring_manual_approval": manual_count,
        "proposals_rejected": len(rejected),
        "validation_errors": validation_errors,
        "registry_valid": len(validation_errors) == 0,
        "next_allowed_phase": _NEXT_PHASE,
        "proposals": proposal_dicts,
        "rejected": rejected,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    proposals_path = out_dir / "runtime_activation_proposals.json"
    proposals_path.write_text(
        json.dumps({"proposals": proposal_dicts}, indent=2, ensure_ascii=False)
    )

    report_path = out_dir / "runtime_activation_report.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    _write_md_report(output, out_dir)

    output["proposals_json"] = str(proposals_path)
    output["report_json"] = str(report_path)
    output["report_md"] = str(out_dir / "runtime_activation_report.md")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIMS Phase 12 — Runtime Activation Proposal Workflow"
    )
    parser.add_argument(
        "--staged-registry",
        type=pathlib.Path,
        default=_DEFAULT_STAGED_REGISTRY,
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_DEFAULT_OUT_DIR,
    )
    args = parser.parse_args()

    r = run_proposal_workflow(
        staged_registry_path=args.staged_registry,
        out_dir=args.out,
    )

    print("=" * 60)
    print("AIMS Phase 12 — Runtime Activation Proposal Workflow")
    print("=" * 60)
    print(f"staged_entries_loaded              : {r['staged_entries_loaded']}")
    print(f"proposals_created                  : {r['proposals_created']}")
    print(f"proposals_blocked                  : {r['proposals_blocked']}")
    print(f"proposals_requiring_manual_approval: {r['proposals_requiring_manual_approval']}")
    print(f"proposals_rejected                 : {r['proposals_rejected']}")
    print(f"registry_valid                     : {r['registry_valid']}")
    print(f"output_dir                         : {args.out}")
    print(f"proposals JSON                     : {r['proposals_json']}")
    print(f"report JSON                        : {r['report_json']}")
    print(f"report MD                          : {r['report_md']}")


if __name__ == "__main__":
    main()
