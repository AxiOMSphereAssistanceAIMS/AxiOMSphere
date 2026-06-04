"""Deterministic natural-language intent interpreter for Logi Telegram messages."""

from __future__ import annotations

import re

from logi.syntax_intent_schema import SyntaxIntent

_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _lang(normalized: str) -> str:
    return "ru" if _CYRILLIC_RE.search(normalized) else "en"


def _has_negated_keyword(normalized: str, keyword: str) -> bool:
    negations = (
        f"do not {keyword}",
        f"don't {keyword}",
        f"do n't {keyword}",
        f"не {keyword}",
        f"не надо {keyword}",
        f"не выполняй {keyword}",
        f"не запускай {keyword}",
        f"не перезапускай {keyword}",
    )
    return any(phrase in normalized for phrase in negations)


def interpret_syntax_intent(raw_text: str) -> SyntaxIntent:
    normalized = _normalize(raw_text)
    lang = _lang(normalized)

    def intent(intent_type: str, horizon: str = "none", mode: str = "unknown", *,
               target_agents: list[str] | None = None, workflow: str = "none", confidence: float = 0.9,
               safety_class: str = "safe_read", response_style: str = "plain") -> SyntaxIntent:
        return SyntaxIntent(
            raw_text=raw_text,
            normalized_text=normalized,
            detected_language=lang,
            intent_type=intent_type,
            horizon=horizon,
            mode=mode,
            target_agents=target_agents or [],
            requested_workflow=workflow,
            confidence=confidence,
            safety_class=safety_class,
            enabled=False,
            reason="interpreted",
            response_style=response_style,
        )

    if not normalized:
        return intent("unknown", confidence=0.0, safety_class="unknown", response_style="clarify")

    # Mutation/unsafe actions first.
    if any(k in normalized for k in ["approve", "подтверди", "подтвердить"]):
        return intent("approval_action", mode="mutation", confidence=0.98, safety_class="mutation_blocked")
    repairman_context = any(
        phrase in normalized
        for phrase in [
            "repairman",
            "repairman task",
            "repairman tasks",
            "repair task",
            "repair tasks",
        ]
    )
    if re.search(r"\brepair\b", normalized) and not repairman_context and not _has_negated_keyword(normalized, "repair"):
        return intent("repair_action", mode="mutation", confidence=0.98, safety_class="mutation_blocked")
    if any(k in normalized for k in ["почини", "исправь", "исправить"]) and not _has_negated_keyword(normalized, "исправь"):
        return intent("repair_action", mode="mutation", confidence=0.98, safety_class="mutation_blocked")
    if any(k in normalized for k in ["execute", "run now", "выполни", "запусти"]) and not _has_negated_keyword(normalized, "execute"):
        return intent("execute_action", mode="mutation", confidence=0.98, safety_class="mutation_blocked")
    if any(k in normalized for k in ["restart", "перезапусти"]) and not _has_negated_keyword(normalized, "restart"):
        return intent("restart_action", mode="mutation", confidence=0.98, safety_class="mutation_blocked")
    if any(k in normalized for k in ["activate skill", "активируй навык", "активируй скилл", "activate"]) and not _has_negated_keyword(normalized, "activate"):
        return intent("activate_action", mode="mutation", confidence=0.95, safety_class="mutation_blocked")

    # Inter-agent review / consolidated decision.
    if (("codex" in normalized and "hermes" in normalized and "review" in normalized)
            or "спроси codex и hermes" in normalized
            or "codex и hermes" in normalized and "ревью" in normalized):
        return intent(
            "inter_agent_review_request",
            mode="request_only",
            target_agents=["codex", "hermes"],
            workflow="review_request",
            confidence=0.95,
            safety_class="request_gated",
        )
    if (("consolidated decision" in normalized and "codex" in normalized and "hermes" in normalized)
            or "консолидирован" in normalized and "codex" in normalized and "hermes" in normalized):
        return intent(
            "consolidated_decision_request",
            mode="request_only",
            target_agents=["codex", "hermes"],
            workflow="consolidated_decision",
            confidence=0.95,
            safety_class="request_gated",
        )

    # Full Stack / strategic engineering delivery request.
    if any(p in normalized for p in [
        "full stack",
        "full-stack",
        "engineering delivery",
        "полный стек",
        "инженерная доставка",
    ]):
        return intent(
            "full_stack_engineering_delivery_request",
            mode="request_only",
            horizon="strategic",
            target_agents=["logi", "architect", "repairman", "traini", "poli"],
            workflow="supervised_full_stack_delivery",
            confidence=0.94,
            safety_class="request_gated",
        )
    if any(p in normalized for p in [
        "проверь взаимодействие",
        "проверь agent interaction",
        "inspect interaction",
        "analyze agent interaction",
    ]):
        return intent(
            "full_stack_engineering_delivery_request",
            mode="request_only",
            horizon="strategic",
            target_agents=["logi", "architect", "repairman", "traini"],
            workflow="supervised_full_stack_delivery",
            confidence=0.93,
            safety_class="request_gated",
        )
    if any(p in normalized for p in [
        "разработай архитектуру",
        "develop architecture",
        "design the architecture",
    ]):
        return intent(
            "full_stack_engineering_delivery_request",
            mode="request_only",
            horizon="strategic",
            target_agents=["logi", "architect"],
            workflow="supervised_full_stack_delivery",
            confidence=0.92,
            safety_class="request_gated",
        )

    # Views.
    day_patterns = [
        "show me today's plan",
        "what are we doing today",
        "today's plan",
        "show daily plan",
        "what is planned today",
        "what are the priorities today",
        "покажи план на сегодня",
        "что у нас сегодня по плану",
        "план на сегодня",
        "какие задачи сегодня",
        "что запланировано на сегодня",
    ]
    if any(p in normalized for p in day_patterns):
        return intent("plan_view", horizon="day", mode="read_only", confidence=0.97, safety_class="read_only")

    if any(p in normalized for p in [
        "what is the next strategic action",
        "why is this the next action",
        "что следующее по стратегическому плану",
    ]):
        return intent("next_actions_view", mode="read_only", confidence=0.95, safety_class="read_only")

    if any(p in normalized for p in [
        "what is the current active strategic plan",
        "current active strategic plan",
        "show active strategic plan",
        "какой текущий активный стратегический план",
        "покажи активный стратегический план",
    ]):
        return intent("active_strategic_plan_view", horizon="strategic", mode="read_only", confidence=0.97, safety_class="read_only")

    if any(p in normalized for p in [
        "strategic plan view",
        "show strategic plan",
        "покажи стратегический план",
    ]):
        return intent("strategic_plan_view", horizon="strategic", mode="read_only", confidence=0.95, safety_class="read_only")

    if any(p in normalized for p in [
        "refresh strategic plan",
        "prepare strategic alignment plan",
        "обнови стратегический план",
        "подготовь стратегический план",
    ]):
        return intent("strategic_plan_refresh", horizon="strategic", mode="request_only", confidence=0.95, safety_class="read_only")

    if any(p in normalized for p in [
        "prepare the strategic alignment execution package",
        "prepare strategic execution package",
        "подготовь пакет исполнения стратегического выравнивания",
        "подготовь стратегический пакет исполнения",
    ]):
        return intent("strategic_execution_package_prepare", horizon="strategic", mode="request_only", confidence=0.97, safety_class="read_only")

    if any(p in normalized for p in [
        "project pulse status",
        "show project pulse",
        "статус project pulse",
        "покажи project pulse",
    ]):
        return intent("project_pulse_view", mode="read_only", confidence=0.95, safety_class="read_only")

    if any(p in normalized for p in [
        "change stack summary",
        "show recent project changes",
        "сводка стека изменений",
        "покажи последние изменения проекта",
    ]):
        return intent("change_stack_view", mode="read_only", confidence=0.95, safety_class="read_only")

    if any(p in normalized for p in [
        "show week plan", "what is planned this week", "show this week's priorities", "покажи план на неделю"
    ]):
        return intent("plan_view", horizon="week", mode="read_only", confidence=0.95, safety_class="read_only")
    if "month" in normalized or "месяц" in normalized:
        if "plan" in normalized or "план" in normalized:
            return intent("plan_view", horizon="month", mode="read_only", confidence=0.9, safety_class="read_only")
    if "strategic" in normalized or "стратег" in normalized:
        if "plan" in normalized or "план" in normalized:
            return intent("strategic_plan_view", horizon="strategic", mode="read_only", confidence=0.9, safety_class="read_only")

    if "blocked" in normalized or "заблок" in normalized:
        return intent("blocked_view", mode="read_only", confidence=0.95, safety_class="read_only")
    if "approval" in normalized or "подтвержд" in normalized:
        return intent("approvals_view", mode="read_only", confidence=0.95, safety_class="read_only")
    if "chains are not closed" in normalized or "цепоч" in normalized and "не закры" in normalized:
        return intent("chain_status_view", mode="read_only", confidence=0.92, safety_class="read_only")
    if "what should we do next" in normalized or "что делать дальше" in normalized:
        return intent("next_actions_view", mode="read_only", confidence=0.9, safety_class="read_only")
    if "current project status" in normalized or "текущий статус проекта" in normalized:
        return intent("status_view", mode="read_only", confidence=0.9, safety_class="read_only")
    if any(p in normalized for p in [
        "what is the current strategic orchestration status",
        "is logi reality-grounded",
        "show me strategic orchestration status",
        "what is the project status",
        "where are we strategically",
        "какой сейчас стратегический статус",
        "где мы сейчас по стратегическому плану",
        "почему нельзя включить full reality-grounded",
    ]):
        return intent("status_view", mode="read_only", confidence=0.95, safety_class="read_only")
    if any(p in normalized for p in [
        "what blocks full reality-grounded promotion",
        "какие проверки не пройдены",
    ]):
        return intent("promotion_blockers_view", mode="read_only", confidence=0.95, safety_class="read_only")
    if any(p in normalized for p in [
        "what known failures exist",
        "какие failures сейчас известны",
        "блокируют ли failures текущую работу",
    ]):
        return intent("known_failures_view", mode="read_only", confidence=0.95, safety_class="read_only")

    # Slash compatibility mapping.
    if normalized == "/plan day":
        return intent("plan_view", horizon="day", mode="read_only", confidence=0.99, safety_class="read_only")
    if normalized == "/plan week":
        return intent("plan_view", horizon="week", mode="read_only", confidence=0.99, safety_class="read_only")
    if normalized == "/plan month":
        return intent("plan_view", horizon="month", mode="read_only", confidence=0.99, safety_class="read_only")
    if normalized == "/plan strategic":
        return intent("strategic_plan_view", horizon="strategic", mode="read_only", confidence=0.99, safety_class="read_only")
    if normalized == "/blocked":
        return intent("blocked_view", mode="read_only", confidence=0.99, safety_class="read_only")
    if normalized == "/approvals":
        return intent("approvals_view", mode="read_only", confidence=0.99, safety_class="read_only")
    if normalized == "/chain_status":
        return intent("chain_status_view", mode="read_only", confidence=0.99, safety_class="read_only")
    if normalized == "/next_actions":
        return intent("next_actions_view", mode="read_only", confidence=0.99, safety_class="read_only")

    return intent("unknown", confidence=0.25, safety_class="unknown", response_style="clarify")
