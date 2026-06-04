"""
AIMS Self-Learning — Staged Skill Registry Validator.

Validates StagedCertifiedSkillEntry dicts before they are written to disk.
No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

from .staged_skill_registry_schema import (
    STAGED_LIFECYCLE_STATE,
    STAGING_GATES_ALWAYS_REQUIRED,
    STAGING_GATE_TRAINI,
    STAGING_REQUIRED_INVARIANTS,
    STAGING_STATUSES,
    ACTIVATION_REQUEST_STATUSES,
)

_FORBIDDEN_LIFECYCLE_STATE = "ACTIVE_RUNTIME_SKILL"


class StagedSkillRegistryValidator:

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

    def validate(self, entry: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # 1. lifecycle_state must be CERTIFIED_SKILL
        ls = entry.get("lifecycle_state")
        if ls != STAGED_LIFECYCLE_STATE:
            self._errors.append(
                f"lifecycle_state must be {STAGED_LIFECYCLE_STATE!r}, got {ls!r}"
            )

        # 2. No ACTIVE_RUNTIME_SKILL entries
        if ls == _FORBIDDEN_LIFECYCLE_STATE:
            self._errors.append(
                f"lifecycle_state must not be {_FORBIDDEN_LIFECYCLE_STATE}"
            )
        if _FORBIDDEN_LIFECYCLE_STATE in str(entry.get("staging_status", "")):
            self._errors.append(
                f"staging_status must not reference {_FORBIDDEN_LIFECYCLE_STATE}"
            )

        # 3. self_approval_allowed must be False
        if entry.get("self_approval_allowed") is not False:
            self._errors.append(
                f"self_approval_allowed must be False, got {entry.get('self_approval_allowed')!r}"
            )

        # 4. runtime_activation_allowed must be False
        if entry.get("runtime_activation_allowed") is not False:
            self._errors.append(
                f"runtime_activation_allowed must be False, got {entry.get('runtime_activation_allowed')!r}"
            )

        # 5. active_runtime_requested must be False
        if entry.get("active_runtime_requested") is not False:
            self._errors.append(
                f"active_runtime_requested must be False, got {entry.get('active_runtime_requested')!r}"
            )

        # 6. activation_request_status must be a valid value
        ars = entry.get("activation_request_status")
        if ars not in ACTIVATION_REQUEST_STATUSES:
            self._errors.append(
                f"activation_request_status must be one of {ACTIVATION_REQUEST_STATUSES}, got {ars!r}"
            )

        # 7. required runtime gates present
        gates = entry.get("required_runtime_gates", [])
        for gate in STAGING_GATES_ALWAYS_REQUIRED:
            if gate not in gates:
                self._errors.append(
                    f"required_runtime_gates missing: {gate!r}"
                )

        # 8. traini gate required for model_related entries
        if entry.get("model_related") and STAGING_GATE_TRAINI not in gates:
            self._errors.append(
                f"model_related entry missing gate: {STAGING_GATE_TRAINI!r}"
            )

        # 9. safety invariants
        invariants = entry.get("safety_invariants", {})
        for key in STAGING_REQUIRED_INVARIANTS:
            if invariants.get(key) is not True:
                self._errors.append(
                    f"safety_invariants[{key!r}] must be True, got {invariants.get(key)!r}"
                )

        # 10. rollback plan
        if not entry.get("rollback_plan"):
            self._errors.append("rollback_plan must be non-empty")

        # 11. deprecation plan
        if not entry.get("deprecation_plan"):
            self._errors.append("deprecation_plan must be non-empty")

        # 12. staging_status must be valid
        ss = entry.get("staging_status")
        if ss not in STAGING_STATUSES:
            self._errors.append(
                f"staging_status must be one of {STAGING_STATUSES}, got {ss!r}"
            )

        # 13. evidence_pack_refs must be non-empty
        ev = entry.get("evidence_pack_refs", [])
        if not isinstance(ev, list) or len(ev) == 0:
            self._errors.append("evidence_pack_refs must be a non-empty list")

        # warn on missing staged_skill_id
        if not entry.get("staged_skill_id"):
            self._warnings.append("staged_skill_id is missing or empty")

        return self.is_valid()

    def validate_registry(self, entries: list[dict[str, Any]]) -> bool:
        """Validate all entries; return True only if every entry passes."""
        all_valid = True
        for entry in entries:
            if not self.validate(entry):
                all_valid = False
        return all_valid
