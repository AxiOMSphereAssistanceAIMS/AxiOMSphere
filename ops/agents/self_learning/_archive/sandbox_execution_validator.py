"""
AIMS Self-Learning — Sandbox Execution Result Validator.

Validates SandboxExecutionResult dicts after harness execution.
No model calls, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from .sandbox_execution_schema import (
    EXEC_STATUSES,
    EXEC_STATUS_PASS,
    REQUIRED_EVIDENCE_KEYS,
)

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)


class SandboxExecutionValidator:

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

    def validate(self, result: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # status must be a valid execution status
        status = result.get("status")
        if status not in EXEC_STATUSES:
            self._errors.append(
                f"status must be one of {EXEC_STATUSES}, got {status!r}"
            )

        # dry_run must be True
        if result.get("dry_run") is not True:
            self._errors.append(f"dry_run must be True, got {result.get('dry_run')!r}")

        # evidence_pack must contain all required keys
        evidence = result.get("evidence_pack", {})
        if not isinstance(evidence, dict):
            self._errors.append("evidence_pack must be a dict")
        else:
            missing_ev = [k for k in REQUIRED_EVIDENCE_KEYS if k not in evidence]
            if missing_ev:
                self._errors.append(
                    f"evidence_pack missing required keys: {missing_ev}"
                )

        # execution_log must be a non-empty list
        log = result.get("execution_log", [])
        if not isinstance(log, list) or len(log) == 0:
            self._errors.append("execution_log must be a non-empty list")

        # PASS status requires no_secrets_detected True
        if status == EXEC_STATUS_PASS and result.get("no_secrets_detected") is not True:
            self._errors.append(
                "SANDBOX_PASS result must have no_secrets_detected=True"
            )

        # PASS status requires no forbidden actions triggered
        if status == EXEC_STATUS_PASS and result.get("forbidden_actions_triggered"):
            self._errors.append(
                "SANDBOX_PASS result must have empty forbidden_actions_triggered"
            )

        # PASS status requires no assertion failures
        if status == EXEC_STATUS_PASS and result.get("assertion_failures"):
            self._errors.append(
                "SANDBOX_PASS result must have empty assertion_failures"
            )

        # No secret-like values in the result dict
        if _SECRET_RE.search(str(result)):
            self._errors.append("Result dict contains secret-like values")

        # Warn if execution_id is missing
        if not result.get("execution_id"):
            self._warnings.append("execution_id is missing or empty")

        return self.is_valid()
