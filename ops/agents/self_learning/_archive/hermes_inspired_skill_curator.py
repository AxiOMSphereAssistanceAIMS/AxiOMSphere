"""
AIMS Phase 17 — Hermes-Inspired Skill Curator.

Evaluates observed patterns against Hermes reference categories,
applies AIMS authoring policy, and produces curator decisions.
No model calls, no Hermes runtime, no registry modification.
"""
from __future__ import annotations

import pathlib
import uuid
from typing import Any

try:
    from .hermes_inspired_skill_curator_schema import (
        SKILL_STATE_OBSERVED,
        SKILL_STATE_CANDIDATE,
        SKILL_STATE_SANDBOX,
        CURATOR_DECISION_PROMOTE,
        CURATOR_DECISION_SANDBOX,
        CURATOR_DECISION_HOLD,
        CURATOR_DECISION_REJECT,
        AIMSSkillCandidate,
        HermesSkillReference,
    )
    from .hermes_skill_reference_mapper import build_reference_index
    from .aims_agent_skill_authoring_policy import SkillAuthoringPolicyEnforcer
except ImportError:
    from agents.self_learning.hermes_inspired_skill_curator_schema import (  # type: ignore
        SKILL_STATE_OBSERVED,
        SKILL_STATE_CANDIDATE,
        SKILL_STATE_SANDBOX,
        CURATOR_DECISION_PROMOTE,
        CURATOR_DECISION_SANDBOX,
        CURATOR_DECISION_HOLD,
        CURATOR_DECISION_REJECT,
        AIMSSkillCandidate,
        HermesSkillReference,
    )
    from agents.self_learning.hermes_skill_reference_mapper import build_reference_index  # type: ignore
    from agents.self_learning.aims_agent_skill_authoring_policy import SkillAuthoringPolicyEnforcer  # type: ignore


class HermesInspiredSkillCurator:
    """
    AIMS-native curator using Hermes skill categories as reference patterns.
    Hermes runtime is never invoked — only the pattern taxonomy is referenced.
    """

    def __init__(self) -> None:
        self._policy = SkillAuthoringPolicyEnforcer()
        self._reference_index = build_reference_index()

    def _resolve_reference(self, candidate: dict[str, Any]) -> HermesSkillReference | None:
        """Match candidate to a Hermes reference category."""
        cat = candidate.get("hermes_reference_category")
        if cat:
            return self._reference_index.get(cat)
        # Attempt keyword match on name/description
        text = (
            (candidate.get("name") or "")
            + " "
            + (candidate.get("description") or "")
        ).lower()
        for cat_name, ref in self._reference_index.items():
            if cat_name.replace("-", " ") in text:
                return ref
        return None

    def _decide(
        self,
        candidate: dict[str, Any],
        violations: list[str],
        ref: HermesSkillReference | None,
    ) -> tuple[str, str]:
        """Return (curator_decision, rationale)."""
        if violations:
            return (
                CURATOR_DECISION_REJECT,
                f"Authoring policy violations detected: {'; '.join(violations)}",
            )

        state = candidate.get("state", SKILL_STATE_OBSERVED)

        if state == SKILL_STATE_OBSERVED:
            if ref:
                return (
                    CURATOR_DECISION_PROMOTE,
                    f"Pattern matches Hermes reference '{ref.hermes_category}' "
                    f"({ref.hermes_pattern_name}). Promoting to CANDIDATE_SKILL for review.",
                )
            return (
                CURATOR_DECISION_HOLD,
                "No matching Hermes reference found. Holding for human categorization.",
            )

        if state == SKILL_STATE_CANDIDATE:
            if ref and ref.applicable_aims_phases:
                return (
                    CURATOR_DECISION_SANDBOX,
                    f"Candidate validated against '{ref.hermes_category}' pattern. "
                    "Promoting to SANDBOX_SKILL for isolated testing.",
                )
            return (
                CURATOR_DECISION_HOLD,
                "Candidate lacks applicable phase mapping. Holding for review.",
            )

        # SANDBOX_SKILL or later → hold; certification is Phase 10's responsibility
        return (
            CURATOR_DECISION_HOLD,
            f"State {state!r} is beyond curator scope. "
            "Certification handled by Phase 10 workflow.",
        )

    def evaluate(self, observed_candidates: list[dict[str, Any]]) -> list[AIMSSkillCandidate]:
        """Evaluate a batch of observed skill candidates."""
        results: list[AIMSSkillCandidate] = []

        for raw in observed_candidates:
            violations = self._policy.check(raw)
            ref = self._resolve_reference(raw)
            decision, rationale = self._decide(raw, violations, ref)

            # Advance state if promoted
            state = raw.get("state", SKILL_STATE_OBSERVED)
            if decision == CURATOR_DECISION_PROMOTE and state == SKILL_STATE_OBSERVED:
                state = SKILL_STATE_CANDIDATE
            elif decision == CURATOR_DECISION_SANDBOX and state == SKILL_STATE_CANDIDATE:
                state = SKILL_STATE_SANDBOX

            candidate = AIMSSkillCandidate(
                candidate_id=raw.get("candidate_id") or f"curator-{uuid.uuid4().hex[:8]}",
                name=raw.get("name", ""),
                description=raw.get("description", ""),
                hermes_reference_category=ref.hermes_category if ref else None,
                state=state,
                authoring_policy_violations=violations,
                curator_decision=decision,
                curator_rationale=rationale,
                metadata=raw.get("metadata", {}),
            )
            results.append(candidate)

        return results

    def summarize_decisions(self, candidates: list[AIMSSkillCandidate]) -> dict[str, int]:
        summary: dict[str, int] = {
            CURATOR_DECISION_PROMOTE: 0,
            CURATOR_DECISION_SANDBOX: 0,
            CURATOR_DECISION_HOLD: 0,
            CURATOR_DECISION_REJECT: 0,
        }
        for c in candidates:
            if c.curator_decision in summary:
                summary[c.curator_decision] += 1
        return summary
