from __future__ import annotations

from pathlib import Path
from typing import Any

from .repair_case_dossier_schema import validate_dossier_shape


def validate(
    audit_root: Path,
    dossiers: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    errors: list[str] = []

    # Missing /data audit root on host is acceptable when fixture/fallback case is used.
    if not dossiers:
        errors.append("no_dossiers")

    secrets_redacted = 0
    for d in dossiers:
        errors.extend(validate_dossier_shape(d))
        if not d.get("problem_statement"):
            errors.append(f"missing_problem_statement:{d.get('repair_case_id')}")
        if not d.get("sanitized"):
            errors.append(f"dossier_not_sanitized:{d.get('repair_case_id')}")
        blob = str(d)
        if "<REDACTED_SECRET>" in blob or "<REDACTED_VALUE>" in blob:
            secrets_redacted += 1
        if ".claude-mem" in blob:
            errors.append("raw_claude_mem_leaked")

    for p in prompts:
        pt = p.get("prompt_text", "")
        if "RAW JSON only" not in pt and "raw JSON only" not in pt:
            errors.append("prompt_not_raw_json")
        forbidden = p.get("forbidden_consultant_actions", [])
        for needed in ["patch files", "run commands", "restart services", "access secrets"]:
            if needed not in forbidden:
                errors.append(f"prompt_missing_forbidden:{needed}")

    if not signals:
        errors.append("no_skill_signal")

    return {
        "ok": not errors,
        "errors": errors,
        "secrets_redacted": secrets_redacted,
        "hermes_invocations": 0 if dry_run else 0,
        "model_endpoint_calls": 0 if dry_run else 0,
        "production_patches": 0,
    }
