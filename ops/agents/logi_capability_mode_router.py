"""
logi_capability_mode_router.py

Classifies Logi messages into capability modes and routes them.

Routing priority:
  1. CONFIRM <ACTION_ID>                 → confirmation flow
  2. run_local_executor_task / approved  → controlled executor
  3. Dangerous/blocked command           → BLOCKED
  4. Protected confirmation actions      → healthcheck/read_logs/diagnose
  5. Skill-based modes (office_hours, etc.) → skill system
  6. Status/context queries              → STATUS_CONTEXT
  7. General chat fallback               → GENERAL_CHAT

This router classifies only. Execution is delegated to:
  - logi_confirmation_flow (protected actions)
  - logi_skill_system (skill dispatch)
  - conversational_orchestrator (general chat)
  - local_executor_action (executor route)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ─── Mode definitions ─────────────────────────────────────────────────────────

MODES = {
    "GENERAL_CHAT",
    "STATUS_CONTEXT",
    "PLAN_TASK",
    "DECOMPOSE_TASK",
    "ORCHESTRATE_BOTS",
    "QUEUE_TASK",
    "SCHEDULE_TASK",
    "VERIFY_AGENT_WORK",
    "CAPABILITY_GAP_ANALYSIS",
    "PATCH_PROMPT_PREPARATION",
    "AUDITOR_HELP_REQUEST",
    "SKILL_REQUEST",
    "LEARNING_REGISTRATION",
    "SELF_CHECK_TASK",
    "REPAIR_LOOP_REQUEST",
    "REPO_INTELLIGENCE_REQUEST",
    "HEALTHCHECK_SERVICE",
    "READ_LOGS_ALLOWLISTED",
    "DIAGNOSE_SERVICE_ALLOWLISTED",
    "SKILL_DISPATCH",       # general skill system hit
    "BLOCKED",
}

_BLOCKED_CHARS_RE = re.compile(r"[;&|`$<>\r\n\\]")
_BLOCKED_WORDS_RE = re.compile(
    r"\b(?:rm|sudo|curl|wget|chmod|chown|dd|mkfs|systemctl|aws"
    r"|docker\s+restart|docker\s+exec)\b",
    re.IGNORECASE,
)
_CONFIRM_RE = re.compile(r"^\s*CONFIRM\s+[a-f0-9]{8,}\s*$", re.IGNORECASE)
_EXECUTOR_RE = re.compile(
    r"(?:run[_\s]+(?:approved[_\s]+)?local[_\s]+executor[_\s]+task|run_local_executor_task)"
    r"[:\s]+[^\s\n]+\.json",
    re.IGNORECASE,
)

# Mode-specific keyword patterns
_MODE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("QUEUE_TASK", re.compile(
        r"\b(?:поставь в очередь|queue\s+task|add\s+to\s+queue|добавь в очередь)\b",
        re.IGNORECASE)),
    ("SCHEDULE_TASK", re.compile(
        r"\b(?:запланируй|schedule\s+task|schedule\s+for|поставь на расписание)\b",
        re.IGNORECASE)),
    ("DECOMPOSE_TASK", re.compile(
        r"\b(?:разбей на части|decompose|декомпозируй|разбей задачу|разбей на подзадачи)\b",
        re.IGNORECASE)),
    ("ORCHESTRATE_BOTS", re.compile(
        r"\b(?:оркестрируй|orchestrate|запусти агент|запусти бота|delegate to agent)\b",
        re.IGNORECASE)),
    ("VERIFY_AGENT_WORK", re.compile(
        r"\b(?:проверь работу|verify agent|verify work|проверь результат агента)\b",
        re.IGNORECASE)),
    ("SELF_CHECK_TASK", re.compile(
        r"\b(?:self.?check|самопроверка|проверь себя|self check)\b",
        re.IGNORECASE)),
    ("REPAIR_LOOP_REQUEST", re.compile(
        r"\b(?:repair loop|цикл ремонта|запусти ремонт|починка|fix\s+loop)\b",
        re.IGNORECASE)),
    ("REPO_INTELLIGENCE_REQUEST", re.compile(
        r"\b(?:repo intelligence|анализ репо|анализ кода|repo analysis|code analysis)\b",
        re.IGNORECASE)),
    ("STATUS_CONTEXT", re.compile(
        r"\b(?:статус|status|состояние|state|покажи статус|show status|project status)\b",
        re.IGNORECASE)),
    ("PLAN_TASK", re.compile(
        r"\b(?:план|plan|спланируй|plan this|create plan|сделай план)\b",
        re.IGNORECASE)),
]


@dataclass
class ModeClassification:
    mode: str
    confidence: float
    skill_id: str | None
    reason: str
    blocked_reason: str | None = None
    requires_confirmation: bool = False


@dataclass
class ModeRouteResult:
    mode: str
    classification: ModeClassification
    skill_id: str | None
    response: str | None          # formatted response if mode is deterministic
    requires_execution: bool      # True for protected actions / executor
    artifact_type: str | None
    next_recommended_skills: list[str]


def classify_logi_mode(text: str) -> ModeClassification:
    """Classify a message into a capability mode."""
    if not text or not text.strip():
        return ModeClassification("GENERAL_CHAT", 0.3, None, "empty input")

    low = text.lower()

    # 1. CONFIRM
    if _CONFIRM_RE.match(text):
        return ModeClassification("HEALTHCHECK_SERVICE", 1.0, None,
                                  "CONFIRM pattern — routes to confirmation flow")

    # 2. Executor route
    if _EXECUTOR_RE.search(text):
        return ModeClassification("VERIFY_AGENT_WORK", 0.95, None,
                                  "controlled executor route detected",
                                  requires_confirmation=False)

    # 3. Dangerous command
    if _BLOCKED_CHARS_RE.search(text) or _BLOCKED_WORDS_RE.search(text):
        return ModeClassification("BLOCKED", 1.0, None,
                                  "dangerous metacharacter or command word detected",
                                  blocked_reason="COMMAND_BLOCKED")

    # 4. Check skill system matches (highest priority for named skills)
    from ops.agents.logi_skill_system import find_skill
    skill = find_skill(text)
    if skill:
        if skill.requires_confirmation:
            mode_map = {
                "auditor_request": "AUDITOR_HELP_REQUEST",
                "skill_request": "SKILL_REQUEST",
                "learning_registration": "LEARNING_REGISTRATION",
            }
            mode = mode_map.get(skill.skill_id, "SKILL_DISPATCH")
            return ModeClassification(mode, 0.9, skill.skill_id,
                                      f"skill match: {skill.skill_id}",
                                      requires_confirmation=True)
        mode_map = {
            "office_hours": "SKILL_DISPATCH",
            "ceo_review": "SKILL_DISPATCH",
            "eng_review": "SKILL_DISPATCH",
            "autoplan": "SKILL_DISPATCH",
            "capability_gap": "CAPABILITY_GAP_ANALYSIS",
            "patch_prompt": "PATCH_PROMPT_PREPARATION",
            "investigate": "SKILL_DISPATCH",
            "review": "SKILL_DISPATCH",
            "qa": "SKILL_DISPATCH",
            "security_cso": "SKILL_DISPATCH",
            "release_ship": "SKILL_DISPATCH",
            "retro": "SKILL_DISPATCH",
            "learn": "SKILL_DISPATCH",
        }
        mode = mode_map.get(skill.skill_id, "SKILL_DISPATCH")
        return ModeClassification(mode, 0.88, skill.skill_id, f"skill match: {skill.skill_id}")

    # 5. Protected action patterns (healthcheck/logs/diagnose)
    if re.search(r"\b(?:проверь\s+(?:здоровье|статус)|healthcheck|check\s+health)\b", low):
        return ModeClassification("HEALTHCHECK_SERVICE", 0.9, None,
                                  "healthcheck intent", requires_confirmation=True)
    if re.search(r"\b(?:покажи\s+(?:логи|log)|show\s+logs?|read\s+logs?)\b", low):
        return ModeClassification("READ_LOGS_ALLOWLISTED", 0.9, None,
                                  "read_logs intent", requires_confirmation=True)
    if re.search(r"\b(?:диагностируй|диагностика|diagnose|run\s+diagnostics?)\b", low):
        return ModeClassification("DIAGNOSE_SERVICE_ALLOWLISTED", 0.9, None,
                                  "diagnose intent", requires_confirmation=True)

    # 6. Mode keyword patterns
    for mode, pattern in _MODE_PATTERNS:
        if pattern.search(text):
            return ModeClassification(mode, 0.75, None, f"keyword match for {mode}")

    # 7. Fallback
    return ModeClassification("GENERAL_CHAT", 0.4, None, "no specific mode matched")


def route_logi_mode(
    text: str,
    source: str = "telegram",
    chat_id: str = "0",
    from_user: str = "",
) -> ModeRouteResult:
    """
    Classify message and produce a route result.

    For skill modes: generates structured text output directly.
    For protected actions and executor: signals that execution is required.
    """
    classification = classify_logi_mode(text)
    mode = classification.mode

    if mode == "BLOCKED":
        return ModeRouteResult(
            mode=mode,
            classification=classification,
            skill_id=None,
            response=(
                f"STATUS: BLOCKED\n"
                f"ERROR_CLASS: {classification.blocked_reason}\n"
                f"REASON: dangerous command or metacharacter detected"
            ),
            requires_execution=False,
            artifact_type=None,
            next_recommended_skills=[],
        )

    if mode == "SKILL_DISPATCH" and classification.skill_id:
        from ops.agents.logi_skill_system import SKILL_REGISTRY
        skill = SKILL_REGISTRY.get(classification.skill_id)
        if skill:
            return ModeRouteResult(
                mode=mode,
                classification=classification,
                skill_id=classification.skill_id,
                response=None,  # caller should run skill executor
                requires_execution=False,
                artifact_type=skill.artifact_type,
                next_recommended_skills=skill.next_recommended_skills,
            )

    # Protected action modes delegate to confirmation flow
    protected = {
        "HEALTHCHECK_SERVICE", "READ_LOGS_ALLOWLISTED", "DIAGNOSE_SERVICE_ALLOWLISTED",
        "AUDITOR_HELP_REQUEST", "SKILL_REQUEST", "LEARNING_REGISTRATION",
        "QUEUE_TASK", "SCHEDULE_TASK",
    }
    if mode in protected:
        return ModeRouteResult(
            mode=mode,
            classification=classification,
            skill_id=classification.skill_id,
            response=None,
            requires_execution=True,
            artifact_type="request",
            next_recommended_skills=[],
        )

    return ModeRouteResult(
        mode=mode,
        classification=classification,
        skill_id=classification.skill_id,
        response=None,
        requires_execution=False,
        artifact_type=None,
        next_recommended_skills=[],
    )


def format_mode_result_for_telegram(result: ModeRouteResult) -> str:
    """Format a ModeRouteResult as a Telegram-safe string."""
    if result.response:
        return result.response
    mode = result.mode
    skill_id = result.skill_id or mode.lower()
    return (
        f"STATUS: ROUTED\n"
        f"MODE: {mode}\n"
        f"SKILL_ID: {skill_id}\n"
        f"REQUIRES_EXECUTION: {'true' if result.requires_execution else 'false'}"
    )
