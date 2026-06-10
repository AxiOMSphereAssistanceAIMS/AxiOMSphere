"""
DOCSREG protected-actions audit gate — hard pre-certification gate.

Reads ``protected_actions_audit.json`` from the evidence directory and verifies
that every flag in it is ``False``.  A document with *any* protected-action flag
set to ``True`` may not proceed to certification.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It reads one JSON file only.

Exports
-------
PROTECTED_ACTIONS_FILE : str
    Filename of the audit JSON (not a path).
ProtectedActionsResult : dataclass
    Outcome of a single gate check.
check_protected_actions(evidence_dir) -> ProtectedActionsResult
    Public entry point — never raises.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("docsreg_protected_actions_gate")

# ── Constant ───────────────────────────────────────────────────────────────────

PROTECTED_ACTIONS_FILE: str = "protected_actions_audit.json"


# ── Result dataclass ───────────────────────────────────────────────────────────


@dataclass
class ProtectedActionsResult:
    """Outcome of a single protected-actions audit gate check.

    Attributes
    ----------
    passed:
        ``True`` only when every flag in the audit file is ``False`` (falsy)
        AND the file exists and is valid JSON.
    flagged_actions:
        Names of flags whose values were truthy (non-False / non-zero /
        non-empty).  Empty list on pass.
    all_actions:
        All flag names found in the audit JSON object, regardless of value.
    evidence_dir:
        String form of the evidence directory path that was checked.
    notes:
        Human-readable explanation of any failure reason; ``"all protected
        actions clear"`` on success.
    """

    passed: bool
    flagged_actions: list[str] = field(default_factory=list)
    all_actions: list[str] = field(default_factory=list)
    evidence_dir: str = ""
    notes: str = ""


# ── Public API ─────────────────────────────────────────────────────────────────


def check_protected_actions(evidence_dir: str | Path) -> ProtectedActionsResult:
    """Check that no protected-action flags are set in the audit JSON.

    Args:
        evidence_dir: Path to the directory that should contain
            ``protected_actions_audit.json``.  Accepts both ``str`` and
            :class:`pathlib.Path`.

    Returns:
        :class:`ProtectedActionsResult` describing which actions (if any) are
        flagged.  ``result.passed`` is ``True`` only when every key in the
        audit JSON maps to a falsy value.

    This function never raises.  Any unexpected error is caught, logged at
    WARNING level, and returned as a failed result.
    """
    try:
        dir_path = Path(evidence_dir)
        dir_str = str(dir_path)

        # 1. Directory existence check
        if not dir_path.is_dir():
            log.warning(
                "protected_actions_gate: FAIL — directory does not exist: %s",
                dir_str,
            )
            return ProtectedActionsResult(
                passed=False,
                evidence_dir=dir_str,
                notes="evidence directory does not exist",
            )

        # 2. File existence check
        audit_file = dir_path / PROTECTED_ACTIONS_FILE
        if not audit_file.is_file():
            log.warning(
                "protected_actions_gate: FAIL — %s not found in %s",
                PROTECTED_ACTIONS_FILE,
                dir_str,
            )
            return ProtectedActionsResult(
                passed=False,
                evidence_dir=dir_str,
                notes=f"{PROTECTED_ACTIONS_FILE} not found",
            )

        # 3. JSON parse
        try:
            raw_text = audit_file.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError, OSError):
            log.warning(
                "protected_actions_gate: FAIL — could not read or parse %s",
                audit_file,
            )
            return ProtectedActionsResult(
                passed=False,
                evidence_dir=dir_str,
                notes=f"{PROTECTED_ACTIONS_FILE} contains invalid JSON",
            )

        # 4. Must be a dict
        if not isinstance(data, dict):
            log.warning(
                "protected_actions_gate: FAIL — expected JSON object, got %s in %s",
                type(data).__name__,
                audit_file,
            )
            return ProtectedActionsResult(
                passed=False,
                evidence_dir=dir_str,
                notes=f"{PROTECTED_ACTIONS_FILE} must be a JSON object",
            )

        # 5. Inspect every key-value pair
        all_actions: list[str] = list(data.keys())
        flagged_actions: list[str] = [k for k, v in data.items() if v]

        if flagged_actions:
            notes = f"{len(flagged_actions)} protected action(s) flagged: {flagged_actions}"
            log.warning(
                "protected_actions_gate: FAIL — %s in %s",
                notes,
                dir_str,
            )
            return ProtectedActionsResult(
                passed=False,
                flagged_actions=flagged_actions,
                all_actions=all_actions,
                evidence_dir=dir_str,
                notes=notes,
            )

        # 6. All clear
        log.info(
            "protected_actions_gate: PASS — all %d action(s) clear in %s",
            len(all_actions),
            dir_str,
        )
        return ProtectedActionsResult(
            passed=True,
            flagged_actions=[],
            all_actions=all_actions,
            evidence_dir=dir_str,
            notes="all protected actions clear",
        )

    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        log.error(
            "protected_actions_gate: FAIL — unexpected error: %s",
            exc,
        )
        return ProtectedActionsResult(
            passed=False,
            notes=f"unexpected error: {exc}",
        )
