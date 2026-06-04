"""
AIMS Self-Learning — Certified Skill Package Validator.

Validates CertifiedSkillPackage dicts before they are written to disk.
No model calls, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from .certified_skill_schema import (
    CERT_LIFECYCLE_TRANSITION,
    CERT_STATUSES,
    CERT_STATUS_WARN,
    CERT_STATUS_REJECTED,
    _FORBIDDEN_TARGET_STATE,
    GATES_ALWAYS_REQUIRED_BEFORE_RUNTIME,
    GATE_TRAINI_RUNTIME,
    REQUIRED_SAFETY_INVARIANTS,
)

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)


class CertifiedSkillPackageValidator:

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

    def validate(self, pkg: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # 1. lifecycle_transition must be correct
        lt = pkg.get("lifecycle_transition")
        if lt != CERT_LIFECYCLE_TRANSITION:
            self._errors.append(
                f"lifecycle_transition must be {CERT_LIFECYCLE_TRANSITION!r}, got {lt!r}"
            )

        # 2. certification_status must be allowed
        status = pkg.get("certification_status")
        if status not in CERT_STATUSES:
            self._errors.append(
                f"certification_status must be one of {CERT_STATUSES}, got {status!r}"
            )

        # 3. No package may target ACTIVE_RUNTIME_SKILL
        if pkg.get("target_state") == _FORBIDDEN_TARGET_STATE:
            self._errors.append(
                f"Package may not target {_FORBIDDEN_TARGET_STATE}"
            )
        if _FORBIDDEN_TARGET_STATE in str(pkg.get("lifecycle_transition", "")):
            self._errors.append(
                f"lifecycle_transition must not reference {_FORBIDDEN_TARGET_STATE}"
            )

        # 4. self_approval_allowed must be False
        if pkg.get("self_approval_allowed") is not False:
            self._errors.append(
                f"self_approval_allowed must be False, got {pkg.get('self_approval_allowed')!r}"
            )

        # 5. runtime_activation_allowed must be False
        if pkg.get("runtime_activation_allowed") is not False:
            self._errors.append(
                f"runtime_activation_allowed must be False, got {pkg.get('runtime_activation_allowed')!r}"
            )

        # 6. active_runtime_requested must be False
        if pkg.get("active_runtime_requested") is not False:
            self._errors.append(
                f"active_runtime_requested must be False, got {pkg.get('active_runtime_requested')!r}"
            )

        # 7. evidence_pack_refs must be non-empty
        ev = pkg.get("evidence_pack_refs", [])
        if not isinstance(ev, list) or len(ev) == 0:
            self._errors.append("evidence_pack_refs must be a non-empty list")

        # 8. rollback_plan must be non-empty
        if not pkg.get("rollback_plan"):
            self._errors.append("rollback_plan must be non-empty")

        # 9. deprecation_plan must be non-empty
        if not pkg.get("deprecation_plan"):
            self._errors.append("deprecation_plan must be non-empty")

        # 10. safety_invariants must include all required keys set to True
        invariants = pkg.get("safety_invariants", {})
        for key in REQUIRED_SAFETY_INVARIANTS:
            if invariants.get(key) is not True:
                self._errors.append(
                    f"safety_invariants[{key!r}] must be True, got {invariants.get(key)!r}"
                )

        # 11. gates_required_before_runtime must include all always-required gates
        gates = pkg.get("gates_required_before_runtime", [])
        for gate in GATES_ALWAYS_REQUIRED_BEFORE_RUNTIME:
            if gate not in gates:
                self._errors.append(
                    f"gates_required_before_runtime missing required gate: {gate!r}"
                )

        # 12. traini_gate required when model_related=True
        if pkg.get("model_related") and GATE_TRAINI_RUNTIME not in gates:
            self._errors.append(
                f"model_related package must have {GATE_TRAINI_RUNTIME!r} in gates_required_before_runtime"
            )

        # 13. production_related packages must be CERTIFIED_SKILL_WARN
        if pkg.get("production_related") and status == "CERTIFIED_SKILL_READY":
            self._errors.append(
                "production_related package must have certification_status=CERTIFIED_SKILL_WARN"
            )

        # 14. CERTIFICATION_REJECTED packages must not arise from SANDBOX_PASS
        # (informational: REJECTED is only produced by the generator for non-PASS inputs)
        # Validator cannot know the source status here, so warn if REJECTED has evidence_refs
        if status == CERT_STATUS_REJECTED and ev:
            self._warnings.append(
                "CERTIFICATION_REJECTED package has evidence_pack_refs — verify source execution status"
            )

        # 15. No secret-like values in package dict
        if _SECRET_RE.search(str(pkg)):
            self._errors.append("Package dict contains secret-like values")

        # Warn on missing certified_skill_id
        if not pkg.get("certified_skill_id"):
            self._warnings.append("certified_skill_id is missing or empty")

        return self.is_valid()
