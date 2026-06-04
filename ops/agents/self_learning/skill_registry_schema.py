"""
AIMS Self-Learning — Skill Registry Entry Schema.

Pure data classes — no I/O, no model calls, no runtime side effects.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from .skill_lifecycle import LIFECYCLE_STATES


@dataclass
class SkillRegistryEntry:
    """A single skill tracked by the AIMS self-learning registry."""

    skill_id: str                  # unique slug, kebab-case
    owner_agent_id: str            # which AIMS agent owns this skill
    lifecycle_state: str           # one of LIFECYCLE_STATES
    source_hermes_category: str    # hermes sandbox category the skill maps to
    source_hermes_name: str        # hermes SKILL.md name (empty for category-root)
    description: str               # one-line human description ≤256 chars
    observed_count: int = 0        # times the underlying pattern was observed
    confidence: float = 0.0        # 0.0–1.0 subjective confidence
    risk_flags: dict[str, bool] = field(default_factory=dict)
    required_gates: list[str] = field(default_factory=list)
    gate_statuses: dict[str, str] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lifecycle_state not in LIFECYCLE_STATES:
            raise ValueError(
                f"Invalid lifecycle_state {self.lifecycle_state!r} "
                f"for skill {self.skill_id!r}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if len(self.description) > 256:
            raise ValueError("description must be ≤256 characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "owner_agent_id": self.owner_agent_id,
            "lifecycle_state": self.lifecycle_state,
            "source_hermes_category": self.source_hermes_category,
            "source_hermes_name": self.source_hermes_name,
            "description": self.description,
            "observed_count": self.observed_count,
            "confidence": self.confidence,
            "risk_flags": self.risk_flags,
            "required_gates": self.required_gates,
            "gate_statuses": self.gate_statuses,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillRegistryEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SkillRegistrySnapshot:
    """Full registry snapshot for serialisation and smoke-test checks."""

    schema_version: str
    created_at: str
    total_entries: int
    agents: list[str]                # all agent_ids present in the registry
    entries: list[SkillRegistryEntry]
    safety_invariants: dict[str, bool]
    next_allowed_phase: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "total_entries": self.total_entries,
            "agents": self.agents,
            "entries": [e.to_dict() for e in self.entries],
            "safety_invariants": self.safety_invariants,
            "next_allowed_phase": self.next_allowed_phase,
        }
