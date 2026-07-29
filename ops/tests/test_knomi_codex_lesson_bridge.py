from __future__ import annotations

import json
from pathlib import Path

from ops.knomi.codex_lesson_bridge import probe_session_card, publish_capture_failure_card, publish_session_card
from ops.knomi.common import iter_text_chunks


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_verified_card_is_retrievable_without_raw_transcript(tmp_path: Path) -> None:
    sid = "session_1"
    lesson = tmp_path / "lessons/report.json"
    action = tmp_path / "actions/decision.json"
    _write(lesson, {"lesson_id": "lesson_1", "lessons": [{"rule": "retry boundedly"}]})
    _write(action, {"decision": "SKILL_MODIFICATION_CANDIDATE"})
    ledger = tmp_path / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    row = {
        "source_session_id": sid,
        "lesson_id": "lesson_1",
        "lesson_report_path": str(lesson.relative_to(tmp_path)),
        "action_decision_path": str(action.relative_to(tmp_path)),
        "final_status": "PASSED",
        "direct_training_allowed": False,
    }
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = publish_session_card(tmp_path, sid)
    assert result["status"] == "PASS"
    assert probe_session_card(tmp_path, sid) == {
        "retrievable": True,
        "session_id": sid,
        "matching_chunks": 1,
        "raw_transcript_indexed": False,
    }


def test_terminal_capture_failure_becomes_retrievable_prevention_card(tmp_path: Path) -> None:
    result = publish_capture_failure_card(
        tmp_path,
        "failed_capture",
        validation_report={
            "lifecycle_state": "QUARANTINED_INCOMPLETE",
            "missing_files": ["learning_material_handoff.json"],
        },
        final_status={
            "status": "FAILED",
            "failure_class": "CAPTURE_WRAPPER",
            "reason": "stale capture",
            "direct_training_allowed": False,
        },
    )
    assert result["status"] == "PASS"
    assert result["probe"]["retrievable"] is True
    card = json.loads(Path(result["card_path"]).read_text(encoding="utf-8"))
    assert card["direct_training_allowed"] is False
    assert card["raw_transcript_included"] is False


def test_unverified_compact_card_is_not_a_knomi_source(tmp_path: Path) -> None:
    card_dir = tmp_path / "aims_workspace/knowledge/codex_lessons"
    card_dir.mkdir(parents=True)
    _write(
        card_dir / "sid.json",
        {
            "schema": "aims.knomi.codex_lesson_card.v2",
            "status": "VALIDATED_COMPACT",
            "session_id": "sid",
            "title": "staged",
            "kind": "codex_lesson",
            "content": {"root_cause": "bounded"},
            "source_hashes": {"source_sha256": "0" * 64},
            "verified_at_utc": None,
            "raw_transcript_included": False,
            "direct_training_allowed": False,
        },
    )
    assert not any(chunk.kind == "codex_lesson" for chunk in iter_text_chunks(explicit_workspace=tmp_path))


def test_transcript_marker_in_card_metadata_is_rejected(tmp_path: Path) -> None:
    card_dir = tmp_path / "aims_workspace/knowledge/codex_lessons"
    card_dir.mkdir(parents=True)
    _write(
        card_dir / "sid.json",
        {
            "schema": "aims.knomi.codex_lesson_card.v2",
            "status": "BENEFIT_VERIFIED",
            "session_id": "sid",
            "title": "BEGIN RAW TRANSCRIPT secret",
            "kind": "codex_lesson",
            "content": {"root_cause": "bounded"},
            "source_hashes": {"source_sha256": "0" * 64},
            "verified_at_utc": "2026-07-29T10:00:00+00:00",
            "raw_transcript_included": False,
            "direct_training_allowed": False,
        },
    )
    assert not any(chunk.kind == "codex_lesson" for chunk in iter_text_chunks(explicit_workspace=tmp_path))


def test_oversized_source_hash_map_is_rejected(tmp_path: Path) -> None:
    card_dir = tmp_path / "aims_workspace/knowledge/codex_lessons"
    card_dir.mkdir(parents=True)
    _write(
        card_dir / "sid.json",
        {
            "schema": "aims.knomi.codex_lesson_card.v2",
            "status": "BENEFIT_VERIFIED",
            "session_id": "sid",
            "title": "bounded",
            "kind": "codex_lesson",
            "content": {"root_cause": "bounded"},
            "source_hashes": {f"source_{index}_sha256": "0" * 64 for index in range(17)},
            "verified_at_utc": "2026-07-29T10:00:00+00:00",
            "raw_transcript_included": False,
            "direct_training_allowed": False,
        },
    )
    assert not any(chunk.kind == "codex_lesson" for chunk in iter_text_chunks(explicit_workspace=tmp_path))


def test_transcript_like_content_is_rejected_from_compact_card(tmp_path: Path) -> None:
    sid = "malicious"
    lesson = tmp_path / "lessons/report.json"
    action = tmp_path / "actions/decision.json"
    _write(
        lesson,
        {
            "lesson_id": "lesson_bad",
            "lessons": [
                {
                    "lesson_id": "lesson_bad",
                    "observed_problem": "BEGIN RAW TRANSCRIPT\nsecret material",
                    "root_cause": "bad",
                }
            ],
        },
    )
    _write(action, {"decision": "SKILL_MODIFICATION_CANDIDATE"})
    ledger = tmp_path / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "source_session_id": sid,
                "lesson_id": "lesson_bad",
                "lesson_report_path": str(lesson.relative_to(tmp_path)),
                "action_decision_path": str(action.relative_to(tmp_path)),
                "final_status": "PASSED",
                "direct_training_allowed": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = publish_session_card(tmp_path, sid)
    assert result["status"] == "BLOCKED"
    assert "transcript-like" in result["reason"]
