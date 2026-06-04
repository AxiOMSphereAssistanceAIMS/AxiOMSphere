"""
AIMS Self-Learning — Skill Candidate Generator.

Converts validated ObservedPattern dicts into CandidateSkill dicts.
Applies safety screening: high-risk patterns → NEEDS_MANUAL_REVIEW;
secrets/deletion/restart flags → REJECTED_UNSAFE.
No model calls, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from .observed_pattern_schema import HIGH_RISK_FLAGS, RISK_FLAGS
from .skill_candidate_schema import (
    CandidateSkill,
    CANDIDATE_STATUS_READY,
    CANDIDATE_STATUS_REVIEW,
    CANDIDATE_STATUS_REJECTED,
)
from .agent_skill_ownership import resolve_owner, AIMS_AGENTS

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)

# Flags that must cause automatic REJECTED_UNSAFE regardless of everything else
_AUTO_REJECT_FLAGS = frozenset({
    "secrets_related",
    "deletion_or_quarantine_related",
    "service_restart_related",
})


def _derive_skill_id(pattern: dict[str, Any]) -> str:
    """Derive a kebab-case skill_id from pattern_id."""
    base = pattern.get("pattern_id", "unknown-pattern")
    slug = re.sub(r"[^a-z0-9\-]", "-", base.lower()).strip("-")
    return f"cand-{slug}"[:63]


def _derive_owner(pattern: dict[str, Any]) -> str:
    category = pattern.get("metadata", {}).get("hermes_category", "")
    skill_name = pattern.get("metadata", {}).get("hermes_skill_name", "")
    owner = resolve_owner(category, skill_name)
    if owner:
        return owner
    # Fall back to source_agent_id if ownership not mappable
    agent = pattern.get("source_agent_id", "")
    return agent if agent in AIMS_AGENTS else "hermes_external_worker"


def generate_candidate(pattern: dict[str, Any]) -> CandidateSkill:
    """
    Convert one ObservedPattern dict into a CandidateSkill.

    Disposition rules (applied in order):
    1. secrets-like value found in description → REJECTED_UNSAFE
    2. Any auto-reject risk flag True → REJECTED_UNSAFE
    3. Any other high-risk flag True → NEEDS_MANUAL_REVIEW
    4. confidence < 0.5 → NEEDS_MANUAL_REVIEW
    5. Otherwise → READY_FOR_SANDBOX
    """
    risk: dict[str, bool] = pattern.get("risk_flags", {})
    desc = pattern.get("description", "")

    # Rule 1 — secret in description text
    if _SECRET_RE.search(desc):
        return CandidateSkill.from_pattern(
            pattern,
            skill_id=_derive_skill_id(pattern),
            owner_agent_id=_derive_owner(pattern),
            candidate_status=CANDIDATE_STATUS_REJECTED,
            rejection_reason="description contains secret-like values",
        )

    # Rule 2 — auto-reject flags
    triggered_reject = [f for f in _AUTO_REJECT_FLAGS if risk.get(f, False)]
    if triggered_reject:
        return CandidateSkill.from_pattern(
            pattern,
            skill_id=_derive_skill_id(pattern),
            owner_agent_id=_derive_owner(pattern),
            candidate_status=CANDIDATE_STATUS_REJECTED,
            rejection_reason=f"auto-reject risk flags set: {triggered_reject}",
        )

    # Rule 3 — other high-risk flag (production_related doesn't auto-reject
    #           but requires manual review)
    other_high_risk = [
        f for f in HIGH_RISK_FLAGS
        if f not in _AUTO_REJECT_FLAGS and risk.get(f, False)
    ]
    # production_related also sends to review
    if risk.get("production_related"):
        other_high_risk.append("production_related")

    if other_high_risk:
        return CandidateSkill.from_pattern(
            pattern,
            skill_id=_derive_skill_id(pattern),
            owner_agent_id=_derive_owner(pattern),
            candidate_status=CANDIDATE_STATUS_REVIEW,
        )

    # Rule 4 — low confidence
    if pattern.get("confidence", 1.0) < 0.5:
        return CandidateSkill.from_pattern(
            pattern,
            skill_id=_derive_skill_id(pattern),
            owner_agent_id=_derive_owner(pattern),
            candidate_status=CANDIDATE_STATUS_REVIEW,
        )

    # Rule 5 — safe to promote
    return CandidateSkill.from_pattern(
        pattern,
        skill_id=_derive_skill_id(pattern),
        owner_agent_id=_derive_owner(pattern),
        candidate_status=CANDIDATE_STATUS_READY,
    )


def generate_candidates(patterns: list[dict[str, Any]]) -> list[CandidateSkill]:
    """Process a list of ObservedPattern dicts into CandidateSkill objects."""
    return [generate_candidate(p) for p in patterns]
