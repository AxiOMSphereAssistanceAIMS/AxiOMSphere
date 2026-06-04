"""
AIMS Self-Learning — SandboxSkillPlan Schema.

A SandboxSkillPlan converts an approved CandidateSkill into a
dry-run execution plan with explicit forbidden-action lists and
sandbox constraint policies. No model calls, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Lifecycle transition encoded in every plan
PLAN_LIFECYCLE_TRANSITION = "CANDIDATE_SKILL -> SANDBOX_SKILL"

# Forbidden actions that must appear in every plan (safety invariants)
MANDATORY_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "delete_files",
    "quarantine_models",
    "restart_services",
    "write_secrets",
    "modify_production_db",
    "call_model_endpoints",
    "enable_runtime_activation",
    "grant_production_access",
    "modify_env_files",
    "run_training_jobs",
)

# Policy key names
_POLICY_FILESYSTEM = "filesystem_policy"
_POLICY_MODEL = "model_policy"
_POLICY_PRODUCTION = "production_policy"
_POLICY_SECRETS = "secrets_policy"

# Policy allowed values
POLICY_READONLY = "READ_ONLY"
POLICY_NO_ACCESS = "NO_ACCESS"
POLICY_DRY_RUN_ONLY = "DRY_RUN_ONLY"
POLICY_DISALLOWED = "DISALLOWED"


@dataclass
class SandboxSkillPlan:
    """
    Execution plan for running a CandidateSkill in the sandbox.

    lifecycle_transition is always "CANDIDATE_SKILL -> SANDBOX_SKILL".
    forbidden_actions must include all MANDATORY_FORBIDDEN_ACTIONS.
    dry_run is always True at plan creation time.
    """

    plan_id: str                        # kebab-case slug
    skill_id: str                       # CandidateSkill.skill_id
    source_pattern_id: str
    owner_agent_id: str
    description: str                    # ≤256 chars
    lifecycle_transition: str           # must == PLAN_LIFECYCLE_TRANSITION
    forbidden_actions: list[str]        # must ⊇ MANDATORY_FORBIDDEN_ACTIONS
    sandbox_policies: dict[str, str]    # policy_key -> policy_value
    dry_run: bool                       # always True at plan time
    evidence_required: list[str]        # what evidence the sandbox run must produce
    risk_flags: dict[str, bool]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lifecycle_transition != PLAN_LIFECYCLE_TRANSITION:
            raise ValueError(
                f"lifecycle_transition must be {PLAN_LIFECYCLE_TRANSITION!r}, "
                f"got {self.lifecycle_transition!r}"
            )
        if not self.dry_run:
            raise ValueError("SandboxSkillPlan.dry_run must be True")
        missing = [
            a for a in MANDATORY_FORBIDDEN_ACTIONS
            if a not in self.forbidden_actions
        ]
        if missing:
            raise ValueError(
                f"forbidden_actions missing mandatory entries: {missing}"
            )
        required_policies = (
            _POLICY_FILESYSTEM, _POLICY_MODEL, _POLICY_PRODUCTION, _POLICY_SECRETS
        )
        missing_policies = [p for p in required_policies if p not in self.sandbox_policies]
        if missing_policies:
            raise ValueError(f"sandbox_policies missing keys: {missing_policies}")

    @classmethod
    def from_candidate(cls, candidate: dict[str, Any]) -> "SandboxSkillPlan":
        skill_id = candidate["skill_id"]
        risk = candidate.get("risk_flags", {})

        # Policy escalation based on risk flags
        model_policy = POLICY_DRY_RUN_ONLY if risk.get("model_related") else POLICY_NO_ACCESS
        prod_policy = POLICY_DRY_RUN_ONLY if risk.get("production_related") else POLICY_NO_ACCESS

        evidence = ["dry_run_log", "assertion_results", "no_forbidden_action_triggered"]
        if risk.get("model_related"):
            evidence.append("model_not_loaded")
        if risk.get("production_related"):
            evidence.append("production_not_modified")

        return cls(
            plan_id=f"plan-{skill_id}"[:63],
            skill_id=skill_id,
            source_pattern_id=candidate.get("source_pattern_id", ""),
            owner_agent_id=candidate.get("owner_agent_id", ""),
            description=candidate.get("description", "")[:256],
            lifecycle_transition=PLAN_LIFECYCLE_TRANSITION,
            forbidden_actions=list(MANDATORY_FORBIDDEN_ACTIONS),
            sandbox_policies={
                _POLICY_FILESYSTEM: POLICY_READONLY,
                _POLICY_MODEL: model_policy,
                _POLICY_PRODUCTION: prod_policy,
                _POLICY_SECRETS: POLICY_DISALLOWED,
            },
            dry_run=True,
            evidence_required=evidence,
            risk_flags=risk,
            metadata=candidate.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "skill_id": self.skill_id,
            "source_pattern_id": self.source_pattern_id,
            "owner_agent_id": self.owner_agent_id,
            "description": self.description,
            "lifecycle_transition": self.lifecycle_transition,
            "forbidden_actions": self.forbidden_actions,
            "sandbox_policies": self.sandbox_policies,
            "dry_run": self.dry_run,
            "evidence_required": self.evidence_required,
            "risk_flags": self.risk_flags,
            "metadata": self.metadata,
        }
