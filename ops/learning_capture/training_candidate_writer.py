from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def normalize_training_candidate(entry: dict[str, Any]) -> dict[str, Any]:
    data = dict(entry)
    data["approved_for_training"] = False
    data["requires_human_approval"] = True
    data.setdefault("source", "agent_action_capture")
    data.setdefault("failure_modes", [])
    return data


def append_training_candidate(
    entry: dict[str, Any],
    *,
    output_root: str | Path,
    axi_ft_root: str | Path = "aims_workspace/axi_ft_log",
) -> dict[str, str]:
    data = normalize_training_candidate(entry)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    learning_log = output / "training_candidates.jsonl"
    axi_root = Path(axi_ft_root)
    axi_log = axi_root / "training_candidates.jsonl"
    line = json.dumps(data, ensure_ascii=False)
    with learning_log.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    result = {"learning_capture": str(learning_log), "axi_ft_log": str(axi_log)}
    try:
        axi_root.mkdir(parents=True, exist_ok=True)
        with axi_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        error_log = output / "training_candidate_mirror_errors.jsonl"
        error = {
            "case_id": data.get("case_id"),
            "target": str(axi_log),
            "error": f"{exc.__class__.__name__}: {exc}",
            "approved_for_training": False,
            "requires_human_approval": True,
        }
        with error_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(error, ensure_ascii=False) + "\n")
        result["axi_ft_log_error"] = str(error_log)
    return result
