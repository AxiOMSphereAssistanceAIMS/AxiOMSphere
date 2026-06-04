"""
AIMS Self-Learning — Skill Lifecycle State Machine.

Defines the ordered lifecycle states for AIMS agent skills and
the allowed transition graph. No model calls, no runtime changes.
"""
from __future__ import annotations

from typing import FrozenSet

# Ordered lifecycle states — index encodes progression direction
LIFECYCLE_STATES: tuple[str, ...] = (
    "OBSERVED_PATTERN",
    "CANDIDATE_SKILL",
    "SANDBOX_SKILL",
    "CERTIFIED_SKILL",
    "ACTIVE_RUNTIME_SKILL",
    "DEPRECATED_SKILL",
)

# Allowed forward transitions (source -> set of legal targets)
LIFECYCLE_TRANSITIONS: dict[str, FrozenSet[str]] = {
    "OBSERVED_PATTERN":     frozenset({"CANDIDATE_SKILL"}),
    "CANDIDATE_SKILL":      frozenset({"SANDBOX_SKILL", "OBSERVED_PATTERN"}),
    "SANDBOX_SKILL":        frozenset({"CERTIFIED_SKILL", "CANDIDATE_SKILL"}),
    "CERTIFIED_SKILL":      frozenset({"ACTIVE_RUNTIME_SKILL", "SANDBOX_SKILL"}),
    "ACTIVE_RUNTIME_SKILL": frozenset({"DEPRECATED_SKILL", "CERTIFIED_SKILL"}),
    "DEPRECATED_SKILL":     frozenset(),  # terminal state — no further transitions
}


class SkillLifecycle:
    """Validates and records skill lifecycle transitions."""

    def __init__(self, current_state: str) -> None:
        if current_state not in LIFECYCLE_STATES:
            raise ValueError(
                f"Unknown lifecycle state: {current_state!r}. "
                f"Valid states: {LIFECYCLE_STATES}"
            )
        self._state = current_state

    @property
    def state(self) -> str:
        return self._state

    @property
    def state_index(self) -> int:
        return LIFECYCLE_STATES.index(self._state)

    def can_transition_to(self, target: str) -> bool:
        return target in LIFECYCLE_TRANSITIONS.get(self._state, frozenset())

    def transition_to(self, target: str) -> "SkillLifecycle":
        if not self.can_transition_to(target):
            allowed = sorted(LIFECYCLE_TRANSITIONS.get(self._state, frozenset()))
            raise ValueError(
                f"Illegal transition {self._state!r} -> {target!r}. "
                f"Allowed targets: {allowed}"
            )
        return SkillLifecycle(target)

    def is_terminal(self) -> bool:
        return len(LIFECYCLE_TRANSITIONS.get(self._state, frozenset())) == 0

    def __repr__(self) -> str:
        return f"SkillLifecycle(state={self._state!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SkillLifecycle):
            return self._state == other._state
        return NotImplemented
