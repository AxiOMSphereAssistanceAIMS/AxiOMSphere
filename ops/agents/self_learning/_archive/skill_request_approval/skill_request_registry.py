from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .skill_request_schema import SkillRequest


class SkillRequestRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.pending_path = self.root / "pending_skill_requests.json"
        self.decisions_path = self.root / "skill_request_decisions.json"

    def load_requests_from_file(self, path: Path) -> list[dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return list(data.get("requests", []))
        if isinstance(data, list):
            return data
        raise ValueError("Unsupported requests fixture format")

    def save_pending(self, requests: list[dict[str, Any]]) -> None:
        self.pending_path.write_text(
            json.dumps({"requests": requests}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_decisions(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions_path.write_text(
            json.dumps({"decisions": decisions}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_pending(self) -> list[dict[str, Any]]:
        if not self.pending_path.exists():
            return []
        data = json.loads(self.pending_path.read_text(encoding="utf-8"))
        return list(data.get("requests", []))

    def ensure_defaults(self, req: dict[str, Any]) -> dict[str, Any]:
        # manual default merge for dataclass fields
        out: dict[str, Any] = {}
        for k, field_obj in SkillRequest.__dataclass_fields__.items():
            if k in req:
                out[k] = req[k]
            else:
                if field_obj.default_factory is not None and str(field_obj.default_factory) != '<dataclasses._MISSING_TYPE object at 0x0>':
                    try:
                        out[k] = field_obj.default_factory()
                    except Exception:
                        out[k] = field_obj.default
                else:
                    out[k] = field_obj.default
        return out
