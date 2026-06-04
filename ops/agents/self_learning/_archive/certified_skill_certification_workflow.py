"""
AIMS Self-Learning — Certified Skill Certification Workflow.

CLI: PYTHONPATH=ops python3 ops/agents/self_learning/certified_skill_certification_workflow.py \
  --execution-report aims_workspace/agent_self_learning/sandbox_runs/sandbox_execution_report.json \
  --evidence-pack aims_workspace/agent_self_learning/sandbox_runs/sandbox_execution_evidence_pack.json \
  --out aims_workspace/agent_self_learning/certifications

Reads Phase 9 outputs, generates certification packages, validates them,
and writes JSON + MD reports. No model calls, no runtime changes.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
from typing import Any

# Allow direct execution: python3 ops/agents/self_learning/certified_skill_certification_workflow.py
_OPS = pathlib.Path(__file__).resolve().parents[2]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

try:
    from .certified_skill_package_generator import generate_packages
    from .certified_skill_package_validator import CertifiedSkillPackageValidator
    from .certified_skill_schema import CERT_STATUS_READY, CERT_STATUS_WARN, CERT_STATUS_REJECTED
except ImportError:
    from agents.self_learning.certified_skill_package_generator import generate_packages  # type: ignore
    from agents.self_learning.certified_skill_package_validator import CertifiedSkillPackageValidator  # type: ignore
    from agents.self_learning.certified_skill_schema import CERT_STATUS_READY, CERT_STATUS_WARN, CERT_STATUS_REJECTED  # type: ignore

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_EXEC_REPORT = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "sandbox_runs" / "sandbox_execution_report.json"
)
_DEFAULT_EVIDENCE_PACK = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "sandbox_runs" / "sandbox_execution_evidence_pack.json"
)
_DEFAULT_OUT_DIR = _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "certifications"

_NEXT_PHASE = "AIMS_SANDBOX_SKILL_CERTIFICATION_COMPLETE"


def _load_json(path: pathlib.Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_md_report(output: dict[str, Any], out_dir: pathlib.Path) -> None:
    lines = [
        "# AIMS Phase 10 — Certified Skill Certification Report",
        "",
        f"**Generated:** {output['created_at']}",
        f"**Executions loaded:** {output['executions_loaded']}",
        f"**Certified READY:** {output['certified_ready']}",
        f"**Certified WARN:** {output['certified_warn']}",
        f"**Rejected:** {output['rejected']}",
        f"**Packages written:** {output['packages_written']}",
        f"**Workflow valid:** {output['workflow_valid']}",
        f"**Next phase:** {output['next_allowed_phase']}",
        "",
        "## Safety Invariants",
        "",
        "- `runtime_activation_allowed` = **False** for all packages",
        "- `self_approval_allowed` = **False** for all packages",
        "- `active_runtime_requested` = **False** for all packages",
        "- No package targets `ACTIVE_RUNTIME_SKILL`",
        "- All runtime gates still required before any activation",
        "",
        "## Certified Packages",
        "",
    ]
    for pkg in output.get("packages", []):
        status = pkg.get("certification_status", "UNKNOWN")
        icon = "✅" if status == CERT_STATUS_READY else ("⚠️" if status == CERT_STATUS_WARN else "❌")
        lines.append(f"### {icon} {pkg.get('certified_skill_id')} — {pkg.get('candidate_skill_id')}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Domain:** {pkg.get('skill_domain')}")
        lines.append(f"- **Execution:** {pkg.get('execution_id')}")
        lines.append(f"- **Model related:** {pkg.get('model_related')}")
        lines.append(f"- **Production related:** {pkg.get('production_related')}")
        gates = pkg.get("gates_required_before_runtime", [])
        lines.append(f"- **Gates before runtime:** {len(gates)}")
        lines.append("")

    if output.get("skipped"):
        lines.append("## Skipped (Not Certified)")
        lines.append("")
        for s in output["skipped"]:
            lines.append(f"- `{s.get('execution_id')}` ({s.get('skill_id')}): {s.get('reason')}")
        lines.append("")

    path = out_dir / "certification_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def run_certification_workflow(
    exec_report_path: pathlib.Path = _DEFAULT_EXEC_REPORT,
    evidence_pack_path: pathlib.Path = _DEFAULT_EVIDENCE_PACK,
    out_dir: pathlib.Path = _DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    exec_report = _load_json(exec_report_path)
    evidence_pack = _load_json(evidence_pack_path)

    execution_results: list[dict[str, Any]] = exec_report.get("results", [])

    packages, skipped = generate_packages(execution_results, evidence_pack)

    validator = CertifiedSkillPackageValidator()
    pkg_dicts: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []

    for pkg in packages:
        d = pkg.to_dict()
        if validator.validate(d):
            pkg_dicts.append(d)
        else:
            validation_errors.append({
                "certified_skill_id": d.get("certified_skill_id"),
                "errors": validator.errors,
            })
            pkg_dicts.append(d)

    ready_count = sum(1 for d in pkg_dicts if d.get("certification_status") == CERT_STATUS_READY)
    warn_count = sum(1 for d in pkg_dicts if d.get("certification_status") == CERT_STATUS_WARN)
    rejected_count = len(skipped)

    output: dict[str, Any] = {
        "phase": "10",
        "created_at": created_at,
        "executions_loaded": len(execution_results),
        "certified_ready": ready_count,
        "certified_warn": warn_count,
        "rejected": rejected_count,
        "packages_written": len(pkg_dicts),
        "validation_errors": validation_errors,
        "workflow_valid": len(validation_errors) == 0,
        "next_allowed_phase": _NEXT_PHASE,
        "packages": pkg_dicts,
        "skipped": skipped,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    packages_path = out_dir / "certified_skill_packages.json"
    packages_path.write_text(
        json.dumps({"packages": pkg_dicts}, indent=2, ensure_ascii=False)
    )

    report_path = out_dir / "certification_report.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    _write_md_report(output, out_dir)

    output["packages_json"] = str(packages_path)
    output["report_json"] = str(report_path)
    output["report_md"] = str(out_dir / "certification_report.md")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIMS Phase 10 — Certified Skill Certification Workflow"
    )
    parser.add_argument(
        "--execution-report",
        type=pathlib.Path,
        default=_DEFAULT_EXEC_REPORT,
    )
    parser.add_argument(
        "--evidence-pack",
        type=pathlib.Path,
        default=_DEFAULT_EVIDENCE_PACK,
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_DEFAULT_OUT_DIR,
    )
    args = parser.parse_args()

    r = run_certification_workflow(
        exec_report_path=args.execution_report,
        evidence_pack_path=args.evidence_pack,
        out_dir=args.out,
    )

    print("=" * 60)
    print("AIMS Phase 10 — Certified Skill Certification Workflow")
    print("=" * 60)
    print(f"executions_loaded  : {r['executions_loaded']}")
    print(f"certified_ready    : {r['certified_ready']}")
    print(f"certified_warn     : {r['certified_warn']}")
    print(f"rejected           : {r['rejected']}")
    print(f"packages_written   : {r['packages_written']}")
    print(f"workflow_valid     : {r['workflow_valid']}")
    print(f"output_dir         : {args.out}")
    print(f"packages JSON      : {r['packages_json']}")
    print(f"report JSON        : {r['report_json']}")
    print(f"report MD          : {r['report_md']}")


if __name__ == "__main__":
    main()
