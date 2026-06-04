"""
AIMS Self-Learning — ObservedPattern Schema.

Represents a repeatedly-observed agent behaviour pattern that may
become a candidate skill. No model calls, no I/O, no runtime changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)

# Risk flag names (canonical)
RISK_FLAGS = (
    "secrets_related",
    "deletion_or_quarantine_related",
    "service_restart_related",
    "production_related",
    "model_related",
)

# A pattern with any of these flags set True is considered high-risk
HIGH_RISK_FLAGS = frozenset({
    "secrets_related",
    "deletion_or_quarantine_related",
    "service_restart_related",
})


@dataclass
class ObservedPattern:
    """A pattern observed ≥2 times by an AIMS agent."""

    pattern_id: str              # kebab-case unique slug
    source_agent_id: str         # which agent produced this observation
    observed_count: int          # must be ≥ 2 to qualify
    evidence_refs: list[str]     # list of log/session references
    description: str             # ≤512 chars, no credentials
    confidence: float            # 0.0–1.0
    risk_flags: dict[str, bool]  # keyed by RISK_FLAGS values
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observed_count < 2:
            raise ValueError(
                f"observed_count must be ≥ 2, got {self.observed_count} "
                f"for pattern {self.pattern_id!r}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if len(self.description) > 512:
            raise ValueError("description must be ≤512 characters")
        unknown_flags = set(self.risk_flags) - set(RISK_FLAGS)
        if unknown_flags:
            raise ValueError(f"Unknown risk_flags: {unknown_flags}")
        if _SECRET_RE.search(self.description):
            raise ValueError(
                "ObservedPattern description contains secret-like value"
            )

    def is_high_risk(self) -> bool:
        return any(self.risk_flags.get(f, False) for f in HIGH_RISK_FLAGS)

    def is_model_related(self) -> bool:
        return bool(self.risk_flags.get("model_related", False))

    def is_production_related(self) -> bool:
        return bool(self.risk_flags.get("production_related", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "source_agent_id": self.source_agent_id,
            "observed_count": self.observed_count,
            "evidence_refs": self.evidence_refs,
            "description": self.description,
            "confidence": self.confidence,
            "risk_flags": self.risk_flags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ObservedPattern":
        return cls(
            pattern_id=d["pattern_id"],
            source_agent_id=d["source_agent_id"],
            observed_count=d["observed_count"],
            evidence_refs=d.get("evidence_refs", []),
            description=d["description"],
            confidence=d.get("confidence", 0.5),
            risk_flags=d.get("risk_flags", {f: False for f in RISK_FLAGS}),
            metadata=d.get("metadata", {}),
        )
