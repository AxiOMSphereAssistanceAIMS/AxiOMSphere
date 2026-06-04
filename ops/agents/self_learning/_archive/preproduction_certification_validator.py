"""
AIMS Self-Learning — Pre-Production Certification Validator.

Validates the certification pack before writing to disk.
No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

try:
    from .preproduction_certification_schema import (
        CERTIFICATION_STATUS_READY_BLOCKED,
        CERTIFICATION_STATUS_READY,
        CERTIFICATION_STATUS_BLOCKED,
        GO_NO_GO_CATEGORIES,
        SAFETY_CONFIRMATION_ITEMS,
        PHASES_COVERED,
    )
except ImportError:
    from agents.self_learning.preproduction_certification_schema import (  # type: ignore
        CERTIFICATION_STATUS_READY_BLOCKED,
        CERTIFICATION_STATUS_READY,
        CERTIFICATION_STATUS_BLOCKED,
        GO_NO_GO_CATEGORIES,
        SAFETY_CONFIRMATION_ITEMS,
        PHASES_COVERED,
    )


class PreproductionCertificationValidator:

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

    def validate(self, pack: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # 1. certification_id present
        if not pack.get("certification_id"):
            self._errors.append("certification_id is missing")

        # 2. created_at present
        if not pack.get("created_at"):
            self._errors.append("created_at is missing")

        # 3. certification_status is valid
        status = pack.get("certification_status", "")
        valid_statuses = {
            CERTIFICATION_STATUS_READY_BLOCKED,
            CERTIFICATION_STATUS_READY,
            CERTIFICATION_STATUS_BLOCKED,
        }
        if status not in valid_statuses:
            self._errors.append(
                f"certification_status {status!r} is not in {valid_statuses}"
            )

        # 4. phases_covered contains all 10 phases
        phases = pack.get("phases_covered", [])
        for p in PHASES_COVERED:
            if p not in phases:
                self._errors.append(f"phase {p} missing from phases_covered")

        # 5. phase_artifacts has entries for all 10 phases
        phase_artifacts = pack.get("phase_artifacts", {})
        for p in PHASES_COVERED:
            if f"phase_{p}" not in phase_artifacts:
                self._errors.append(f"phase_artifacts missing entry for phase_{p}")

        # 6. smoke_results has entries for all 10 phases
        smoke_results = pack.get("smoke_results", {})
        for p in PHASES_COVERED:
            if f"phase_{p}" not in smoke_results:
                self._errors.append(f"smoke_results missing entry for phase_{p}")

        # 7. all sentinels found
        for phase_key, result in smoke_results.items():
            if not result.get("sentinel_found"):
                self._errors.append(
                    f"smoke sentinel not found: {phase_key} — {result.get('sentinel')}"
                )

        # 8. go_no_go_matrix has all 18 categories
        gng = pack.get("go_no_go_matrix", {})
        for cat in GO_NO_GO_CATEGORIES:
            if cat not in gng:
                self._errors.append(f"go_no_go_matrix missing category: {cat}")

        # 9. safety_confirmations has all 20 items
        sc = pack.get("safety_confirmations", {})
        for item in SAFETY_CONFIRMATION_ITEMS:
            if item not in sc:
                self._errors.append(f"safety_confirmations missing: {item}")

        # 10. all safety_confirmations are True
        for item, value in sc.items():
            if value is not True:
                self._errors.append(f"safety_confirmation {item!r} is not True")

        # 11. runtime_activation_blocked is True in go_no_go_matrix
        if not gng.get("runtime_activation_blocked"):
            self._errors.append("go_no_go_matrix: runtime_activation_blocked must be True")

        # 12. active_registry_unchanged is True
        if not gng.get("active_registry_unchanged"):
            self._errors.append("go_no_go_matrix: active_registry_unchanged must be True")

        # 13. agent_behavior_unchanged is True
        if not gng.get("agent_behavior_unchanged"):
            self._errors.append("go_no_go_matrix: agent_behavior_unchanged must be True")

        # 14. activation_blockers is a non-empty list
        blockers = pack.get("activation_blockers", [])
        if not blockers:
            self._errors.append("activation_blockers must not be empty")

        # 15. required_human_decisions_before_runtime is non-empty
        decisions = pack.get("required_human_decisions_before_runtime", [])
        if not decisions:
            self._errors.append("required_human_decisions_before_runtime must not be empty")

        # 16. final_recommendation is present and non-empty
        if not pack.get("final_recommendation"):
            self._errors.append("final_recommendation is missing")

        # 17. direct_workflow_summaries present
        dws = pack.get("direct_workflow_summaries", {})
        if "phase_13" not in dws or "phase_14" not in dws:
            self._errors.append("direct_workflow_summaries must include phase_13 and phase_14")

        # 18. Phase 13 blocked count == 8
        p13 = dws.get("phase_13", {})
        if p13.get("blocked") != 8:
            self._errors.append(
                f"Phase 13 blocked must be 8, got {p13.get('blocked')}"
            )

        # 19. Phase 14 blocked_not_approved == 8
        p14 = dws.get("phase_14", {})
        if p14.get("blocked_not_approved") != 8:
            self._errors.append(
                f"Phase 14 blocked_not_approved must be 8, got {p14.get('blocked_not_approved')}"
            )

        return self.is_valid()
