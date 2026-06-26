from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ops.learning_capture.git_capture import capture_commit_diff
from ops.learning_capture.models import (
    AgentActionCase,
    CodexRepairComparison,
    dataclass_from_dict,
    dataclass_to_dict,
)
from ops.learning_capture.skill_proposal_builder import create_or_update_skill_proposal, skill_name_for_failure_modes
from ops.learning_capture.training_candidate_writer import append_training_candidate


def load_case(output_root: str | Path, case_id: str) -> AgentActionCase:
    path = Path(output_root) / "cases" / case_id / "case.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return dataclass_from_dict(AgentActionCase, data)


def summarize_case(case: AgentActionCase) -> str:
    modes = ", ".join(case.failure_modes) if case.failure_modes else "none"
    return (
        f"{case.agent_name} on {case.target_slot}; outcome={case.outcome}; "
        f"actual_deliverables={len(case.actual_deliverables)}/{len(case.expected_deliverables)}; "
        f"failure_modes={modes}"
    )


def summarize_codex_repair(codex_evidence_root: str | Path, codex_commit: str) -> str:
    root = Path(codex_evidence_root)
    parts = [f"codex_commit={codex_commit or 'none'}"]
    if root.exists():
        parts.append(f"codex_evidence_root={root}")
        summary_candidates = [
            root / "markitdown_production_activation_status.md",
            root / "markitdown_runtime_standardization_status.md",
            root / "summary.md",
        ]
        for path in summary_candidates:
            if path.exists():
                parts.append(path.read_text(encoding="utf-8", errors="replace")[:1000])
                break
    else:
        parts.append("codex_evidence_root_missing")
    return "\n".join(parts)


def same_task_identity(case: AgentActionCase, codex_evidence_root: str | Path, codex_commit: str) -> bool:
    if not codex_commit:
        return False
    root_text = str(codex_evidence_root).lower()
    prompt = case.task_prompt.lower()
    if "markitdown" in prompt and "markitdown" in root_text:
        return True
    expected_names = [Path(item).name.lower() for item in case.expected_deliverables]
    return any(name and name in root_text for name in expected_names)


def build_codex_repair_comparison(
    *,
    case_id: str,
    codex_evidence_root: str | Path,
    codex_commit: str,
    output_root: str | Path,
    repo_root: str | Path = ".",
) -> tuple[CodexRepairComparison, dict[str, Any]]:
    output = Path(output_root)
    case = load_case(output, case_id)
    case_dir = output / "cases" / case_id
    chosen_diff = capture_commit_diff(
        commit=codex_commit,
        output_path=case_dir / "codex_chosen_diff.patch",
        repo_root=repo_root,
    )
    same_identity = same_task_identity(case, codex_evidence_root, codex_commit)
    eligible_skill = bool(case.failure_modes)
    eligible_sft = same_identity and bool(case.task_prompt.strip()) and Path(codex_evidence_root).exists()
    eligible_dpo = same_identity and bool(case.git_diff_path or case.terminal_log_path) and bool(chosen_diff or Path(codex_evidence_root).exists())

    comparison = CodexRepairComparison(
        case_id=case_id,
        rejected_summary=summarize_case(case),
        chosen_summary=summarize_codex_repair(codex_evidence_root, codex_commit),
        rejected_diff_path=case.git_diff_path,
        chosen_diff_path=chosen_diff,
        quality_delta=None,
        same_task_identity=same_identity,
        eligible_for_sft=eligible_sft,
        eligible_for_dpo=eligible_dpo,
        eligible_for_skill_update=eligible_skill,
        approved_for_training=False,
    )
    comparison_path = case_dir / "codex_repair_comparison.json"
    comparison_path.write_text(
        json.dumps(dataclass_to_dict(comparison), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    skill_target = skill_name_for_failure_modes(case.failure_modes)
    candidate_type = "mixed" if sum([eligible_sft, eligible_dpo, eligible_skill]) > 1 else (
        "dpo" if eligible_dpo else "sft" if eligible_sft else "skill_update"
    )
    dpo_candidate: dict[str, Any] = {
        "case_id": case_id,
        "source": "agent_action_capture",
        "target_slot": case.target_slot,
        "target_agent": "Repairman/Logi",
        "candidate_type": candidate_type,
        "failure_modes": case.failure_modes,
        "rejected_artifact": case.git_diff_path or case.terminal_log_path or case.evidence_path,
        "chosen_artifact": chosen_diff or str(codex_evidence_root),
        "skill_target": skill_target,
        "eligible_for_sft": eligible_sft,
        "eligible_for_dpo": eligible_dpo,
        "eligible_for_skill_update": eligible_skill,
        "approved_for_training": False,
        "requires_human_approval": True,
        "comparison_path": str(comparison_path),
    }
    dpo_path = case_dir / "dpo_candidate.json"
    dpo_path.write_text(json.dumps(dpo_candidate, indent=2, ensure_ascii=False), encoding="utf-8")
    append_training_candidate(
        dpo_candidate,
        output_root=output,
        axi_ft_root=output.parent / "axi_ft_log",
    )
    if eligible_skill:
        create_or_update_skill_proposal(
            output_root=output,
            case_id=case_id,
            failure_modes=case.failure_modes,
            skill_name=skill_target,
        )
    return comparison, dpo_candidate
