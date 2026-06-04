"""
AIMS Self-Learning — Skill Candidate Validator.

Validates ObservedPattern dicts before promotion and
CandidateSkill dicts after generation. No model calls, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from .observed_pattern_schema import RISK_FLAGS, HIGH_RISK_FLAGS
from .skill_candidate_schema import (
    CANDIDATE_STATUS_REJECTED,
    CANDIDATE_STATUS_REVIEW,
    CANDIDATE_STATUS_READY,
)
from .agent_skill_ownership import AIMS_AGENTS
from .promotion_gates import GATE_ARGUS, GATE_LOGI, GATE_QA, GATE_TRAINI

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)


class PatternValidator:
    """Validates raw ObservedPattern dicts from fixture files."""

    def __init__(self) -> None:
        self._errors: list[str] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def is_valid(self) -> bool:
        return len(self._errors) == 0

    def validate(self, d: dict[str, Any]) -> bool:
        self._errors.clear()

        pid = d.get("pattern_id", "")
        if not pid:
            self._errors.append("pattern_id is missing or empty")

        agent = d.get("source_agent_id", "")
        if agent not in AIMS_AGENTS:
            self._errors.append(f"source_agent_id {agent!r} not in known agents")

        count = d.get("observed_count", 0)
        if not isinstance(count, int) or count < 2:
            self._errors.append(
                f"observed_count must be int ≥ 2, got {count!r}"
            )

        conf = d.get("confidence", -1)
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            self._errors.append(f"confidence must be float in [0.0,1.0], got {conf!r}")

        desc = d.get("description", "")
        if len(desc) > 512:
            self._errors.append("description exceeds 512 characters")
        if _SECRET_RE.search(desc):
            self._errors.append("description contains secret-like value")

        risk = d.get("risk_flags", {})
        unknown = set(risk.keys()) - set(RISK_FLAGS)
        if unknown:
            self._errors.append(f"Unknown risk_flags: {unknown}")

        refs = d.get("evidence_refs", [])
        if not isinstance(refs, list) or len(refs) == 0:
            self._errors.append("evidence_refs must be a non-empty list")

        return self.is_valid()


class CandidateValidator:
    """Validates generated CandidateSkill dicts."""

    def __init__(self) -> None:
        self._errors: list[str] = []
        self._warnings: list[str] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def is_valid(self) -> bool:
        return len(self._errors) == 0

    def validate(self, d: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        if d.get("lifecycle_state") != "CANDIDATE_SKILL":
            self._errors.append(
                f"lifecycle_state must be CANDIDATE_SKILL, "
                f"got {d.get('lifecycle_state')!r}"
            )

        status = d.get("candidate_status", "")
        if status not in (
            CANDIDATE_STATUS_READY, CANDIDATE_STATUS_REVIEW, CANDIDATE_STATUS_REJECTED
        ):
            self._errors.append(f"candidate_status {status!r} is not a valid status")

        gates = d.get("required_gates", [])
        for always_gate in (GATE_ARGUS, GATE_LOGI, GATE_QA):
            if always_gate not in gates:
                self._errors.append(f"{always_gate} missing from required_gates")

        risk = d.get("risk_flags", {})
        if risk.get("model_related") and GATE_TRAINI not in gates:
            self._errors.append(
                f"model_related=True but {GATE_TRAINI} not in required_gates"
            )

        if status == CANDIDATE_STATUS_REJECTED:
            if not d.get("rejection_reason"):
                self._errors.append(
                    "REJECTED_UNSAFE candidate must have non-empty rejection_reason"
                )
            # Rejected candidates must not appear as READY
        elif status == CANDIDATE_STATUS_READY:
            high_risk = any(
                risk.get(f, False) for f in HIGH_RISK_FLAGS
            )
            if high_risk:
                self._warnings.append(
                    "READY_FOR_SANDBOX candidate has high-risk flags set — "
                    "review recommended before sandbox promotion"
                )

        # No secrets anywhere
        if _SECRET_RE.search(str(d)):
            self._errors.append("CandidateSkill dict contains secret-like values")

        return self.is_valid()
