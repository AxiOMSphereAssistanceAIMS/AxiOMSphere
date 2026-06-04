"""Dataset snapshot + quality checks for Traini lifecycle."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SourceSpec:
    key: str
    path: Path
    critical: bool = False


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_jsonl(path: Path) -> tuple[int, int, int]:
    total = 0
    malformed = 0
    empty = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            s = ln.strip()
            if not s:
                empty += 1
                continue
            total += 1
            try:
                json.loads(s)
            except Exception:
                malformed += 1
    return total, malformed, empty


def _dup_ratio(path: Path) -> float:
    seen = set()
    total = 0
    dup = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            s = ln.strip()
            if not s:
                continue
            total += 1
            if s in seen:
                dup += 1
            else:
                seen.add(s)
    if total == 0:
        return 0.0
    return dup / float(total)


def _secret_scan_text(path: Path) -> dict[str, Any]:
    pats = ("sk-", "OMNI_TOKEN=", "AIMS_SERVICE_TOKEN=", "BOT")
    hits = []
    text = path.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    for p in pats:
        if p.lower() in low:
            hits.append(p)
    return {"status": "WARN" if hits else "PASS", "hits": hits}


def create_snapshot() -> dict[str, Any]:
    specs = [
        SourceSpec("repair_pairs", ROOT / "aims_workspace/repairman_memory/repairman_pairs_auto.jsonl"),
        SourceSpec("lessons", ROOT / "aims_workspace/repairman_memory/lessons.jsonl"),
        SourceSpec("gold_pairs", ROOT / "aims_workspace/axi_ft_log/gold_pairs.jsonl"),
        SourceSpec("dpo_pairs", ROOT / "aims_workspace/axi_ft_log/dpo_pairs.jsonl"),
    ]
    rows = []
    total_records = 0
    malformed_total = 0
    for s in specs:
        exists = s.path.exists()
        info: dict[str, Any] = {
            "key": s.key,
            "path": str(s.path),
            "exists": exists,
            "critical": s.critical,
            "record_count": 0,
            "malformed_lines": 0,
            "empty_lines": 0,
            "duplicate_ratio": 0.0,
            "sha256": "",
            "modified_time": "",
            "secret_scan": {"status": "SKIP", "hits": []},
        }
        if exists:
            count, malformed, empty = _count_jsonl(s.path)
            info["record_count"] = count
            info["malformed_lines"] = malformed
            info["empty_lines"] = empty
            info["duplicate_ratio"] = round(_dup_ratio(s.path), 4)
            info["sha256"] = _hash_file(s.path)
            info["modified_time"] = datetime.fromtimestamp(s.path.stat().st_mtime, timezone.utc).isoformat()
            info["secret_scan"] = _secret_scan_text(s.path)
            total_records += count
            malformed_total += malformed
        rows.append(info)

    quality_notes = []
    if total_records < 20:
        quality_notes.append("low_record_count")
    if malformed_total > 0:
        quality_notes.append("malformed_lines_present")
    if any(r["secret_scan"]["status"] == "WARN" for r in rows if r["exists"]):
        quality_notes.append("potential_secret_markers_detected")

    safe_for_training = total_records >= 100 and malformed_total == 0 and "potential_secret_markers_detected" not in quality_notes
    recommended_use = "full_tuning" if safe_for_training else ("tuning_smoke" if total_records >= 40 else ("eval_only" if total_records > 0 else "insufficient_data"))

    return {
        "dataset_snapshot_id": f"dss_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "generated_at": _now(),
        "source_paths": rows,
        "exists": {r["key"]: r["exists"] for r in rows},
        "record_counts": {r["key"]: r["record_count"] for r in rows},
        "file_hashes": {r["key"]: r["sha256"] for r in rows if r["exists"]},
        "modified_times": {r["key"]: r["modified_time"] for r in rows if r["exists"]},
        "quality_notes": quality_notes,
        "secret_scan_status": "WARN" if "potential_secret_markers_detected" in quality_notes else "PASS",
        "recommended_use": recommended_use,
        "safe_for_training": safe_for_training,
        "dataset_records_total": total_records,
    }


def quality_classification(snapshot: dict[str, Any]) -> dict[str, Any]:
    total = int(snapshot.get("dataset_records_total", 0))
    notes = list(snapshot.get("quality_notes", []))
    secret_warn = snapshot.get("secret_scan_status") == "WARN"
    malformed = "malformed_lines_present" in notes
    if total == 0:
        status = "INSUFFICIENT_DATA"
    elif secret_warn:
        status = "EVAL_ONLY"
    elif malformed:
        status = "EVAL_ONLY"
    elif total < 40:
        status = "EVAL_ONLY"
    elif total < 100:
        status = "TUNING_SMOKE_READY"
    else:
        status = "FULL_TUNING_READY"
    return {
        "status": status,
        "minimum_records_eval_only": 1,
        "minimum_records_tuning_smoke": 40,
        "minimum_records_full_tuning": 100,
        "total_records": total,
        "notes": notes,
        "safe_for_training": bool(snapshot.get("safe_for_training", False)),
    }

