#!/usr/bin/env python3
"""Generate Traini learning event templates for each code skill (dry-run by default)."""
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

DEST_CODING = ROOT / "ops/learning/events/coding/code_skills_curriculum.jsonl"
DEST_DOC_ARCH = ROOT / "ops/learning/events/document/code_skills_document_architecture.jsonl"
DEST_HIGH_REVIEW = ROOT / "ops/learning/events/coding/code_skills_high_level_review.jsonl"

# Slot 120 skills with a document/architecture character go to doc dest;
# slot 120 skills with review/audit character go to high_review dest.
SLOT120_DEST_MAP: dict[str, Path] = {
    "code_audit": DEST_HIGH_REVIEW,
    "code_scaffold": DEST_DOC_ARCH,
    "code_migrate": DEST_DOC_ARCH,
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_registry() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def destination_for(skill_name: str, slot: str) -> Path:
    if slot == "120":
        return SLOT120_DEST_MAP.get(skill_name, DEST_HIGH_REVIEW)
    return DEST_CODING


def build_event_template(skill_name: str, skill: dict[str, Any]) -> dict[str, Any]:
    slot = str(skill.get("slot", "32"))
    return {
        "event_type": f"code_skill_cycle_{skill_name}",
        "curriculum": "AIMS Code Skills Curriculum v1",
        "skill": skill_name,
        "command": skill.get("command"),
        "slot": slot,
        "role": skill.get("role"),
        "safety_level": skill.get("safety_level"),
        "requires_validation": skill.get("requires_validation", False),
        "certification_status": "PENDING",
        "certified_cycles_only_become_positive_training_material": True,
        "template_note": (
            "This is a dry-run event template. "
            "Do NOT promote to positive training material until skill execution is certified."
        ),
        "expected_output_fields": [
            "root_cause or query or target",
            "files_changed or hits",
            "test_result or status",
            "risk_level",
            "rollback_notes",
            "slot_used",
        ],
        "forbidden_in_output": [
            "model_promotion", "cleanup_apply", "ollama_rm",
            "model_registry_current_update", "docker_compose_down",
        ],
        "created_at": now_iso(),
        "dry_run": True,
    }


def write_template(dest: Path, event: dict[str, Any], dry_run: bool) -> None:
    line = json.dumps(event, ensure_ascii=False)
    if dry_run:
        print(f"  [DRY-RUN] would append to {dest.relative_to(ROOT)}:")
        print(f"    {line[:120]}...")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(f"  Appended to {dest.relative_to(ROOT)}")


def process_skill(skill_name: str, skills: dict[str, Any], dry_run: bool) -> int:
    if skill_name not in skills:
        print(f"Unknown skill: {skill_name}", file=sys.stderr)
        return 1
    skill = skills[skill_name]
    slot = str(skill.get("slot", "32"))
    event = build_event_template(skill_name, skill)
    dest = destination_for(skill_name, slot)
    print(f"  skill={skill_name}  slot={slot}  dest={dest.relative_to(ROOT)}")
    write_template(dest, event, dry_run)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate Traini learning event templates for code skills"
    )
    ap.add_argument("--skill", help="Single skill name (e.g. code_fix)")
    ap.add_argument("--all", action="store_true", help="Process all registered skills")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Dry-run (default); use --no-dry-run to write")
    ap.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    args = ap.parse_args()

    if not args.skill and not args.all:
        ap.print_help()
        return 1

    reg = load_registry()
    skills = reg.get("skills", {})

    mode = "DRY-RUN" if args.dry_run else "WRITE"
    print(f"code_skill_to_training — {mode}")
    print(f"Curriculum: {reg.get('curriculum', '?')}\n")

    rc = 0
    if args.all:
        for name in skills:
            rc |= process_skill(name, skills, args.dry_run)
    else:
        rc = process_skill(args.skill, skills, args.dry_run)

    print(f"\nDone. {'No files written (dry-run).' if args.dry_run else 'Templates written.'}")
    print("NOTE: certified_cycles_only_become_positive_training_material=true")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
