"""Snapshot helpers for model data preparation outputs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logi.model_data_quality import hash_file


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_dataset_snapshot(
    certification_id: str,
    output_dir: Path,
    files: list[Path],
    slot14_records: dict[str, int],
    slot32_records: dict[str, int],
    category_coverage: dict[str, Any],
    quality_summary: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    hashes = {p.name: hash_file(p) for p in files}
    snapshot = {
        "snapshot_id": f"model_data_snapshot_{certification_id}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files": [
            "docs/AIMS_GSTACK_INTEGRATION_STATUS.md",
            "ops/agents/agent_skill_registry.yaml",
            "aims_workspace/model_tuning_readiness/certifications/model_tuning_readiness_chain_v1_20260514_145843",
        ],
        "output_files": [str(p.relative_to(output_dir)) if p.is_relative_to(output_dir) else str(p) for p in files],
        "record_counts": {
            "slot14": slot14_records,
            "slot32": slot32_records,
        },
        "accepted_counts": {
            "slot14_gold": slot14_records.get("accepted_gold", 0),
            "slot14_dpo": slot14_records.get("accepted_dpo", 0),
            "slot32_eval": slot32_records.get("accepted_eval", 0),
            "slot32_training": slot32_records.get("accepted_training", 0),
        },
        "rejected_counts": {
            "slot14": slot14_records.get("rejected", 0),
            "slot32": slot32_records.get("rejected", 0),
        },
        "file_hashes": hashes,
        "category_coverage": category_coverage,
        "missing_topic_coverage": quality_summary.get("missing_topic_coverage", {}),
        "quality_summary": quality_summary,
        "secret_scan_status": quality_summary.get("secret_scan_status", "UNKNOWN"),
        "dedupe_status": quality_summary.get("dedupe_status", "UNKNOWN"),
        "safe_for_eval": True,
        "safe_for_tuning_smoke": slot14_records.get("accepted_gold", 0) + slot14_records.get("accepted_dpo", 0) >= 50 and slot32_records.get("accepted_training", 0) > 0,
        "safe_for_full_tuning": False,
        "recommended_next_action": "Feed dataset snapshot into Logi/Traini readiness cycle; keep full tuning and promotion blocked until later readiness approval.",
    }
    return snapshot, hashes
