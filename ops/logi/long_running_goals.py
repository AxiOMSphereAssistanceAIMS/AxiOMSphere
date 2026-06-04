"""Helpers for long-running self-regulation integrity goals."""
from __future__ import annotations

from datetime import datetime, timezone

from logi.process_goals import ProcessGoal, build_default_integrity_goal


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def build_long_running_goal(cycle_id: str, requested_by: str = "long_running_harness") -> ProcessGoal:
    """Build a bounded goal for one harness cycle."""
    goal = build_default_integrity_goal(requested_by=requested_by)
    goal.title = f"Long-Running Self-Regulation Cycle {cycle_id}"
    goal.max_iterations = 2
    goal.target_state = (
        "Maintain process integrity over repeated cycles with no active blockers, "
        "no slot32/slot120 conflict, consistent ledgers, and auditable closure evidence."
    )
    goal.artifacts.append(f"cycle_goal_tag:{_now_tag()}")
    return goal

