"""
AIMS Self-Learning — Sandbox Execution Policy.

Defines policy checks applied before and during sandbox execution.
Enforces: no secrets in input, no forbidden actions, dry-run-only mode.
No model calls, no I/O beyond fixture reads.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from .sandbox_execution_schema import (
    EXEC_STATUS_REJECTED,
    EXEC_STATUS_FAIL,
)
from .sandbox_skill_plan_schema import MANDATORY_FORBIDDEN_ACTIONS

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)

# Keywords in input that signal a forbidden production action request
_PRODUCTION_ACTION_KEYWORDS = frozenset({
    "restart_service",
    "deploy_to_production",
    "modify_production_db",
    "grant_production_access",
    "enable_runtime_activation",
    "run_training_job",
    "write_secret",
    "quarantine_model",
    "delete_file",
    "modify_env",
})


class SandboxExecutionPolicy:
    """
    Stateless policy checker for sandbox execution requests.

    check_input() must pass before harness runs the plan.
    check_forbidden_actions() validates no plan-forbidden actions appear in output.
    """

    def __init__(self) -> None:
        self._violations: list[str] = []

    @property
    def violations(self) -> list[str]:
        return list(self._violations)

    def check_input(self, input_text: str) -> tuple[bool, str]:
        """
        Returns (ok, rejection_reason).

        Rejects if input contains secret-like values or production action keywords.
        """
        self._violations.clear()

        secret_hits = _SECRET_RE.findall(input_text)
        if secret_hits:
            reason = f"Input contains secret-like values: {secret_hits[:3]}"
            self._violations.append(reason)
            return False, reason

        found_keywords = [
            kw for kw in _PRODUCTION_ACTION_KEYWORDS
            if kw in input_text.lower().replace("-", "_").replace(" ", "_")
        ]
        if found_keywords:
            reason = f"Input requests forbidden production actions: {found_keywords}"
            self._violations.append(reason)
            return False, reason

        return True, ""

    def check_forbidden_actions(
        self,
        plan_forbidden: list[str],
        execution_log: list[str],
    ) -> list[str]:
        """
        Returns list of forbidden actions found in execution_log lines.

        Any match → harness must set status to SANDBOX_FAIL.
        """
        triggered: list[str] = []
        log_text = "\n".join(execution_log).lower().replace("-", "_").replace(" ", "_")
        for action in plan_forbidden:
            normalized = action.lower().replace("-", "_")
            if normalized in log_text:
                triggered.append(action)
        return triggered

    def check_no_secrets_in_output(self, output: Any) -> bool:
        """Returns True if output (serialized as str) contains no secret-like values."""
        return not bool(_SECRET_RE.search(str(output)))

    def load_fixture(self, fixture_path: str) -> tuple[str, str | None]:
        """
        Load a fixture file. Returns (content, error_message).

        error_message is None on success.
        """
        p = pathlib.Path(fixture_path)
        if not p.exists():
            return "", f"Fixture not found: {fixture_path}"
        try:
            return p.read_text(encoding="utf-8", errors="replace"), None
        except Exception as exc:
            return "", f"Failed to read fixture: {exc}"
