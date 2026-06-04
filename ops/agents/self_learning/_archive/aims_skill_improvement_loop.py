"""
AIMS Phase 17 — AIMS Skill Improvement Loop.

Tracks repeated improvement cycles for skill candidates.
No model calls, no activation, no registry modification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from .hermes_inspired_skill_curator_schema import (
        SKILL_STATE_OBSERVED,
        SKILL_STATE_CANDIDATE,
        CURATOR_DECISION_HOLD,
    )
except ImportError:
    from agents.self_learning.hermes_inspired_skill_curator_schema import (  # type: ignore
        SKILL_STATE_OBSERVED,
        SKILL_STATE_CANDIDATE,
        CURATOR_DECISION_HOLD,
    )

# Maximum improvement cycles before forcing human review
MAX_IMPROVEMENT_CYCLES = 3


@dataclass
class ImprovementCycle:
    cycle_number: int
    candidate_id: str
    prior_state: str
    prior_decision: str
    improvement_notes: str
    resolved_violations: list[str]
    remaining_violations: list[str]
    outcome: str  # "ADVANCED" | "HELD" | "REJECTED" | "CYCLE_LIMIT_REACHED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_number": self.cycle_number,
            "candidate_id": self.candidate_id,
            "prior_state": self.prior_state,
            "prior_decision": self.prior_decision,
            "improvement_notes": self.improvement_notes,
            "resolved_violations": self.resolved_violations,
            "remaining_violations": self.remaining_violations,
            "outcome": self.outcome,
        }


class SkillImprovementLoop:
    """
    Tracks improvement history for candidates that receive HOLD decisions.
    When MAX_IMPROVEMENT_CYCLES is reached, escalates to human review.
    """

    def __init__(self) -> None:
        self._history: dict[str, list[ImprovementCycle]] = {}

    def record_cycle(
        self,
        candidate_id: str,
        prior_state: str,
        prior_decision: str,
        improvement_notes: str,
        resolved_violations: list[str],
        remaining_violations: list[str],
    ) -> ImprovementCycle:
        if candidate_id not in self._history:
            self._history[candidate_id] = []

        cycle_number = len(self._history[candidate_id]) + 1

        if cycle_number > MAX_IMPROVEMENT_CYCLES:
            outcome = "CYCLE_LIMIT_REACHED"
        elif remaining_violations:
            outcome = "HELD"
        elif prior_decision == CURATOR_DECISION_HOLD and not remaining_violations:
            outcome = "ADVANCED"
        else:
            outcome = "HELD"

        cycle = ImprovementCycle(
            cycle_number=cycle_number,
            candidate_id=candidate_id,
            prior_state=prior_state,
            prior_decision=prior_decision,
            improvement_notes=improvement_notes,
            resolved_violations=resolved_violations,
            remaining_violations=remaining_violations,
            outcome=outcome,
        )
        self._history[candidate_id].append(cycle)
        return cycle

    def get_cycle_count(self, candidate_id: str) -> int:
        return len(self._history.get(candidate_id, []))

    def needs_human_escalation(self, candidate_id: str) -> bool:
        return self.get_cycle_count(candidate_id) >= MAX_IMPROVEMENT_CYCLES

    def get_history(self, candidate_id: str) -> list[ImprovementCycle]:
        return list(self._history.get(candidate_id, []))

    def get_all_history(self) -> dict[str, list[dict[str, Any]]]:
        return {
            cid: [c.to_dict() for c in cycles]
            for cid, cycles in self._history.items()
        }

    def build_improvement_summary(self) -> dict[str, Any]:
        total_cycles = sum(len(v) for v in self._history.values())
        escalated = [
            cid for cid in self._history
            if self.needs_human_escalation(cid)
        ]
        return {
            "candidates_tracked": len(self._history),
            "total_improvement_cycles": total_cycles,
            "candidates_escalated_to_human": len(escalated),
            "escalated_candidate_ids": escalated,
            "max_cycles_allowed": MAX_IMPROVEMENT_CYCLES,
        }
