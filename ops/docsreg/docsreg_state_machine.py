"""
DOCSREG state machine — defines all run states and valid transition graph.
"""
from __future__ import annotations


class DocsregState:
    """String constants for all DOCSREG pipeline states."""

    # Happy-path pipeline states
    CREATED = "CREATED"
    INTAKE_READY = "INTAKE_READY"
    EXTRACTION_READY = "EXTRACTION_READY"
    FAMILY_MAP_READY = "FAMILY_MAP_READY"
    MASTER_DECISION_READY = "MASTER_DECISION_READY"
    STRUCTURE_REPAIR_READY = "STRUCTURE_REPAIR_READY"
    REFERENCE_GOVERNANCE_READY = "REFERENCE_GOVERNANCE_READY"
    BEST_DRAFT_SYNC_READY = "BEST_DRAFT_SYNC_READY"
    TRACEABILITY_READY = "TRACEABILITY_READY"
    QUALITY_VALIDATED = "QUALITY_VALIDATED"
    REGISTRATION_PRECHECK_READY = "REGISTRATION_PRECHECK_READY"
    CERTIFIED_MASTER_READY = "CERTIFIED_MASTER_READY"
    MASTER_REGISTERED = "MASTER_REGISTERED"

    # Blocked / terminal states
    BLOCKED_REQUIRES_DECISION = "BLOCKED_REQUIRES_DECISION"
    BLOCKED_REQUIRES_RESOURCE = "BLOCKED_REQUIRES_RESOURCE"
    FAILED = "FAILED"


# Ordered list of happy-path states for reference
_HAPPY_PATH: list[str] = [
    DocsregState.CREATED,
    DocsregState.INTAKE_READY,
    DocsregState.EXTRACTION_READY,
    DocsregState.FAMILY_MAP_READY,
    DocsregState.MASTER_DECISION_READY,
    DocsregState.STRUCTURE_REPAIR_READY,
    DocsregState.REFERENCE_GOVERNANCE_READY,
    DocsregState.BEST_DRAFT_SYNC_READY,
    DocsregState.TRACEABILITY_READY,
    DocsregState.QUALITY_VALIDATED,
    DocsregState.REGISTRATION_PRECHECK_READY,
    DocsregState.CERTIFIED_MASTER_READY,
    DocsregState.MASTER_REGISTERED,
]

_BLOCKED_STATES: set[str] = {
    DocsregState.BLOCKED_REQUIRES_DECISION,
    DocsregState.BLOCKED_REQUIRES_RESOURCE,
}

_INTERRUPT_STATES: list[str] = [
    DocsregState.BLOCKED_REQUIRES_DECISION,
    DocsregState.BLOCKED_REQUIRES_RESOURCE,
    DocsregState.FAILED,
]


def _build_valid_transitions() -> dict[str, list[str]]:
    """
    Build the full transition graph.

    Rules:
    - Each happy-path state may advance to the next happy-path state.
    - Every non-terminal state may transition to any interrupt state
      (BLOCKED_REQUIRES_DECISION, BLOCKED_REQUIRES_RESOURCE, FAILED).
    - BLOCKED states may resume to any non-terminal, non-blocked pipeline
      state (the caller decides which state to re-enter after unblocking).
    - MASTER_REGISTERED and FAILED are terminal: no outgoing transitions.
    """
    transitions: dict[str, list[str]] = {}

    # Happy-path forward edges + interrupt edges
    for idx, state in enumerate(_HAPPY_PATH):
        if state == DocsregState.MASTER_REGISTERED:
            # Terminal — no outgoing transitions
            transitions[state] = []
            continue

        next_states: list[str] = []

        # Advance to next happy-path state (if not last)
        if idx + 1 < len(_HAPPY_PATH):
            next_states.append(_HAPPY_PATH[idx + 1])

        # Any non-terminal state can be interrupted
        next_states.extend(_INTERRUPT_STATES)

        transitions[state] = next_states

    # FAILED is terminal
    transitions[DocsregState.FAILED] = []

    # BLOCKED states: can resume to any non-terminal pipeline state,
    # switch to the other blocked state, or escalate to FAILED.
    resumable: list[str] = [
        s for s in _HAPPY_PATH if s != DocsregState.MASTER_REGISTERED
    ]
    for blocked in _BLOCKED_STATES:
        other_blocked = list(_BLOCKED_STATES - {blocked})
        transitions[blocked] = (
            list(resumable) + other_blocked + [DocsregState.FAILED]
        )

    return transitions


VALID_TRANSITIONS: dict[str, list[str]] = _build_valid_transitions()


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Return True if transitioning from *from_state* to *to_state* is allowed."""
    allowed = VALID_TRANSITIONS.get(from_state)
    if allowed is None:
        return False
    return to_state in allowed


def is_terminal(state: str) -> bool:
    """Return True when *state* has no valid outgoing transitions (run is finished)."""
    return state in {DocsregState.MASTER_REGISTERED, DocsregState.FAILED}


def is_blocked(state: str) -> bool:
    """Return True when *state* is a BLOCKED_* state requiring external action."""
    return state in _BLOCKED_STATES
