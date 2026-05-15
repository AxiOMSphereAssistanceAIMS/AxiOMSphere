#!/usr/bin/env python3
"""Audit the AIMS Code Skills Curriculum against the registry and policy rules."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "ops/skills/code_skill_registry.yaml"
COMMANDS_DIR = ROOT / ".claude/commands"
AUDIT_DIR = ROOT / "aims_workspace/audit"

REQUIRED_FIELDS = {"command", "slot", "role", "purpose", "output_contract", "safety_level"}
VALID_SLOTS = {"32", "120"}
VALID_SAFETY = {"low", "medium", "high"}
HIGH_SAFETY_SKILLS = {"code_audit", "code_migrate"}
REQUIRES_VALIDATION_SAFETY = {"medium", "high"}


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_registry() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def check_skill_file_exists(command: str) -> bool:
    fname = command.lstrip("/").replace("-", "-") + ".md"
    return (COMMANDS_DIR / fname).exists()


def check_forbidden_in_skill_file(command: str, forbidden: list[str]) -> list[str]:
    fname = command.lstrip("/") + ".md"
    path = COMMANDS_DIR / fname
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").lower()
    hits = []
    critical_forbidden = [
        "model_promotion", "cleanup_apply", "ollama_rm", "docker_compose_down",
        "edit_secrets", "rm_rf", "git_reset_hard",
    ]
    for f in critical_forbidden:
        token = f.replace("_", " ").lower()
        if token in text and "forbidden" not in text[:text.find(token)][-100:]:
            hits.append(f)
    return hits


def audit_skill(name: str, skill: dict[str, Any], forbidden: list[str]) -> dict[str, Any]:
    issues: list[str] = []

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in skill:
            issues.append(f"missing required field: {field}")

    # Slot validity
    slot = str(skill.get("slot", ""))
    if slot not in VALID_SLOTS:
        issues.append(f"invalid slot: {slot!r} (must be 32 or 120)")

    # output_contract
    if skill.get("output_contract") != "structured_json":
        issues.append("output_contract must be structured_json")

    # safety_level validity
    safety = skill.get("safety_level", "")
    if safety not in VALID_SAFETY:
        issues.append(f"invalid safety_level: {safety!r}")

    # High-safety skills must be marked high
    if name in HIGH_SAFETY_SKILLS and safety != "high":
        issues.append(f"{name} must have safety_level=high")

    # Dangerous skills (medium+) must have requires_validation
    # Exemptions: read-only/findings-only skills that never write production state
    if safety in REQUIRES_VALIDATION_SAFETY and not skill.get("requires_validation"):
        if name not in {"code_debug", "code_deploy", "code_model_slot", "code_audit"}:
            issues.append(f"safety_level={safety} but requires_validation not set")

    # Slot 120 skills: check execution_note
    if slot == "120" and not skill.get("execution_note"):
        issues.append("slot 120 skill missing execution_note")

    # Skill file exists
    command = skill.get("command", "")
    if not check_skill_file_exists(command):
        issues.append(f"skill file not found: .claude/commands/{command.lstrip('/')}.md")

    # Forbidden action leakage into skill file
    leaks = check_forbidden_in_skill_file(command, forbidden)
    if leaks:
        issues.append(f"forbidden action tokens found in skill file: {leaks}")

    return {
        "skill": name,
        "command": command,
        "slot": slot,
        "safety_level": safety,
        "requires_validation": skill.get("requires_validation", False),
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit AIMS Code Skills Curriculum v1")
    ap.add_argument("--json", action="store_true", help="Output JSON only")
    args = ap.parse_args()

    reg = load_registry()
    skills = reg.get("skills", {})
    forbidden = reg.get("global_forbidden_actions", [])

    results = []
    for name, skill in skills.items():
        results.append(audit_skill(name, skill, forbidden))

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    overall = "PASS" if failed == 0 else "FAIL"

    report: dict[str, Any] = {
        "report_type": "code_skill_audit",
        "curriculum": reg.get("curriculum", "AIMS Code Skills Curriculum v1"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "overall": overall,
        "skills": results,
        "global_forbidden_actions": forbidden,
    }

    # Write output files
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = now_ts()
    json_path = AUDIT_DIR / f"code_skill_audit_{ts}.json"
    md_path = AUDIT_DIR / f"code_skill_audit_{ts}.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_lines = [
        "# AIMS Code Skills Audit",
        f"\nGenerated: {report['generated_at']}  ",
        f"Overall: **{overall}** — {passed}/{len(results)} passed\n",
        "| Skill | Command | Slot | Safety | Status | Issues |",
        "|-------|---------|------|--------|--------|--------|",
    ]
    for r in results:
        issues_str = "; ".join(r["issues"]) if r["issues"] else "—"
        md_lines.append(
            f"| {r['skill']} | `{r['command']}` | {r['slot']} | {r['safety_level']} | {r['status']} | {issues_str} |"
        )
    md_lines += ["", f"## Forbidden Actions ({len(forbidden)})", ""]
    for f in forbidden:
        md_lines.append(f"- `{f}`")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Audit: {overall}  ({passed}/{len(results)} passed)")
        for r in results:
            marker = "OK" if r["status"] == "PASS" else "FAIL"
            print(f"  [{marker}] {r['skill']:20s}  slot={r['slot']}  safety={r['safety_level']}")
            for issue in r["issues"]:
                print(f"         ! {issue}")
        print(f"\nJSON:  {json_path}")
        print(f"MD:    {md_path}")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
