from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, TypeVar


FAILURE_MODES: tuple[str, ...] = (
    "evidence_only_completion_without_feature_implementation",
    "tests_only_no_production_wiring",
    "mocked_path_claimed_as_production",
    "quality_score_without_gate_validation",
    "raw_output_certified_without_master_package",
    "missing_learning_entry",
    "missing_artifact_paths",
    "wrong_extractor_applied",
    "unsupported_counted_as_failed",
    "archive_member_not_processed",
    "no_commit_after_implementation",
    "no_regression_after_patch",
    "no_limited_production_run",
)


@dataclass
class AgentActionCase:
    case_id: str
    timestamp_utc: str
    project: str
    agent_name: str
    target_slot: str
    task_prompt: str
    expected_deliverables: list[str] = field(default_factory=list)
    actual_deliverables: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    terminal_log_path: str | None = None
    git_diff_path: str | None = None
    evidence_path: str = ""
    outcome: str = "UNKNOWN"
    failure_modes: list[str] = field(default_factory=list)
    approved_for_training: bool = False

    def __post_init__(self) -> None:
        self.approved_for_training = False
        self.failure_modes = [mode for mode in self.failure_modes if mode in FAILURE_MODES]


@dataclass
class CodexRepairComparison:
    case_id: str
    rejected_summary: str
    chosen_summary: str
    rejected_diff_path: str | None = None
    chosen_diff_path: str | None = None
    quality_delta: float | None = None
    same_task_identity: bool = False
    eligible_for_sft: bool = False
    eligible_for_dpo: bool = False
    eligible_for_skill_update: bool = False
    approved_for_training: bool = False

    def __post_init__(self) -> None:
        self.approved_for_training = False


T = TypeVar("T", AgentActionCase, CodexRepairComparison)


def dataclass_to_dict(obj: AgentActionCase | CodexRepairComparison) -> dict[str, Any]:
    data = asdict(obj)
    data["approved_for_training"] = False
    return data


def dataclass_from_dict(cls: type[T], data: dict[str, Any]) -> T:
    values = dict(data)
    values["approved_for_training"] = False
    return cls(**values)
