from __future__ import annotations

from pathlib import Path


def validate(out_dir: Path) -> list[str]:
    errors: list[str] = []
    required = [
        "hermes_current_status.json",
        "hermes_current_status.md",
        "hermes_activity_ledger.jsonl",
        "hermes_active_requests.json",
        "hermes_agent_help_matrix.json",
        "hermes_skill_activity_matrix.json",
        "hermes_status_report.json",
        "hermes_status_report.md",
        "hermes_current_status_for_telegram.md",
    ]
    for f in required:
        if not (out_dir / f).exists():
            errors.append(f"missing:{f}")
    return errors
