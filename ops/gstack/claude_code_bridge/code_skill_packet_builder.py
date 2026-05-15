#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "ops/skills/code_skill_registry.yaml"
OUT_ROOT = ROOT / "aims_workspace/claude_code_bridge/packets"


def _load() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true", default=True)
    args = ap.parse_args()

    reg = _load()
    skills = reg.get("skills") or {}
    selected = [args.skill] if args.skill else list(skills.keys()) if args.all else []
    if not selected:
        ap.print_help()
        return 1

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ts = Path(__file__).stem + "_" + __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    packet = {
        "packet_type": "code_skill_packet",
        "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "dry_run": True,
        "skills": [],
    }
    for name in selected:
        skill = skills.get(name, {})
        packet["skills"].append(
            {
                "skill": name,
                "slot": skill.get("slot"),
                "role": skill.get("role"),
                "command": skill.get("command"),
                "safety_level": skill.get("safety_level"),
                "requires_validation": skill.get("requires_validation", False),
            }
        )
    jp = OUT_ROOT / f"{ts}.json"
    mp = OUT_ROOT / f"{ts}.md"
    jp.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mp.write_text("# Code Skill Packet\n\n" + "\n".join(f"- `{x['skill']}`" for x in packet["skills"]) + "\n", encoding="utf-8")
    print(jp)
    print(mp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

