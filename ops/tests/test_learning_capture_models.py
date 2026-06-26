from __future__ import annotations

from ops.learning_capture.models import (
    AgentActionCase,
    CodexRepairComparison,
    dataclass_from_dict,
    dataclass_to_dict,
)


def test_training_flags_are_forced_false() -> None:
    case = AgentActionCase(
        case_id="c1",
        timestamp_utc="2026-06-26T00:00:00Z",
        project="aims",
        agent_name="slot32-local",
        target_slot="slot32",
        task_prompt="do work",
        approved_for_training=True,
    )
    comparison = CodexRepairComparison(
        case_id="c1",
        rejected_summary="bad",
        chosen_summary="good",
        approved_for_training=True,
    )
    assert case.approved_for_training is False
    assert comparison.approved_for_training is False
    assert dataclass_to_dict(case)["approved_for_training"] is False
    restored = dataclass_from_dict(AgentActionCase, dataclass_to_dict(case))
    assert restored.approved_for_training is False
