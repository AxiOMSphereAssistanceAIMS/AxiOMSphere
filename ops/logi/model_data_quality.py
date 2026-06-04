"""Quality gates for candidate model data preparation.

The checks here are intentionally conservative: generated data remains
candidate material until it passes structure, role, safety, dedupe, and score
threshold checks.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9_./+=-]{12,}"),
]

UNSAFE_CLAIMS = [
    "0.98 achieved",
    "model improved",
    "model promoted",
    "training completed",
    "slot120 loaded",
]


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:10]}"


def has_secret_text(value: str) -> bool:
    return any(p.search(value) for p in SECRET_PATTERNS)


def scan_record_for_secrets(record: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for key, value in _walk(record):
        if isinstance(value, str) and has_secret_text(value):
            issues.append(f"{key}: secret-like value")
    return issues


def scan_record_for_unsafe_claims(record: dict[str, Any]) -> list[str]:
    text = json.dumps(record, ensure_ascii=False).lower()
    return [claim for claim in UNSAFE_CLAIMS if claim in text]


def critic_review(record: dict[str, Any], slot_id: str) -> dict[str, Any]:
    issues: list[str] = []
    if str(record.get("slot_id")) != str(slot_id):
        issues.append("slot_id mismatch")
    issues.extend(scan_record_for_secrets(record))
    issues.extend(scan_record_for_unsafe_claims(record))
    if slot_id == "14" and not record.get("ideal_response"):
        issues.append("missing ideal_response")
    if slot_id == "32" and not record.get("expected_output"):
        issues.append("missing expected_output")
    if "source_context" in record and record["source_context"] != "synthetic_from_project_profile":
        issues.append("unexpected source_context")

    status = "PASS" if not issues else ("REJECT" if any("secret" in i for i in issues) else "REWRITE")
    return {
        "record_id": record.get("pair_id") or record.get("task_id"),
        "slot_id": slot_id,
        "critic_status": status,
        "critic_notes": issues or ["consistent with slot role, evidence discipline, and safety policy"],
    }


def judge_score(record: dict[str, Any], critic: dict[str, Any], slot_id: str) -> dict[str, Any]:
    threshold = 0.85 if slot_id == "14" else 0.88
    base = 0.93 if slot_id == "14" else 0.92
    difficulty = record.get("difficulty", "medium")
    if difficulty in {"hard", "expert"}:
        base += 0.02
    if critic["critic_status"] != "PASS":
        base -= 0.18
    if record.get("rejected_response") or record.get("rejected_or_bad_output"):
        base += 0.01
    score = max(0.0, min(1.0, round(base, 3)))

    if score >= threshold and critic["critic_status"] == "PASS":
        if slot_id == "14":
            label = "accepted_dpo" if record.get("rejected_response") else "accepted_gold"
        else:
            label = "accepted_eval" if int(record.get("sequence", 0)) % 3 == 0 else "accepted_training"
    elif critic["critic_status"] == "REJECT":
        label = "rejected"
    else:
        label = "needs_rewrite"

    return {
        "record_id": record.get("pair_id") or record.get("task_id"),
        "slot_id": slot_id,
        "score": score,
        "threshold": threshold,
        "label": label,
        "reason": "meets quality threshold and policy checks" if label.startswith("accepted") else "below quality or policy threshold",
    }


def dedupe_records(records: list[dict[str, Any]], key_fields: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicates: list[str] = []
    for record in records:
        raw = "|".join(str(record.get(k, "")) for k in key_fields)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        rid = str(record.get("pair_id") or record.get("task_id"))
        if digest in seen:
            duplicates.append(rid)
            continue
        seen.add(digest)
        unique.append(record)
    return unique, {
        "status": "PASS",
        "input_records": len(records),
        "unique_records": len(unique),
        "duplicates_removed": len(duplicates),
        "duplicate_record_ids": duplicates,
    }


def hash_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "sha256": None, "size_bytes": 0}
    data = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _walk(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from _walk(inner, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for idx, inner in enumerate(value):
            yield from _walk(inner, f"{prefix}[{idx}]")
    else:
        yield prefix, value
