"""
AIMS Self-Learning — SandboxSkillPlan Generator.

Converts READY_FOR_SANDBOX CandidateSkill dicts into SandboxSkillPlan
objects. REJECTED/REVIEW candidates are skipped (not plannable).
No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

from .sandbox_skill_plan_schema import SandboxSkillPlan
from .skill_candidate_schema import CANDIDATE_STATUS_READY


def generate_plan(candidate: dict[str, Any]) -> SandboxSkillPlan | None:
    """
    Generate a SandboxSkillPlan from a CandidateSkill dict.

    Returns None if the candidate is not READY_FOR_SANDBOX.
    """
    if candidate.get("candidate_status") != CANDIDATE_STATUS_READY:
        return None
    return SandboxSkillPlan.from_candidate(candidate)


def generate_plans(candidates: list[dict[str, Any]]) -> list[SandboxSkillPlan]:
    """Generate plans for all READY candidates; skip others."""
    plans: list[SandboxSkillPlan] = []
    for c in candidates:
        plan = generate_plan(c)
        if plan is not None:
            plans.append(plan)
    return plans
