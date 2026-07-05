"""
m10_safety_adapter.py

Enforces M10-layer safety rules before delegating to LogiAgent.
These rules apply regardless of what LogiAgent would do:

  - No destructive action (rm -rf, delete, drop, wipe)
  - No execution from Telegram without confirmation
  - No low-confidence execution
  - Repair always requires confirmation
  - Redis-heavy work blocked unless Redis live integration PASSED
"""
from __future__ import annotations
import re
from dataclasses import dataclass

_DESTRUCTIVE_RE = re.compile(
    r"\b(rm\s+-rf|delete\s+database|drop\s+table|удали\s+базу|"
    r"wipe|purge\s+all|kill\s+all|format\s+disk|destroy)\b",
    re.IGNORECASE,
)
_EXECUTION_RE = re.compile(
    r"\b(запуст\w+|run\s+task|execute|start\s+task|выполни|deploy)\b",
    re.IGNORECASE,
)
_REPAIR_RE = re.compile(
    r"\b(исправ\w+|fix\s+error|repair|восстанов\w+)\b",
    re.IGNORECASE,
)
_REDIS_HEAVY_RE = re.compile(
    r"\b(redis\s*scheduler|restart\s+redis|перезапуст\w+\s+redis|"
    r"redis\s+daemon|flush\s+redis)\b",
    re.IGNORECASE,
)
_EXECUTION_CONFIDENCE_FLOOR = 0.75


@dataclass
class SafetyCheckResult:
    allowed: bool
    action: str          # PROCEED | BLOCK | CONFIRM_FIRST
    reason: str
    requires_confirmation: bool


def check_m10_safety(
    text: str,
    source: str,
    intent_confidence: float,
    redis_integration_passed: bool = False,
) -> SafetyCheckResult:
    low = (text or "").lower()

    # Hard block: destructive keywords
    if _DESTRUCTIVE_RE.search(text):
        return SafetyCheckResult(
            allowed=False, action="BLOCK",
            reason="destructive keyword detected — blocked unconditionally",
            requires_confirmation=False,
        )

    # Hard block: rm -rf anywhere in text
    if "rm -rf" in low or "rm-rf" in low:
        return SafetyCheckResult(
            allowed=False, action="BLOCK",
            reason="rm -rf detected — blocked unconditionally",
            requires_confirmation=False,
        )

    # Redis-heavy: block unless integration confirmed; if confirmed, still require confirmation
    if _REDIS_HEAVY_RE.search(text):
        if not redis_integration_passed:
            return SafetyCheckResult(
                allowed=False, action="BLOCK",
                reason="Redis-heavy operation blocked until REDIS_LIVE_INTEGRATION_CONFIRMATION=PASSED",
                requires_confirmation=False,
            )
        return SafetyCheckResult(
            allowed=True, action="CONFIRM_FIRST",
            reason="Redis-heavy operation allowed (integration passed) but requires operator confirmation",
            requires_confirmation=True,
        )

    # Repair: always confirm
    if _REPAIR_RE.search(text):
        return SafetyCheckResult(
            allowed=True, action="CONFIRM_FIRST",
            reason="repair action requires operator confirmation",
            requires_confirmation=True,
        )

    # Execution from Telegram: always confirm
    if source == "telegram" and _EXECUTION_RE.search(text):
        return SafetyCheckResult(
            allowed=True, action="CONFIRM_FIRST",
            reason="execution from Telegram requires confirmation",
            requires_confirmation=True,
        )

    # Low confidence execution
    if _EXECUTION_RE.search(text) and intent_confidence < _EXECUTION_CONFIDENCE_FLOOR:
        return SafetyCheckResult(
            allowed=False, action="BLOCK",
            reason=f"execution confidence {intent_confidence:.2f} < {_EXECUTION_CONFIDENCE_FLOOR}",
            requires_confirmation=False,
        )

    return SafetyCheckResult(
        allowed=True, action="PROCEED",
        reason="safety checks passed",
        requires_confirmation=False,
    )
