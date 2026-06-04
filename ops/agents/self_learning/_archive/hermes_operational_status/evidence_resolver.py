from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def path_exists(path: Path) -> bool:
    return path.exists()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def find_active_skill_adoption_evidence(assist_dir: Path) -> tuple[bool, list[str]]:
    paths = [
        assist_dir / "repairman_active_skill_registry.json",
        assist_dir / "repairman_owner_skill_bindings.json",
        assist_dir / "repairman_adoption_test_results.json",
    ]
    found = [str(p) for p in paths if p.exists()]
    return bool(found), found


def load_rejection_summary(rej_dir: Path) -> dict[str, Any]:
    return read_json(rej_dir / "rejection_summary.json", {}) or {}

