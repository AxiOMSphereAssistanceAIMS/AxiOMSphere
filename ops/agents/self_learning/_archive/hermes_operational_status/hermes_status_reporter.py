from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hermes_current_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# Hermes Current Status",
        "",
        f"- status: {status.get('current_status')}",
        f"- helping: {status.get('helping_agent')}",
        f"- audit_id: {status.get('active_audit_id')}",
        f"- current task: {status.get('current_task_summary')}",
        f"- active skill: {status.get('active_skill_name')}",
        f"- skill stage: {status.get('active_skill_stage')}",
        f"- latest request: {status.get('latest_assistance_request_id')}",
        f"- blockers: {', '.join(status.get('blockers', [])) if status.get('blockers') else '-'}",
        f"- next action: {status.get('next_action')}",
    ]
    (out_dir / "hermes_current_status.md").write_text("\n".join(md), encoding="utf-8")

    ru = [
        "# Hermes status (Telegram-ready)",
        "",
        f"- Чем занят Hermes: {status.get('current_task_summary')}",
        f"- Какому агенту помогает: {status.get('helping_agent')}",
        f"- Какой audit_id / repair case: {status.get('active_audit_id') or status.get('active_repair_case_id')}",
        f"- Какой skill: {status.get('active_skill_name')}",
        f"- Какая стадия: {status.get('active_skill_stage')}",
        f"- Что уже сделано: {', '.join(status.get('work_completed', [])) if status.get('work_completed') else '-'}",
        f"- Что в работе: {', '.join(status.get('work_in_progress', [])) if status.get('work_in_progress') else '-'}",
        f"- Блокеры: {', '.join(status.get('blockers', [])) if status.get('blockers') else '-'}",
        f"- Следующее действие: {status.get('next_action')}",
        f"- Что нужно от пользователя: {', '.join(status.get('pending_user_decisions', [])) if status.get('pending_user_decisions') else '-'}",
    ]
    (out_dir / "hermes_current_status_for_telegram.md").write_text("\n".join(ru), encoding="utf-8")


def write_matrices(out_dir: Path, status: dict[str, Any], active_requests: list[dict[str, Any]]) -> None:
    (out_dir / "hermes_active_requests.json").write_text(json.dumps(active_requests, indent=2, ensure_ascii=False), encoding="utf-8")
    help_matrix = {
        "helping_agent": status.get("helping_agent"),
        "active_target_agent": status.get("active_target_agent"),
        "help_type": status.get("help_type"),
        "current_status": status.get("current_status"),
    }
    (out_dir / "hermes_agent_help_matrix.json").write_text(json.dumps(help_matrix, indent=2, ensure_ascii=False), encoding="utf-8")

    skill_matrix = {
        "active_skill_id": status.get("active_skill_id"),
        "active_skill_name": status.get("active_skill_name"),
        "active_skill_stage": status.get("active_skill_stage"),
        "active_skill_origin": status.get("active_skill_origin"),
        "active_skill_owner_after_adoption": status.get("active_skill_owner_after_adoption"),
    }
    (out_dir / "hermes_skill_activity_matrix.json").write_text(json.dumps(skill_matrix, indent=2, ensure_ascii=False), encoding="utf-8")

    report = {
        "current_status": status,
        "active_requests_count": len(active_requests),
        "next_action": status.get("next_action"),
    }
    (out_dir / "hermes_status_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "hermes_status_report.md").write_text(
        "# Hermes Status Report\n\n"
        f"- current_status: {status.get('current_status')}\n"
        f"- helping_agent: {status.get('helping_agent')}\n"
        f"- active_audit_id: {status.get('active_audit_id')}\n"
        f"- active_skill: {status.get('active_skill_name')}\n"
        f"- active_skill_stage: {status.get('active_skill_stage')}\n"
        f"- next_action: {status.get('next_action')}\n",
        encoding="utf-8",
    )
