"""
AIMS Self-Learning — SandboxSkillPlan Validator.

Validates SandboxSkillPlan dicts before they are written to disk
or passed to the execution harness. No model calls, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from .sandbox_skill_plan_schema import (
    PLAN_LIFECYCLE_TRANSITION,
    MANDATORY_FORBIDDEN_ACTIONS,
    POLICY_READONLY,
    POLICY_NO_ACCESS,
    POLICY_DRY_RUN_ONLY,
    POLICY_DISALLOWED,
    _POLICY_FILESYSTEM,
    _POLICY_MODEL,
    _POLICY_PRODUCTION,
    _POLICY_SECRETS,
)

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)

_VALID_POLICIES = frozenset({
    POLICY_READONLY, POLICY_NO_ACCESS, POLICY_DRY_RUN_ONLY, POLICY_DISALLOWED
})


class SandboxSkillPlanValidator:

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

    def validate(self, plan: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # lifecycle_transition
        lt = plan.get("lifecycle_transition")
        if lt != PLAN_LIFECYCLE_TRANSITION:
            self._errors.append(
                f"lifecycle_transition must be {PLAN_LIFECYCLE_TRANSITION!r}, got {lt!r}"
            )

        # dry_run must be True
        if plan.get("dry_run") is not True:
            self._errors.append(
                f"dry_run must be True, got {plan.get('dry_run')!r}"
            )

        # forbidden_actions must include all mandatory entries
        fa = plan.get("forbidden_actions", [])
        missing_fa = [a for a in MANDATORY_FORBIDDEN_ACTIONS if a not in fa]
        if missing_fa:
            self._errors.append(
                f"forbidden_actions missing mandatory entries: {missing_fa}"
            )

        # sandbox_policies must have all 4 keys with valid values
        policies = plan.get("sandbox_policies", {})
        for key in (_POLICY_FILESYSTEM, _POLICY_MODEL, _POLICY_PRODUCTION, _POLICY_SECRETS):
            val = policies.get(key)
            if val is None:
                self._errors.append(f"sandbox_policies missing key: {key!r}")
            elif val not in _VALID_POLICIES:
                self._errors.append(
                    f"sandbox_policies[{key!r}] has invalid value {val!r}"
                )

        # secrets policy must be DISALLOWED
        if policies.get(_POLICY_SECRETS) not in (POLICY_DISALLOWED, None):
            self._errors.append(
                f"secrets_policy must be {POLICY_DISALLOWED!r}"
            )

        # evidence_required must be a non-empty list
        ev = plan.get("evidence_required", [])
        if not isinstance(ev, list) or len(ev) == 0:
            self._errors.append("evidence_required must be a non-empty list")

        # No secrets anywhere in the plan dict
        if _SECRET_RE.search(str(plan)):
            self._errors.append("Plan dict contains secret-like values")

        # Warn if plan_id is missing
        if not plan.get("plan_id"):
            self._warnings.append("plan_id is missing or empty")

        return self.is_valid()
