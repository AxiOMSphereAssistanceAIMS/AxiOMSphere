"""
AIMS Self-Learning — Pre-Production Certification Workflow.

CLI:
  PYTHONPATH=ops python3 ops/agents/self_learning/preproduction_certification_workflow.py \
    --out aims_workspace/agent_self_learning/preproduction_certification

Collects evidence from Phases 5–14, validates, and writes a certification dossier.
No model calls, no activation, no registry modification.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import uuid
from typing import Any

_OPS = pathlib.Path(__file__).resolve().parents[2]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

try:
    from .preproduction_certification_schema import (
        CERTIFICATION_STATUS_READY_BLOCKED,
        CERTIFICATION_STATUS_BLOCKED,
        CERTIFICATION_SCHEMA_VERSION,
        FINAL_RECOMMENDATION,
        PHASES_COVERED,
        PreproductionCertificationPack,
    )
    from .preproduction_certification_collector import (
        collect_phase_artifacts,
        collect_smoke_results,
        collect_direct_workflow_summaries,
        build_safety_confirmations,
        build_go_no_go_matrix,
        build_activation_blockers,
        build_rollback_readiness,
        build_audit_trail_paths,
        build_required_human_decisions,
        collect_unresolved_blockers,
        collect_unresolved_warnings,
    )
    from .preproduction_certification_validator import PreproductionCertificationValidator
except ImportError:
    from agents.self_learning.preproduction_certification_schema import (  # type: ignore
        CERTIFICATION_STATUS_READY_BLOCKED,
        CERTIFICATION_STATUS_BLOCKED,
        CERTIFICATION_SCHEMA_VERSION,
        FINAL_RECOMMENDATION,
        PHASES_COVERED,
        PreproductionCertificationPack,
    )
    from agents.self_learning.preproduction_certification_collector import (  # type: ignore
        collect_phase_artifacts,
        collect_smoke_results,
        collect_direct_workflow_summaries,
        build_safety_confirmations,
        build_go_no_go_matrix,
        build_activation_blockers,
        build_rollback_readiness,
        build_audit_trail_paths,
        build_required_human_decisions,
        collect_unresolved_blockers,
        collect_unresolved_warnings,
    )
    from agents.self_learning.preproduction_certification_validator import PreproductionCertificationValidator  # type: ignore

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_OUT_DIR = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "preproduction_certification"
)
_NEXT_PHASE = "AIMS_SELF_LEARNING_PREPRODUCTION_CERTIFICATION_READY"


def _write_md_report(pack_dict: dict[str, Any], out_dir: pathlib.Path) -> None:
    status = pack_dict["certification_status"]
    gng = pack_dict["go_no_go_matrix"]
    sc = pack_dict["safety_confirmations"]
    smoke = pack_dict["smoke_results"]

    lines = [
        "# AIMS Phase 15 — Pre-Production Certification Pack Report",
        "",
        f"**Certification ID:** {pack_dict['certification_id']}",
        f"**Generated:** {pack_dict['created_at']}",
        f"**Status:** {status}",
        f"**Runtime Activation Status:** {pack_dict['runtime_activation_status']}",
        f"**Phases Covered:** {', '.join(str(p) for p in pack_dict['phases_covered'])}",
        "",
        "## Final Recommendation",
        "",
        pack_dict["final_recommendation"],
        "",
        "## Go/No-Go Matrix",
        "",
    ]
    for cat, value in gng.items():
        icon = "✅" if value else "❌"
        lines.append(f"- {icon} `{cat}`")
    lines.append("")

    lines += [
        "## Safety Confirmations",
        "",
    ]
    for item, value in sc.items():
        icon = "✅" if value else "❌"
        lines.append(f"- {icon} `{item}`")
    lines.append("")

    lines += [
        "## Smoke Test Sentinels",
        "",
    ]
    for phase_key, result in smoke.items():
        icon = "✅" if result.get("sentinel_found") else "❌"
        lines.append(f"- {icon} {phase_key}: `{result.get('sentinel')}`")
    lines.append("")

    lines += [
        "## Activation Blockers",
        "",
    ]
    for b in pack_dict["activation_blockers"]:
        lines.append(f"- {b}")
    lines.append("")

    lines += [
        "## Required Human Decisions Before Runtime Activation",
        "",
    ]
    for d in pack_dict["required_human_decisions_before_runtime"]:
        lines.append(f"- {d}")
    lines.append("")

    unresolved = pack_dict["unresolved_blockers"]
    if unresolved:
        lines += ["## Unresolved Blockers", ""]
        for b in unresolved:
            lines.append(f"- {b}")
        lines.append("")

    lines += [
        "## Rollback Readiness",
        "",
    ]
    for k, v in pack_dict["rollback_readiness"].items():
        icon = "✅" if v else "❌"
        lines.append(f"- {icon} `{k}`")
    lines.append("")

    path = out_dir / "preproduction_certification_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_summary(pack_dict: dict[str, Any], out_dir: pathlib.Path) -> None:
    smoke = pack_dict["smoke_results"]
    phase_artifacts = pack_dict["phase_artifacts"]

    required_found = 0
    required_missing = 0
    for phase_data in phase_artifacts.values():
        for entry in phase_data.values():
            if entry.get("found"):
                required_found += 1
            else:
                required_missing += 1

    sentinels_found = sum(1 for v in smoke.values() if v.get("sentinel_found"))

    summary = {
        "certification_id": pack_dict["certification_id"],
        "certification_status": pack_dict["certification_status"],
        "created_at": pack_dict["created_at"],
        "phases_covered": pack_dict["phases_covered"],
        "required_artifacts_found": required_found,
        "required_artifacts_missing": required_missing,
        "smoke_sentinels_passed": sentinels_found,
        "smoke_suite_passed": sentinels_found == len(smoke),
        "runtime_activation_allowed": False,
        "active_registry_modified": False,
        "phase_13_approvals_blocked": pack_dict["direct_workflow_summaries"].get("phase_13", {}).get("blocked", 0),
        "phase_14_bindings_blocked": pack_dict["direct_workflow_summaries"].get("phase_14", {}).get("blocked_not_approved", 0),
        "unresolved_blockers_count": len(pack_dict["unresolved_blockers"]),
        "activation_blockers_count": len(pack_dict["activation_blockers"]),
        "final_recommendation": pack_dict["final_recommendation"],
    }
    path = out_dir / "preproduction_certification_summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def run_certification_workflow(
    out_dir: pathlib.Path = _DEFAULT_OUT_DIR,
    repo_root: pathlib.Path = _REPO_ROOT,
) -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    certification_id = f"preproduction-cert-{uuid.uuid4().hex[:12]}"

    phase_artifacts = collect_phase_artifacts(repo_root)
    smoke_results = collect_smoke_results(repo_root)
    direct_workflow_summaries = collect_direct_workflow_summaries(repo_root)
    safety_confirmations = build_safety_confirmations()
    go_no_go_matrix = build_go_no_go_matrix(phase_artifacts, smoke_results, direct_workflow_summaries)
    activation_blockers = build_activation_blockers()
    rollback_readiness = build_rollback_readiness(phase_artifacts)
    audit_trail_paths = build_audit_trail_paths(repo_root)
    required_human_decisions = build_required_human_decisions()
    unresolved_blockers = collect_unresolved_blockers(
        phase_artifacts, smoke_results, direct_workflow_summaries
    )
    unresolved_warnings = collect_unresolved_warnings(phase_artifacts)

    # Determine certification status
    if unresolved_blockers:
        certification_status = CERTIFICATION_STATUS_BLOCKED
    else:
        # All phases covered, all sentinels found — but runtime remains blocked by design
        certification_status = CERTIFICATION_STATUS_READY_BLOCKED

    pack = PreproductionCertificationPack(
        certification_id=certification_id,
        created_at=created_at,
        certification_status=certification_status,
        runtime_activation_status="RUNTIME_BLOCKED_BY_DESIGN",
        phases_covered=PHASES_COVERED,
        phase_artifacts=phase_artifacts,
        smoke_results=smoke_results,
        direct_workflow_summaries=direct_workflow_summaries,
        safety_confirmations=safety_confirmations,
        unresolved_blockers=unresolved_blockers,
        unresolved_warnings=unresolved_warnings,
        go_no_go_matrix=go_no_go_matrix,
        activation_blockers=activation_blockers,
        rollback_readiness=rollback_readiness,
        audit_trail_paths=audit_trail_paths,
        required_human_decisions_before_runtime=required_human_decisions,
        final_recommendation=FINAL_RECOMMENDATION,
    )

    pack_dict = pack.to_dict()

    validator = PreproductionCertificationValidator()
    validation_passed = validator.validate(pack_dict)
    pack_dict["validation_passed"] = validation_passed
    pack_dict["validation_errors"] = validator.errors
    pack_dict["validation_warnings"] = validator.warnings

    out_dir.mkdir(parents=True, exist_ok=True)

    pack_path = out_dir / "preproduction_certification_pack.json"
    pack_path.write_text(json.dumps(pack_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    _write_md_report(pack_dict, out_dir)

    smoke_only = {
        k: {"sentinel_found": v["sentinel_found"], "sentinel": v["sentinel"]}
        for k, v in smoke_results.items()
    }
    gng_path = out_dir / "preproduction_go_no_go_matrix.json"
    gng_path.write_text(
        json.dumps({
            "go_no_go_matrix": go_no_go_matrix,
            "smoke_sentinels": smoke_only,
            "safety_confirmations": safety_confirmations,
            "certification_status": certification_status,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = _write_summary(pack_dict, out_dir)

    pack_dict["pack_json"] = str(pack_path)
    pack_dict["report_md"] = str(out_dir / "preproduction_certification_report.md")
    pack_dict["summary_json"] = str(out_dir / "preproduction_certification_summary.json")
    pack_dict["go_no_go_json"] = str(gng_path)
    pack_dict["_summary"] = summary
    return pack_dict


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIMS Phase 15 — Pre-Production Certification Workflow"
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_DEFAULT_OUT_DIR,
    )
    args = parser.parse_args()

    r = run_certification_workflow(out_dir=args.out)

    print("=" * 60)
    print("AIMS Phase 15 — Pre-Production Certification Pack")
    print("=" * 60)
    s = r.get("_summary", {})
    print(f"certification_id              : {r['certification_id']}")
    print(f"certification_status          : {r['certification_status']}")
    print(f"phases_covered                : {r['phases_covered']}")
    print(f"required_artifacts_found      : {s.get('required_artifacts_found')}")
    print(f"required_artifacts_missing    : {s.get('required_artifacts_missing')}")
    print(f"smoke_suite_passed            : {s.get('smoke_suite_passed')}")
    print(f"runtime_activation_allowed    : {s.get('runtime_activation_allowed')}")
    print(f"active_registry_modified      : {s.get('active_registry_modified')}")
    print(f"phase_13_approvals_blocked    : {s.get('phase_13_approvals_blocked')}")
    print(f"phase_14_bindings_blocked     : {s.get('phase_14_bindings_blocked')}")
    print(f"unresolved_blockers           : {s.get('unresolved_blockers_count')}")
    print(f"validation_passed             : {r.get('validation_passed')}")
    print(f"output_dir                    : {args.out}")
    print(f"pack JSON                     : {r['pack_json']}")
    print(f"report MD                     : {r['report_md']}")
    print(f"summary JSON                  : {r['summary_json']}")
    print(f"go/no-go JSON                 : {r['go_no_go_json']}")
    print()
    print(f"Final recommendation: {r['final_recommendation']}")


if __name__ == "__main__":
    main()
