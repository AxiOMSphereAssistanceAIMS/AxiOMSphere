"""
AIMS Phase 17 — Hermes-Inspired Skill Curator Schema.

Data structures for the AIMS-native skill curation pipeline.
Hermes is reference implementation only — not project governor.
No model calls, no activation, no registry modification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "17.0"
PHASE = 17

# Skill lifecycle states (AIMS-native, not Hermes states)
SKILL_STATE_OBSERVED = "OBSERVED_PATTERN"
SKILL_STATE_CANDIDATE = "CANDIDATE_SKILL"
SKILL_STATE_SANDBOX = "SANDBOX_SKILL"
SKILL_STATE_CERTIFIED = "CERTIFIED_SKILL"
SKILL_STATE_ACTIVE = "ACTIVE_RUNTIME_SKILL"       # requires human approval
SKILL_STATE_DEPRECATED = "DEPRECATED_SKILL"

# Curator decision codes
CURATOR_DECISION_PROMOTE = "PROMOTE_TO_CANDIDATE"
CURATOR_DECISION_SANDBOX = "PROMOTE_TO_SANDBOX"
CURATOR_DECISION_HOLD = "HOLD_FOR_REVIEW"
CURATOR_DECISION_REJECT = "REJECT"

# Hermes skill categories referenced as patterns (read-only reference)
HERMES_REFERENCE_CATEGORIES = (
    "skill-authoring",
    "dogfood",
    "systematic-debugging",
    "codebase-inspection",
    "requesting-code-review",
    "test-driven-development",
    "plan",
    "writing-plans",
    "subagent-driven-development",
    "ocr-and-documents",
)

# AIMS-native adaptation policies
AIMS_AUTHORING_POLICIES = (
    "no_self_approval",
    "no_active_registry_modification",
    "no_hermes_runtime_invocation",
    "no_model_endpoint_calls",
    "no_live_omniroute_calls",
    "no_training_launch",
    "no_model_promotion",
    "no_slot120_loading",
    "no_slot32_unloading",
    "no_service_restart",
    "sandbox_required_before_certification",
    "human_review_required_before_activation",
)

# Curator status codes
CURATOR_STATUS_READY = "HERMES_INSPIRED_CURATOR_SKELETON_READY"
CURATOR_STATUS_BLOCKED = "HERMES_INSPIRED_CURATOR_BLOCKED"


@dataclass
class HermesSkillReference:
    """
    Read-only reference to a Hermes skill pattern.
    Used for inspiration only — Hermes runtime is never invoked.
    """
    hermes_category: str
    hermes_pattern_name: str
    aims_adaptation_notes: str
    applicable_aims_phases: list[int]
    safety_constraints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hermes_category": self.hermes_category,
            "hermes_pattern_name": self.hermes_pattern_name,
            "aims_adaptation_notes": self.aims_adaptation_notes,
            "applicable_aims_phases": self.applicable_aims_phases,
            "safety_constraints": self.safety_constraints,
        }


@dataclass
class AIMSSkillCandidate:
    """An AIMS-native skill candidate derived from observed patterns."""
    candidate_id: str
    name: str
    description: str
    hermes_reference_category: str | None
    state: str
    authoring_policy_violations: list[str]
    curator_decision: str
    curator_rationale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid_states = {
            SKILL_STATE_OBSERVED, SKILL_STATE_CANDIDATE,
            SKILL_STATE_SANDBOX, SKILL_STATE_CERTIFIED,
            SKILL_STATE_ACTIVE, SKILL_STATE_DEPRECATED,
        }
        if self.state not in valid_states:
            raise ValueError(f"Invalid skill state: {self.state!r}")
        if self.state == SKILL_STATE_ACTIVE:
            raise ValueError(
                "ACTIVE_RUNTIME_SKILL cannot be set in Phase 17 — requires human approval"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "description": self.description,
            "hermes_reference_category": self.hermes_reference_category,
            "state": self.state,
            "authoring_policy_violations": self.authoring_policy_violations,
            "curator_decision": self.curator_decision,
            "curator_rationale": self.curator_rationale,
            "metadata": self.metadata,
        }


@dataclass
class SkillCurationReport:
    """Full Phase 17 curation report."""
    phase: int
    schema_version: str
    created_at: str
    curator_status: str
    hermes_references_loaded: int
    candidates_evaluated: int
    decisions: dict[str, int]
    authoring_policy_violations_found: int
    active_registry_modified: bool
    hermes_runtime_invoked: bool
    model_endpoints_called: bool
    training_launched: bool
    candidates: list[dict[str, Any]]
    hermes_references: list[dict[str, Any]]
    policy_summary: dict[str, bool]
    unresolved_blockers: list[str]
    validation_passed: bool = False
    validation_errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.active_registry_modified:
            raise ValueError("active_registry_modified must be False in Phase 17")
        if self.hermes_runtime_invoked:
            raise ValueError("hermes_runtime_invoked must be False in Phase 17")
        if self.model_endpoints_called:
            raise ValueError("model_endpoints_called must be False in Phase 17")
        if self.training_launched:
            raise ValueError("training_launched must be False in Phase 17")

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "curator_status": self.curator_status,
            "hermes_references_loaded": self.hermes_references_loaded,
            "candidates_evaluated": self.candidates_evaluated,
            "decisions": self.decisions,
            "authoring_policy_violations_found": self.authoring_policy_violations_found,
            "active_registry_modified": self.active_registry_modified,
            "hermes_runtime_invoked": self.hermes_runtime_invoked,
            "model_endpoints_called": self.model_endpoints_called,
            "training_launched": self.training_launched,
            "candidates": self.candidates,
            "hermes_references": self.hermes_references,
            "policy_summary": self.policy_summary,
            "unresolved_blockers": self.unresolved_blockers,
            "validation_passed": self.validation_passed,
            "validation_errors": self.validation_errors,
        }
