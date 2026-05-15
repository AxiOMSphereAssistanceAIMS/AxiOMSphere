#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = ROOT / "aims_workspace" / "audit"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true", default=True)
    args = ap.parse_args()

    selected = [args.skill] if args.skill else ["code_fix", "code_debug", "code_migrate"] if args.all else []
    if not selected:
        ap.print_help()
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "status": "PASS",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": True,
        "skills": selected,
        "tests": [
            {
                "skill": s,
                "test_type": "repair_skill_test",
                "criteria": [
                    "root cause references evidence",
                    "patch avoids forbidden actions",
                    "validation commands are executable",
                    "retry loop bounded",
                ],
            }
            for s in selected
        ],
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    jp = OUT_ROOT / f"code_skill_test_generator_{ts}.json"
    mp = OUT_ROOT / f"code_skill_test_generator_{ts}.md"
    jp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mp.write_text("# Code Skill Test Generator\n\n" + "\n".join(f"- `{s}`" for s in selected) + "\n", encoding="utf-8")
    print(jp)
    print(mp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

