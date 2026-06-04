"""
AIMS Phase 17 — Skill Curator Validator.

Validates the curation report before writing to disk.
14 validation checks. No model calls, no I/O.
"""
from __future__ import annotations

from typing import Any

try:
    from .hermes_inspired_skill_curator_schema import (
        HERMES_REFERENCE_CATEGORIES,
        AIMS_AUTHORING_POLICIES,
        CURATOR_STATUS_READY,
        CURATOR_STATUS_BLOCKED,
        PHASE,
    )
except ImportError:
    from agents.self_learning.hermes_inspired_skill_curator_schema import (  # type: ignore
        HERMES_REFERENCE_CATEGORIES,
        AIMS_AUTHORING_POLICIES,
        CURATOR_STATUS_READY,
        CURATOR_STATUS_BLOCKED,
        PHASE,
    )

_VALID_STATUSES = {CURATOR_STATUS_READY, CURATOR_STATUS_BLOCKED}


class SkillCuratorValidator:

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

    def validate(self, report: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # 1. phase == 17
        if report.get("phase") != PHASE:
            self._errors.append(f"phase must be {PHASE}, got {report.get('phase')!r}")

        # 2. schema_version present
        if not report.get("schema_version"):
            self._errors.append("schema_version is missing")

        # 3. created_at present
        if not report.get("created_at"):
            self._errors.append("created_at is missing")

        # 4. curator_status is valid
        status = report.get("curator_status", "")
        if status not in _VALID_STATUSES:
            self._errors.append(f"curator_status {status!r} not in {_VALID_STATUSES}")

        # 5. hermes_references_loaded == len(HERMES_REFERENCE_CATEGORIES)
        expected_refs = len(HERMES_REFERENCE_CATEGORIES)
        loaded = report.get("hermes_references_loaded", 0)
        if loaded != expected_refs:
            self._errors.append(
                f"hermes_references_loaded must be {expected_refs}, got {loaded}"
            )

        # 6. candidates_evaluated >= 0
        if report.get("candidates_evaluated", -1) < 0:
            self._errors.append("candidates_evaluated must be >= 0")

        # 7. active_registry_modified is False
        if report.get("active_registry_modified") is not False:
            self._errors.append("active_registry_modified must be False")

        # 8. hermes_runtime_invoked is False
        if report.get("hermes_runtime_invoked") is not False:
            self._errors.append("hermes_runtime_invoked must be False")

        # 9. model_endpoints_called is False
        if report.get("model_endpoints_called") is not False:
            self._errors.append("model_endpoints_called must be False")

        # 10. training_launched is False
        if report.get("training_launched") is not False:
            self._errors.append("training_launched must be False")

        # 11. candidates is a list
        candidates = report.get("candidates", None)
        if not isinstance(candidates, list):
            self._errors.append("candidates must be a list")

        # 12. hermes_references is a list with correct length
        refs = report.get("hermes_references", [])
        if not isinstance(refs, list):
            self._errors.append("hermes_references must be a list")
        elif len(refs) != expected_refs:
            self._errors.append(
                f"hermes_references must have {expected_refs} entries, got {len(refs)}"
            )

        # 13. policy_summary present and non-empty
        policy = report.get("policy_summary", {})
        if not policy:
            self._errors.append("policy_summary must not be empty")

        # 14. no ACTIVE_RUNTIME_SKILL state in any candidate
        if isinstance(candidates, list):
            for c in candidates:
                if isinstance(c, dict) and c.get("state") == "ACTIVE_RUNTIME_SKILL":
                    self._errors.append(
                        f"candidate {c.get('candidate_id')!r} has forbidden "
                        "ACTIVE_RUNTIME_SKILL state"
                    )

        return self.is_valid()
