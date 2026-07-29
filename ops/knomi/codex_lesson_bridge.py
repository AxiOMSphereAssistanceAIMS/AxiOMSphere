#!/usr/bin/env python3
"""Publish verified Codex lessons to Knomi without indexing raw transcripts."""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ops.knomi.common import iter_text_chunks, knowledge_root, validate_compact_card
from ops.logi.codex_learning_traceability import replay_traceability_ledger


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _ledger_rows(root: Path) -> list[dict[str, Any]]:
    path = root / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _write_validated_card(root: Path, session_id: str, card: dict[str, Any]) -> dict[str, Any]:
    valid, reason = validate_compact_card(card)
    if not valid:
        return {"status": "BLOCKED", "reason": reason, "session_id": session_id}
    target = knowledge_root(root) / "codex_lessons" / f"{session_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    staged = _read(target)
    staged_valid, staged_reason = validate_compact_card(staged)
    if not staged_valid or staged.get("status") != "VALIDATED_COMPACT":
        target.unlink(missing_ok=True)
        return {"status": "BLOCKED", "reason": f"staged compact validation failed: {staged_reason}", "session_id": session_id}
    if probe_session_card(root, session_id)["retrievable"]:
        target.unlink(missing_ok=True)
        return {"status": "BLOCKED", "reason": "unverified staged card leaked into Knomi", "session_id": session_id}
    card["status"] = "BENEFIT_VERIFIED"
    card["verified_at_utc"] = datetime.now(timezone.utc).isoformat()
    target.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    probe = probe_session_card(root, session_id)
    return {"status": "PASS" if probe["retrievable"] else "BLOCKED", "session_id": session_id, "card_path": str(target), "probe": probe}


def publish_session_card(root: Path, session_id: str) -> dict[str, Any]:
    """Write an idempotent compact card only for a replayable ledger chain."""
    replay = replay_traceability_ledger(root, session_id=session_id)
    if replay.get("status") != "PASS":
        return {"status": "BLOCKED", "reason": "ledger replay failed", "session_id": session_id}
    row = next((r for r in _ledger_rows(root) if r.get("source_session_id") == session_id), None)
    if row is None:
        return {"status": "BLOCKED", "reason": "ledger row missing", "session_id": session_id}
    lesson_path = root / str(row.get("lesson_report_path") or "")
    action_path = root / str(row.get("action_decision_path") or "")
    lesson = _read(lesson_path)
    action = _read(action_path)
    if not lesson or not action:
        return {"status": "BLOCKED", "reason": "lesson/action evidence missing", "session_id": session_id}
    lessons = lesson.get("lessons") or []
    compact_lesson = lessons[0] if lessons and isinstance(lessons[0], dict) else {}
    content_keys = (
        "lesson_id",
        "observed_problem",
        "root_cause",
        "prevention_rule",
        "reusable_lesson",
        "affected_component",
        "applicability_scope",
        "recommended_action",
    )
    card = {
        "schema": "aims.knomi.codex_lesson_card.v2",
        "status": "VALIDATED_COMPACT",
        "session_id": session_id,
        "title": f"Codex lesson {session_id}",
        "kind": "codex_lesson",
        "content": {
            **{key: compact_lesson[key] for key in content_keys if compact_lesson.get(key) is not None},
            "recommended_action": str(action.get("decision") or compact_lesson.get("recommended_action") or ""),
        },
        "source_hashes": {
            "lesson_report_sha256": hashlib.sha256(lesson_path.read_bytes()).hexdigest(),
            "action_decision_sha256": hashlib.sha256(action_path.read_bytes()).hexdigest(),
        },
        "verified_at_utc": None,
        "raw_transcript_included": False,
        "direct_training_allowed": False,
    }
    return _write_validated_card(root, session_id, card)


def publish_capture_failure_card(
    root: Path,
    session_id: str,
    *,
    validation_report: dict[str, Any],
    final_status: dict[str, Any],
) -> dict[str, Any]:
    """Turn a terminal incomplete capture into reusable operational knowledge."""
    if validation_report.get("lifecycle_state") not in {"QUARANTINED_INCOMPLETE", "QUARANTINED_INVALID"}:
        return {"status": "BLOCKED", "reason": "validation is not terminal quarantine", "session_id": session_id}
    if str(final_status.get("status") or "").upper() not in {"FAILED", "COMPLETED"}:
        return {"status": "BLOCKED", "reason": "final status missing", "session_id": session_id}
    card = {
        "schema": "aims.knomi.codex_capture_failure_card.v2",
        "status": "VALIDATED_COMPACT",
        "session_id": session_id,
        "title": f"Codex capture failure {session_id}",
        "kind": "codex_capture_failure",
        "content": {
            "failure_class": str(final_status.get("failure_class") or "INCOMPLETE_CAPTURE"),
            "root_cause": str(final_status.get("reason") or "capture package did not satisfy the required evidence contract"),
            "prevention_rule": "Close stale captures terminally and require the complete wrapper evidence contract before lesson extraction.",
            "disposition": "REJECTED_WITH_OPERATIONAL_LESSON",
            "missing_file_count": len(validation_report.get("missing_files") or []),
            "empty_file_count": len(validation_report.get("empty_files") or []),
        },
        "source_hashes": {
            "validation_report_sha256": hashlib.sha256(
                json.dumps(validation_report, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
            "final_status_sha256": hashlib.sha256(
                json.dumps(final_status, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
        },
        "verified_at_utc": None,
        "raw_transcript_included": False,
        "direct_training_allowed": False,
    }
    return _write_validated_card(root, session_id, card)


def probe_session_card(root: Path, session_id: str) -> dict[str, Any]:
    """Prove the compact lesson is visible to Knomi's source collector."""
    expected = str((knowledge_root(root) / "codex_lessons" / f"{session_id}.json").resolve())
    chunks = iter_text_chunks(explicit_workspace=root)
    matches = [c for c in chunks if str(Path(c.source).resolve()) == expected and session_id in c.text]
    return {
        "retrievable": bool(matches),
        "session_id": session_id,
        "matching_chunks": len(matches),
        "raw_transcript_indexed": any("raw_material/codex_sessions" in c.source for c in chunks),
    }
