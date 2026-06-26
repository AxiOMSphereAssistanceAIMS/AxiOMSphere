from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REUSABLE_FAILURE_MODES = {
    "evidence_only_completion_without_feature_implementation",
    "tests_only_no_production_wiring",
    "mocked_path_claimed_as_production",
    "missing_artifact_paths",
    "no_limited_production_run",
}

DEFAULT_SKILL_NAME = "docsreg-feature-completion-verification"

DEFAULT_CHECKLIST = [
    "Compare requested deliverables against actual files.",
    "Verify production files exist in repo, not only evidence.",
    "Verify entrypoint/wiring exists.",
    "Verify tests exist and pass.",
    "Verify limited production run exercises the new implementation.",
    "Verify no mocked path is claimed as production.",
    "If requested files are missing, report NOT READY, not COMPLETE.",
]


def skill_name_for_failure_modes(failure_modes: list[str]) -> str | None:
    if any(mode in REUSABLE_FAILURE_MODES for mode in failure_modes):
        return DEFAULT_SKILL_NAME
    return None


def create_or_update_skill_proposal(
    *,
    output_root: str | Path,
    case_id: str,
    failure_modes: list[str],
    skill_name: str | None = None,
) -> dict[str, Any] | None:
    resolved = skill_name or skill_name_for_failure_modes(failure_modes)
    if not resolved:
        return None
    proposal_dir = Path(output_root) / "skill_proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    json_path = proposal_dir / f"{resolved}.json"
    md_path = proposal_dir / f"{resolved}.md"

    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        data = {
            "skill_name": resolved,
            "status": "PROPOSED",
            "case_ids": [],
            "failure_modes": [],
            "checklist": list(DEFAULT_CHECKLIST),
            "approved_for_training": False,
            "requires_human_approval": True,
        }
    data["case_ids"] = sorted(set(list(data.get("case_ids") or []) + [case_id]))
    data["failure_modes"] = sorted(set(list(data.get("failure_modes") or []) + list(failure_modes)))
    data["approved_for_training"] = False
    data["requires_human_approval"] = True
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Skill Proposal: {resolved}",
        "",
        "Status: PROPOSED",
        "Approved for training: false",
        "Requires human approval: true",
        "",
        "## Failure Modes",
        *[f"- {mode}" for mode in data["failure_modes"]],
        "",
        "## Cases",
        *[f"- {cid}" for cid in data["case_ids"]],
        "",
        "## Checklist",
        *[f"{idx}. {item}" for idx, item in enumerate(DEFAULT_CHECKLIST, start=1)],
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    data["json_path"] = str(json_path)
    data["markdown_path"] = str(md_path)
    return data
