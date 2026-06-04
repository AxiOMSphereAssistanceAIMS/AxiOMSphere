"""
AIMS Self-Learning — CandidateSkill Schema.

A CandidateSkill is an ObservedPattern that has passed initial screening
and been promoted to CANDIDATE_SKILL lifecycle state.
No model calls, no I/O, no runtime changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .skill_lifecycle import LIFECYCLE_STATES
from .promotion_gates import (
    GATE_ARGUS, GATE_LOGI, GATE_QA, GATE_TRAINI,
    GATE_PENDING,
)

# Candidate disposition statuses
CANDIDATE_STATUS_READY = "READY_FOR_SANDBOX"
CANDIDATE_STATUS_REVIEW = "NEEDS_MANUAL_REVIEW"
CANDIDATE_STATUS_REJECTED = "REJECTED_UNSAFE"

CANDIDATE_STATUSES = (
    CANDIDATE_STATUS_READY,
    CANDIDATE_STATUS_REVIEW,
    CANDIDATE_STATUS_REJECTED,
)

# Gates always required (regardless of risk flags)
_ALWAYS_REQUIRED_GATES = (GATE_ARGUS, GATE_LOGI, GATE_QA)


@dataclass
class CandidateSkill:
    """
    A promoted skill candidate ready for gate evaluation.

    lifecycle_state is always CANDIDATE_SKILL.
    required_gates always includes argus, logi, qa; traini added if model_related.
    """

    skill_id: str
    source_pattern_id: str          # pattern_id this was promoted from
    owner_agent_id: str
    description: str                # ≤256 chars
    confidence: float               # 0.0–1.0
    risk_flags: dict[str, bool]
    candidate_status: str           # one of CANDIDATE_STATUSES
    required_gates: list[str]       # gate_ids that must approve
    gate_statuses: dict[str, str]   # gate_id -> PENDING/APPROVED/REJECTED
    rejection_reason: str = ""      # non-empty only when REJECTED_UNSAFE
    metadata: dict[str, Any] = field(default_factory=dict)

    # Fixed by spec
    lifecycle_state: str = field(default="CANDIDATE_SKILL", init=False)

    def __post_init__(self) -> None:
        if self.lifecycle_state != "CANDIDATE_SKILL":
            raise ValueError("CandidateSkill.lifecycle_state must be CANDIDATE_SKILL")
        if self.candidate_status not in CANDIDATE_STATUSES:
            raise ValueError(
                f"candidate_status {self.candidate_status!r} not in {CANDIDATE_STATUSES}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0]")
        if len(self.description) > 256:
            raise ValueError("description must be ≤256 characters")

        # Enforce gate list completeness
        for g in _ALWAYS_REQUIRED_GATES:
            if g not in self.required_gates:
                raise ValueError(
                    f"required_gates must include {g!r} (always required)"
                )
        if self.risk_flags.get("model_related") and GATE_TRAINI not in self.required_gates:
            raise ValueError(
                f"model_related=True requires {GATE_TRAINI!r} in required_gates"
            )

    @classmethod
    def from_pattern(
        cls,
        pattern_dict: dict[str, Any],
        skill_id: str,
        owner_agent_id: str,
        candidate_status: str,
        rejection_reason: str = "",
    ) -> "CandidateSkill":
        risk_flags: dict[str, bool] = pattern_dict.get("risk_flags", {})
        gates = list(_ALWAYS_REQUIRED_GATES)
        if risk_flags.get("model_related"):
            gates.append(GATE_TRAINI)

        return cls(
            skill_id=skill_id,
            source_pattern_id=pattern_dict["pattern_id"],
            owner_agent_id=owner_agent_id,
            description=pattern_dict.get("description", "")[:256],
            confidence=pattern_dict.get("confidence", 0.5),
            risk_flags=risk_flags,
            candidate_status=candidate_status,
            required_gates=gates,
            gate_statuses={g: GATE_PENDING for g in gates},
            rejection_reason=rejection_reason,
            metadata=pattern_dict.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "lifecycle_state": self.lifecycle_state,
            "source_pattern_id": self.source_pattern_id,
            "owner_agent_id": self.owner_agent_id,
            "description": self.description,
            "confidence": self.confidence,
            "risk_flags": self.risk_flags,
            "candidate_status": self.candidate_status,
            "required_gates": self.required_gates,
            "gate_statuses": self.gate_statuses,
            "rejection_reason": self.rejection_reason,
            "metadata": self.metadata,
        }
