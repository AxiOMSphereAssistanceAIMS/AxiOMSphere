"""
AIMS Phase 17 — AIMS Agent Skill Authoring Policy.

Enforces AIMS-native constraints on skill candidates before they advance.
No model calls, no activation, no registry modification.
"""
from __future__ import annotations

from typing import Any

try:
    from .hermes_inspired_skill_curator_schema import (
        AIMS_AUTHORING_POLICIES,
        SKILL_STATE_ACTIVE,
    )
except ImportError:
    from agents.self_learning.hermes_inspired_skill_curator_schema import (  # type: ignore
        AIMS_AUTHORING_POLICIES,
        SKILL_STATE_ACTIVE,
    )


class SkillAuthoringPolicyEnforcer:
    """
    Validates skill candidates against AIMS authoring policy.
    Returns a list of violations (empty = policy compliant).
    """

    def check(self, candidate: dict[str, Any]) -> list[str]:
        violations: list[str] = []

        # State guard — ACTIVE_RUNTIME_SKILL never allowed in Phase 17
        if candidate.get("state") == SKILL_STATE_ACTIVE:
            violations.append(
                "ACTIVE_RUNTIME_SKILL state is forbidden — requires human approval outside Phase 17"
            )

        # Explicit policy flags must all be absent/False
        if candidate.get("self_approved"):
            violations.append("no_self_approval: self_approved flag must not be set")

        if candidate.get("active_registry_write"):
            violations.append(
                "no_active_registry_modification: active_registry_write must not be set"
            )

        if candidate.get("hermes_runtime_invoked"):
            violations.append(
                "no_hermes_runtime_invocation: hermes_runtime_invoked must not be set"
            )

        if candidate.get("model_endpoint_called"):
            violations.append(
                "no_model_endpoint_calls: model_endpoint_called must not be set"
            )

        if candidate.get("live_omniroute_called"):
            violations.append(
                "no_live_omniroute_calls: live_omniroute_called must not be set"
            )

        if candidate.get("training_launched"):
            violations.append(
                "no_training_launch: training_launched must not be set"
            )

        if candidate.get("model_promoted"):
            violations.append(
                "no_model_promotion: model_promoted must not be set"
            )

        if candidate.get("slot120_loaded"):
            violations.append(
                "no_slot120_loading: slot120_loaded must not be set"
            )

        if candidate.get("slot32_unloaded"):
            violations.append(
                "no_slot32_unloading: slot32_unloaded must not be set"
            )

        if candidate.get("service_restarted"):
            violations.append(
                "no_service_restart: service_restarted must not be set"
            )

        # Sandbox required before certification — check phase advancement rules
        state = candidate.get("state", "")
        if state == "CERTIFIED_SKILL" and not candidate.get("sandbox_passed"):
            violations.append(
                "sandbox_required_before_certification: "
                "sandbox_passed must be True for CERTIFIED_SKILL state"
            )

        # Human review required before any activation attempt
        if candidate.get("activation_attempted") and not candidate.get("human_approved"):
            violations.append(
                "human_review_required_before_activation: "
                "activation_attempted without human_approved"
            )

        return violations

    def check_batch(self, candidates: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Check a list of candidates; returns candidate_id → violations."""
        results: dict[str, list[str]] = {}
        for c in candidates:
            cid = c.get("candidate_id", "UNKNOWN")
            results[cid] = self.check(c)
        return results

    @staticmethod
    def policy_names() -> tuple[str, ...]:
        return AIMS_AUTHORING_POLICIES
