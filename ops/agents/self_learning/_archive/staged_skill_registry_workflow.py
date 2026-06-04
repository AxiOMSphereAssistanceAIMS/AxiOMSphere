"""
AIMS Self-Learning — Staged Skill Registry Workflow.

CLI: PYTHONPATH=ops python3 ops/agents/self_learning/staged_skill_registry_workflow.py \
  --certified-packages aims_workspace/agent_self_learning/certifications/certified_skill_packages.json \
  --out aims_workspace/agent_self_learning/staged_registry

Reads Phase 10 outputs, stages eligible certified skill packages,
validates them, and writes JSON + MD reports. No model calls, no runtime changes.
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
    from .staged_skill_registry_builder import build_staged_registry, load_certified_packages
    from .staged_skill_registry_validator import StagedSkillRegistryValidator
    from .staged_skill_registry_schema import (
        STAGING_STATUS_REVIEW,
        STAGING_STATUS_WARN,
        STAGING_STATUS_REJECTED,
    )
except ImportError:
    from agents.self_learning.staged_skill_registry_builder import build_staged_registry, load_certified_packages  # type: ignore
    from agents.self_learning.staged_skill_registry_validator import StagedSkillRegistryValidator  # type: ignore
    from agents.self_learning.staged_skill_registry_schema import (  # type: ignore
        STAGING_STATUS_REVIEW,
        STAGING_STATUS_WARN,
        STAGING_STATUS_REJECTED,
    )

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_CERTIFIED_PACKAGES = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "certifications" / "certified_skill_packages.json"
)
_DEFAULT_OUT_DIR = _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "staged_registry"

_NEXT_PHASE = "AIMS_CERTIFIED_SKILL_REGISTRY_STAGING_COMPLETE"


def _write_md_report(output: dict[str, Any], out_dir: pathlib.Path) -> None:
    lines = [
        "# AIMS Phase 11 — Certified Skill Registry Staging Report",
        "",
        f"**Generated:** {output['created_at']}",
        f"**Certified packages loaded:** {output['certified_packages_loaded']}",
        f"**Staged for review:** {output['staged_for_review']}",
        f"**Staged with warnings:** {output['staged_with_warnings']}",
        f"**Rejected from staging:** {output['rejected_from_staging']}",
        f"**Registry valid:** {output['registry_valid']}",
        f"**Next phase:** {output['next_allowed_phase']}",
        "",
        "## Safety Invariants",
        "",
        "- `runtime_activation_allowed` = **False** for all entries",
        "- `self_approval_allowed` = **False** for all entries",
        "- `active_runtime_requested` = **False** for all entries",
        "- `activation_request_status` = **BLOCKED** (gates pending) for all entries",
        "- No entry targets `ACTIVE_RUNTIME_SKILL`",
        "- All runtime gates still required before any activation",
        "",
        "## Staged Entries",
        "",
    ]

    for entry in output.get("staged_entries", []):
        status = entry.get("staging_status", "UNKNOWN")
        icon = "✅" if status == STAGING_STATUS_REVIEW else ("⚠️" if status == STAGING_STATUS_WARN else "❌")
        lines.append(f"### {icon} {entry.get('staged_skill_id')} — {entry.get('candidate_skill_id')}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Domain:** {entry.get('skill_domain')}")
        lines.append(f"- **Certified ID:** {entry.get('certified_skill_id')}")
        lines.append(f"- **Model related:** {entry.get('model_related')}")
        lines.append(f"- **Production related:** {entry.get('production_related')}")
        lines.append(f"- **Activation:** {entry.get('activation_request_status')}")
        lines.append(f"- **Gates required:** {len(entry.get('required_runtime_gates', []))}")
        lines.append("")

    if output.get("rejected"):
        lines.append("## Rejected from Staging")
        lines.append("")
        for r in output["rejected"]:
            lines.append(f"- `{r.get('certified_skill_id')}` ({r.get('candidate_skill_id')}): {r.get('reason')}")
        lines.append("")

    path = out_dir / "staged_registry_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def run_staging_workflow(
    certified_packages_path: pathlib.Path = _DEFAULT_CERTIFIED_PACKAGES,
    out_dir: pathlib.Path = _DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    certified_packages = load_certified_packages(certified_packages_path)

    entries, rejected = build_staged_registry(certified_packages)

    validator = StagedSkillRegistryValidator()
    entry_dicts: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []

    for entry in entries:
        d = entry.to_dict()
        if validator.validate(d):
            entry_dicts.append(d)
        else:
            validation_errors.append({
                "staged_skill_id": d.get("staged_skill_id"),
                "errors": validator.errors,
            })
            entry_dicts.append(d)

    review_count = sum(1 for d in entry_dicts if d.get("staging_status") == STAGING_STATUS_REVIEW)
    warn_count = sum(1 for d in entry_dicts if d.get("staging_status") == STAGING_STATUS_WARN)

    output: dict[str, Any] = {
        "phase": "11",
        "created_at": created_at,
        "certified_packages_loaded": len(certified_packages),
        "staged_for_review": review_count,
        "staged_with_warnings": warn_count,
        "rejected_from_staging": len(rejected),
        "entries_written": len(entry_dicts),
        "validation_errors": validation_errors,
        "registry_valid": len(validation_errors) == 0,
        "next_allowed_phase": _NEXT_PHASE,
        "staged_entries": entry_dicts,
        "rejected": rejected,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    staged_path = out_dir / "staged_certified_skills.json"
    staged_path.write_text(
        json.dumps({"staged_entries": entry_dicts}, indent=2, ensure_ascii=False)
    )

    report_path = out_dir / "staged_registry_report.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    _write_md_report(output, out_dir)

    output["staged_json"] = str(staged_path)
    output["report_json"] = str(report_path)
    output["report_md"] = str(out_dir / "staged_registry_report.md")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIMS Phase 11 — Certified Skill Registry Staging Workflow"
    )
    parser.add_argument(
        "--certified-packages",
        type=pathlib.Path,
        default=_DEFAULT_CERTIFIED_PACKAGES,
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_DEFAULT_OUT_DIR,
    )
    args = parser.parse_args()

    r = run_staging_workflow(
        certified_packages_path=args.certified_packages,
        out_dir=args.out,
    )

    print("=" * 60)
    print("AIMS Phase 11 — Certified Skill Registry Staging Workflow")
    print("=" * 60)
    print(f"certified_packages_loaded : {r['certified_packages_loaded']}")
    print(f"staged_for_review         : {r['staged_for_review']}")
    print(f"staged_with_warnings      : {r['staged_with_warnings']}")
    print(f"rejected_from_staging     : {r['rejected_from_staging']}")
    print(f"registry_valid            : {r['registry_valid']}")
    print(f"output_dir                : {args.out}")
    print(f"staged JSON               : {r['staged_json']}")
    print(f"report JSON               : {r['report_json']}")
    print(f"report MD                 : {r['report_md']}")


if __name__ == "__main__":
    main()
