"""
AIMS Phase 17 — Hermes-Inspired Skill Curator Workflow.

CLI:
  PYTHONPATH=ops python3 ops/agents/self_learning/aims_skill_curator_workflow.py \
    --fixtures ops/evals/fixtures/self_learning \
    --out aims_workspace/agent_self_learning/hermes_inspired_skill_curator

Loads observed patterns, runs curator, validates, writes output.
No model calls, no Hermes runtime, no registry modification.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

_OPS = pathlib.Path(__file__).resolve().parents[2]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

try:
    from .hermes_inspired_skill_curator_schema import (
        SCHEMA_VERSION,
        PHASE,
        HERMES_REFERENCE_CATEGORIES,
        AIMS_AUTHORING_POLICIES,
        CURATOR_STATUS_READY,
        CURATOR_STATUS_BLOCKED,
        SkillCurationReport,
    )
    from .hermes_skill_reference_mapper import load_hermes_references
    from .hermes_inspired_skill_curator import HermesInspiredSkillCurator
    from .aims_skill_improvement_loop import SkillImprovementLoop
    from .aims_skill_curator_validator import SkillCuratorValidator
except ImportError:
    from agents.self_learning.hermes_inspired_skill_curator_schema import (  # type: ignore
        SCHEMA_VERSION,
        PHASE,
        HERMES_REFERENCE_CATEGORIES,
        AIMS_AUTHORING_POLICIES,
        CURATOR_STATUS_READY,
        CURATOR_STATUS_BLOCKED,
        SkillCurationReport,
    )
    from agents.self_learning.hermes_skill_reference_mapper import load_hermes_references  # type: ignore
    from agents.self_learning.hermes_inspired_skill_curator import HermesInspiredSkillCurator  # type: ignore
    from agents.self_learning.aims_skill_improvement_loop import SkillImprovementLoop  # type: ignore
    from agents.self_learning.aims_skill_curator_validator import SkillCuratorValidator  # type: ignore

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_OUT_DIR = (
    _REPO_ROOT / "aims_workspace" / "agent_self_learning" / "hermes_inspired_skill_curator"
)
_DEFAULT_FIXTURES = _REPO_ROOT / "ops" / "evals" / "fixtures" / "self_learning"


def _load_observed_patterns(fixtures_dir: pathlib.Path) -> list[dict]:
    """Load observed pattern candidates from fixture file."""
    fixture_path = fixtures_dir / "hermes_inspired_observed_patterns.json"
    if fixture_path.exists():
        return json.loads(fixture_path.read_text(encoding="utf-8"))
    # Fallback: minimal built-in set for testing
    return [
        {
            "candidate_id": "obs-doc-gen-001",
            "name": "Repeated document generation pattern",
            "description": "User repeatedly requests inspection reports with similar structure.",
            "hermes_reference_category": "skill-authoring",
            "state": "OBSERVED_PATTERN",
            "metadata": {"source": "axi_bot_log", "count": 12},
        },
        {
            "candidate_id": "obs-repair-002",
            "name": "Systematic repair diagnosis",
            "description": "Repairman consistently applies root-cause → patch → verify cycle.",
            "hermes_reference_category": "systematic-debugging",
            "state": "OBSERVED_PATTERN",
            "metadata": {"source": "repairman_memory", "count": 7},
        },
        {
            "candidate_id": "obs-ocr-003",
            "name": "OCR document ingestion pattern",
            "description": "OmiAgent repeatedly processes scanned PDFs through OCR pipeline.",
            "hermes_reference_category": "ocr-and-documents",
            "state": "OBSERVED_PATTERN",
            "metadata": {"source": "omi_agent_log", "count": 23},
        },
        {
            "candidate_id": "obs-plan-004",
            "name": "Phase planning pattern",
            "description": "Each AIMS phase begins with acceptance criteria definition.",
            "hermes_reference_category": "plan",
            "state": "OBSERVED_PATTERN",
            "metadata": {"source": "session_history", "count": 17},
        },
        {
            "candidate_id": "obs-review-005",
            "name": "Code review gate pattern",
            "description": "All skill candidates require Poli approval before activation.",
            "hermes_reference_category": "requesting-code-review",
            "state": "CANDIDATE_SKILL",
            "metadata": {"source": "poli_agent_log", "count": 9},
        },
    ]


def _write_md_report(report_dict: dict, out_dir: pathlib.Path) -> None:
    lines = [
        "# AIMS Phase 17 — Hermes-Inspired Skill Curator Report",
        "",
        f"**Phase:** {report_dict['phase']}",
        f"**Generated:** {report_dict['created_at']}",
        f"**Curator Status:** {report_dict['curator_status']}",
        f"**Hermes References Loaded:** {report_dict['hermes_references_loaded']}",
        f"**Candidates Evaluated:** {report_dict['candidates_evaluated']}",
        "",
        "## Decision Summary",
        "",
    ]
    for decision, count in report_dict["decisions"].items():
        lines.append(f"- `{decision}`: {count}")

    lines += ["", "## Safety Invariants", ""]
    policy = report_dict["policy_summary"]
    for k, v in policy.items():
        icon = "✅" if v else "❌"
        lines.append(f"- {icon} `{k}`")

    lines += ["", "## Candidates", ""]
    for c in report_dict["candidates"]:
        lines += [
            f"### {c['name']} (`{c['candidate_id']}`)",
            f"- **State:** `{c['state']}`",
            f"- **Decision:** `{c['curator_decision']}`",
            f"- **Hermes Reference:** `{c['hermes_reference_category'] or 'none'}`",
            f"- **Rationale:** {c['curator_rationale']}",
        ]
        if c["authoring_policy_violations"]:
            lines += ["- **Violations:**"]
            for v in c["authoring_policy_violations"]:
                lines.append(f"  - {v}")
        lines.append("")

    lines += ["## Hermes Reference Index", ""]
    for ref in report_dict["hermes_references"]:
        lines += [
            f"### {ref['hermes_category']} → {ref['hermes_pattern_name']}",
            f"- **Phases:** {ref['applicable_aims_phases']}",
            f"- **Notes:** {ref['aims_adaptation_notes'][:120]}...",
            "",
        ]

    if report_dict["unresolved_blockers"]:
        lines += ["## Unresolved Blockers", ""]
        for b in report_dict["unresolved_blockers"]:
            lines.append(f"- ⚠️ {b}")
        lines.append("")

    lines += [
        "## Validation",
        "",
        f"- **Validation Passed:** {report_dict['validation_passed']}",
    ]
    if report_dict["validation_errors"]:
        lines += ["", "### Validation Errors", ""]
        for e in report_dict["validation_errors"]:
            lines.append(f"- ❌ {e}")

    (out_dir / "curation_report.md").write_text("\n".join(lines), encoding="utf-8")


def run_curator_workflow(
    out_dir: pathlib.Path = _DEFAULT_OUT_DIR,
    fixtures_dir: pathlib.Path = _DEFAULT_FIXTURES,
    repo_root: pathlib.Path = _REPO_ROOT,
) -> dict:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Load references and observed patterns
    hermes_refs = load_hermes_references()
    observed = _load_observed_patterns(fixtures_dir)

    # Run curator
    curator = HermesInspiredSkillCurator()
    evaluated = curator.evaluate(observed)
    decisions = curator.summarize_decisions(evaluated)

    # Improvement loop (dry run — just initialize)
    improvement_loop = SkillImprovementLoop()
    improvement_summary = improvement_loop.build_improvement_summary()

    # Policy summary
    policy_summary = {
        "active_registry_modified": False,
        "hermes_runtime_invoked": False,
        "model_endpoints_called": False,
        "training_launched": False,
        "model_promoted": False,
        "slot120_loaded": False,
        "slot32_unloaded": False,
        "service_restarted": False,
        "self_approval_granted": False,
        "human_review_required": True,
    }

    total_violations = sum(len(c.authoring_policy_violations) for c in evaluated)
    unresolved_blockers: list[str] = []
    for c in evaluated:
        for v in c.authoring_policy_violations:
            unresolved_blockers.append(
                f"Candidate {c.candidate_id}: {v}"
            )

    curator_status = (
        CURATOR_STATUS_BLOCKED if unresolved_blockers else CURATOR_STATUS_READY
    )

    report = SkillCurationReport(
        phase=PHASE,
        schema_version=SCHEMA_VERSION,
        created_at=created_at,
        curator_status=curator_status,
        hermes_references_loaded=len(hermes_refs),
        candidates_evaluated=len(evaluated),
        decisions=decisions,
        authoring_policy_violations_found=total_violations,
        active_registry_modified=False,
        hermes_runtime_invoked=False,
        model_endpoints_called=False,
        training_launched=False,
        candidates=[c.to_dict() for c in evaluated],
        hermes_references=[r.to_dict() for r in hermes_refs],
        policy_summary=policy_summary,
        unresolved_blockers=unresolved_blockers,
    )

    report_dict = report.to_dict()

    validator = SkillCuratorValidator()
    validation_passed = validator.validate(report_dict)
    report_dict["validation_passed"] = validation_passed
    report_dict["validation_errors"] = validator.errors
    report_dict["validation_warnings"] = validator.warnings
    report_dict["improvement_summary"] = improvement_summary

    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "curation_report.json").write_text(
        json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_md_report(report_dict, out_dir)

    # Write hermes_reference_index.json
    ref_index = {r.hermes_category: r.to_dict() for r in hermes_refs}
    (out_dir / "hermes_reference_index.json").write_text(
        json.dumps(ref_index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write curator_decisions.json
    (out_dir / "curator_decisions.json").write_text(
        json.dumps(
            {
                "created_at": created_at,
                "decisions": decisions,
                "candidates": [
                    {
                        "candidate_id": c.candidate_id,
                        "name": c.name,
                        "state": c.state,
                        "curator_decision": c.curator_decision,
                        "hermes_reference_category": c.hermes_reference_category,
                    }
                    for c in evaluated
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Write policy_audit.json
    (out_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "created_at": created_at,
                "policy_summary": policy_summary,
                "authoring_policy_violations_found": total_violations,
                "unresolved_blockers": unresolved_blockers,
                "improvement_summary": improvement_summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report_dict["out_dir"] = str(out_dir)
    return report_dict


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIMS Phase 17 — Hermes-Inspired Skill Curator Workflow"
    )
    parser.add_argument("--out", type=pathlib.Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--fixtures", type=pathlib.Path, default=_DEFAULT_FIXTURES)
    args = parser.parse_args()

    r = run_curator_workflow(out_dir=args.out, fixtures_dir=args.fixtures)

    print("=" * 60)
    print("AIMS Phase 17 — Hermes-Inspired Skill Curator")
    print("=" * 60)
    print(f"curator_status              : {r['curator_status']}")
    print(f"hermes_references_loaded    : {r['hermes_references_loaded']}")
    print(f"candidates_evaluated        : {r['candidates_evaluated']}")
    print(f"decisions                   : {r['decisions']}")
    print(f"policy_violations_found     : {r['authoring_policy_violations_found']}")
    print(f"active_registry_modified    : {r['active_registry_modified']}")
    print(f"hermes_runtime_invoked      : {r['hermes_runtime_invoked']}")
    print(f"training_launched           : {r['training_launched']}")
    print(f"unresolved_blockers         : {len(r['unresolved_blockers'])}")
    print(f"validation_passed           : {r['validation_passed']}")
    print(f"output_dir                  : {r['out_dir']}")


if __name__ == "__main__":
    main()
