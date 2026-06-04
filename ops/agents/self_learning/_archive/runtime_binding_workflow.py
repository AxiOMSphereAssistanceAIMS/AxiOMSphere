"""
AIMS Self-Learning — Runtime Binding Simulation Workflow.

CLI:
  PYTHONPATH=ops python3 ops/agents/self_learning/runtime_binding_workflow.py \
    --approval-manifest aims_workspace/agent_self_learning/runtime_activation_approval/runtime_activation_approval_manifest.template.json \
    --approval-report aims_workspace/agent_self_learning/runtime_activation_approval/runtime_activation_approval_report.json \
    --out aims_workspace/agent_self_learning/runtime_binding_simulation

Loads Phase 13 approval entries, simulates binding evaluation for all.
No model calls, no activation, no registry modification.
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
    from .runtime_binding_schema import (
        BINDING_SCHEMA_VERSION,
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
    )
    from .runtime_binding_simulator import simulate_all_bindings, build_binding_matrix
    from .runtime_binding_validator import RuntimeBindingValidator
except ImportError:
    from agents.self_learning.runtime_binding_schema import (  # type: ignore
        BINDING_SCHEMA_VERSION,
        SIMULATED_BLOCKED,
        SIMULATED_READY,
        SIMULATED_REJECTED,
    )
    from agents.self_learning.runtime_binding_simulator import simulate_all_bindings, build_binding_matrix  # type: ignore
    from agents.self_learning.runtime_binding_validator import RuntimeBindingValidator  # type: ignore

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_APPROVAL_MANIFEST = (
    _REPO_ROOT
    / "aims_workspace"
    / "agent_self_learning"
    / "runtime_activation_approval"
    / "runtime_activation_approval_manifest.template.json"
)
_DEFAULT_APPROVAL_REPORT = (
    _REPO_ROOT
    / "aims_workspace"
    / "agent_self_learning"
    / "runtime_activation_approval"
    / "runtime_activation_approval_report.json"
)
_DEFAULT_OUT_DIR = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "runtime_binding_simulation"
)
_NEXT_PHASE = "AIMS_RUNTIME_BINDING_SIMULATOR_READY"


def _load_approval_entries(
    manifest_path: pathlib.Path,
    report_path: pathlib.Path,
) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Approval manifest not found: {manifest_path}")
    if not report_path.exists():
        raise FileNotFoundError(f"Approval report not found: {report_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # Manifest template has gate state; report has counts; prefer manifest entries
    entries = manifest.get("entries") or report.get("entries", [])
    return entries


def _write_md_report(output: dict[str, Any], out_dir: pathlib.Path) -> None:
    lines = [
        "# AIMS Phase 14 — Dry-run Runtime Binding Simulation Report",
        "",
        f"**Generated:** {output['created_at']}",
        f"**Approvals loaded:** {output['approvals_loaded']}",
        f"**Bindings simulated:** {output['bindings_simulated']}",
        f"**Ready for dry-run binding:** {output['ready_for_dry_run_binding']}",
        f"**Blocked (not approved):** {output['blocked_not_approved']}",
        f"**Rejected (unsafe):** {output['rejected_unsafe']}",
        f"**Active registry changed:** {output['active_registry_changed']}",
        f"**Next phase:** {output['next_allowed_phase']}",
        "",
        "## Safety Invariants",
        "",
        "- All entries **BLOCKED_NOT_APPROVED** (Phase 13 has 0 approved entries)",
        "- `binding_allowed` = **False** for all entries",
        "- `active_runtime_registry_changed` = **False** for all entries",
        "- `agent_behavior_changed` = **False** for all entries",
        "- `runtime_activation_allowed` = **False** for all entries",
        "- `self_approval_allowed` = **False** for all entries",
        "- No skill activated",
        "- No active runtime registry modified",
        "- No agent behavior modified",
        "",
        "## Binding Matrix",
        "",
    ]

    for entry in output.get("entries", []):
        state = entry.get("simulated_binding_state", "UNKNOWN")
        if state == SIMULATED_BLOCKED:
            icon = "\U0001f512"  # lock
        elif state == SIMULATED_READY:
            icon = "✅"  # check
        else:
            icon = "❌"  # cross
        lines.append(
            f"### {icon} {entry.get('proposal_id')} — {entry.get('skill_domain')}"
        )
        lines.append(f"- **Binding state:** {state}")
        lines.append(f"- **Source approval:** {entry.get('source_approval_status')}")
        lines.append(f"- **Binding allowed:** {entry.get('binding_allowed')}")
        lines.append(f"- **Binding blocked:** {entry.get('binding_blocked')}")
        lines.append(f"- **Traini required:** {entry.get('traini_gate_required')}")
        lines.append(f"- **Active registry changed:** {entry.get('active_runtime_registry_changed')}")
        lines.append(f"- **Blocking reasons:** {len(entry.get('blocking_reasons', []))}")
        lines.append("")

    path = out_dir / "runtime_binding_simulation_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def run_binding_workflow(
    approval_manifest_path: pathlib.Path = _DEFAULT_APPROVAL_MANIFEST,
    approval_report_path: pathlib.Path = _DEFAULT_APPROVAL_REPORT,
    out_dir: pathlib.Path = _DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    approval_entries = _load_approval_entries(approval_manifest_path, approval_report_path)

    binding_objs = simulate_all_bindings(approval_entries)
    binding_dicts = [b.to_dict() for b in binding_objs]

    matrix = build_binding_matrix(binding_objs)

    validator = RuntimeBindingValidator()
    validation_errors: list[dict[str, Any]] = []
    for bd, ae in zip(binding_dicts, approval_entries):
        if not validator.validate(bd, ae):
            validation_errors.append({
                "proposal_id": bd.get("proposal_id"),
                "errors": validator.errors,
            })

    output: dict[str, Any] = {
        "phase": "14",
        "schema_version": BINDING_SCHEMA_VERSION,
        "created_at": created_at,
        "approvals_loaded": len(approval_entries),
        "bindings_simulated": len(binding_dicts),
        "ready_for_dry_run_binding": matrix["ready_for_dry_run_binding"],
        "blocked_not_approved": matrix["blocked_not_approved"],
        "rejected_unsafe": matrix["rejected_unsafe"],
        "active_registry_changed": False,
        "validation_errors": validation_errors,
        "registry_valid": len(validation_errors) == 0,
        "next_allowed_phase": _NEXT_PHASE,
        "entries": binding_dicts,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = out_dir / "runtime_binding_simulation_report.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    matrix_path = out_dir / "runtime_binding_matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False))

    _write_md_report(output, out_dir)

    output["report_json"] = str(report_path)
    output["matrix_json"] = str(matrix_path)
    output["report_md"] = str(out_dir / "runtime_binding_simulation_report.md")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIMS Phase 14 — Dry-run Runtime Binding Simulation Workflow"
    )
    parser.add_argument(
        "--approval-manifest",
        type=pathlib.Path,
        default=_DEFAULT_APPROVAL_MANIFEST,
    )
    parser.add_argument(
        "--approval-report",
        type=pathlib.Path,
        default=_DEFAULT_APPROVAL_REPORT,
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_DEFAULT_OUT_DIR,
    )
    args = parser.parse_args()

    r = run_binding_workflow(
        approval_manifest_path=args.approval_manifest,
        approval_report_path=args.approval_report,
        out_dir=args.out,
    )

    print("=" * 60)
    print("AIMS Phase 14 — Dry-run Runtime Binding Simulation")
    print("=" * 60)
    print(f"approvals_loaded              : {r['approvals_loaded']}")
    print(f"bindings_simulated            : {r['bindings_simulated']}")
    print(f"ready_for_dry_run_binding     : {r['ready_for_dry_run_binding']}")
    print(f"blocked_not_approved          : {r['blocked_not_approved']}")
    print(f"rejected_unsafe               : {r['rejected_unsafe']}")
    print(f"active_registry_changed       : {r['active_registry_changed']}")
    print(f"output_dir                    : {args.out}")
    print(f"report JSON                   : {r['report_json']}")
    print(f"matrix JSON                   : {r['matrix_json']}")
    print(f"report MD                     : {r['report_md']}")


if __name__ == "__main__":
    main()
