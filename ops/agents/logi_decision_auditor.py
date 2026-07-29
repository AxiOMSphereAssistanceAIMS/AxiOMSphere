"""Deterministic decision audit for Logi repair notifications.

This is the policy boundary between diagnosis and a user-facing approval
request.  It deliberately does not apply changes.  It decides whether a
repair is safe to execute inside the declared project strategy, must wait for
human approval, or is blocked because the request is incomplete.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ops.repairman.repair_policy import classify_repair_type


@dataclass
class DecisionAudit:
    decision: str  # AUTO_REPAIR | HUMAN_APPROVAL | BLOCKED | NO_REPAIR
    risk_level: str
    human_approval_required: bool
    strategy_change: bool
    repair_type: str
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    human_message_ru: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _request(env: Any) -> dict[str, Any]:
    try:
        payload = json.loads(env.description or "{}")
    except Exception:
        return {}
    request = payload.get("request", payload)
    return request if isinstance(request, dict) else {}


def audit_repair_decision(env: Any, analysis: dict[str, Any],
                          repairman_result: dict[str, Any] | None = None) -> DecisionAudit:
    """Audit a proposed repair before it becomes a notification or action."""
    if analysis.get("classification") != "repair_needed":
        return DecisionAudit("NO_REPAIR", "none", False, False, "", ["repair is not requested"])

    request = _request(env)
    repair_type = str(
        analysis.get("repair_type")
        or (getattr(env, "params", {}) or {}).get("repair_type")
        or request.get("repair_type")
        or request.get("task_type")
        or ""
    ).strip()
    level = str(
        analysis.get("requested_repair_level")
        or request.get("requested_repair_level")
        or ""
    ).upper()
    strategy_change = bool(
        analysis.get("strategy_change")
        or request.get("strategy_change")
        or analysis.get("changes_strategy")
    )
    restorative = analysis.get("restorative", request.get("restorative", True)) is True
    has_validation = bool(analysis.get("verification_commands") or request.get("success_criteria"))
    has_rollback = bool(analysis.get("rollback_command") or request.get("rollback_requirement"))

    if not repair_type:
        return DecisionAudit(
            "BLOCKED", "unknown", True, strategy_change, "",
            ["repair_type/capability is missing"], ["cannot classify requested action"],
            "Ремонт заблокирован: не указаны тип ремонта и требуемая capability; "
            "нужна заявка на новый или обновлённый скилл.",
        )
    if strategy_change or level in {"L3_PRODUCTION_REPAIR_APPROVAL_REQUIRED", "L4_MODEL_ROUTING_OR_TRAINING_APPROVAL_REQUIRED"}:
        return DecisionAudit(
            "HUMAN_APPROVAL", "high", True, True, repair_type,
            ["изменяется стратегия или production/model policy"],
            ["изменение может повлиять на другие задачи и rollback boundary"],
            "Нужно подтверждение человека: предлагаемое действие выходит за рамки "
            "текущей стратегии проекта.",
        )

    policy = classify_repair_type(repair_type, {"description": env.description})
    if policy.forbidden:
        return DecisionAudit(
            "BLOCKED", "forbidden", True, strategy_change, repair_type,
            [policy.reason], ["action is forbidden by repair policy"],
            "Ремонт заблокирован политикой безопасности.",
        )
    if not restorative or not has_validation or not has_rollback:
        missing = []
        if not restorative:
            missing.append("restorative=true")
        if not has_validation:
            missing.append("verification/success criteria")
        if not has_rollback:
            missing.append("rollback plan")
        return DecisionAudit(
            "HUMAN_APPROVAL", "moderate", True, strategy_change, repair_type,
            ["repair packet is incomplete: " + ", ".join(missing)],
            ["insufficient evidence for unattended repair"],
            "Нужно подтверждение человека: в заявке не хватает доказательств "
            "безопасного восстановления (" + ", ".join(missing) + ").",
        )
    if policy.safe_to_auto_repair and not policy.requires_poli_approval:
        return DecisionAudit(
            "AUTO_REPAIR", "low", False, False, repair_type,
            [policy.reason, "восстановление не меняет стратегию проекта"], [],
            "Аудитор разрешил безопасное восстановление в рамках действующей стратегии; "
            "дополнительное human approval не требуется.",
        )
    return DecisionAudit(
        "HUMAN_APPROVAL", "moderate", True, strategy_change, repair_type,
        [policy.reason], ["policy class is not auto-allowed"],
        "Нужно подтверждение человека: действие не входит в безопасный auto-repair allowlist.",
    )


__all__ = ["DecisionAudit", "audit_repair_decision"]
