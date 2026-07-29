from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ops.logi.artifact_lifecycle import artifact_id, lifecycle_for_session, status_path
from ops.logi.raw_material_clearance import apply_decision, decide_session, run_clearance


def _benefit_evidence(root: Path, checks: dict[str, bool]) -> dict[str, dict[str, str]]:
    support = root / "support.json"
    support.write_text('{"status":"PASS"}', encoding="utf-8")
    support_hash = hashlib.sha256(support.read_bytes()).hexdigest()
    path = root / "probe.json"
    path.write_text(
        json.dumps(
            {
                "schema": "aims.closed_loop.benefit_probe.v1",
                "source_session_id": "sid",
                "checks": checks,
                "supporting_evidence": {
                    name: {"status": "PASS", "path": str(support), "sha256": support_hash}
                    for name in checks
                },
            }
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {name: {"status": "PASS", "path": str(path), "sha256": digest} for name in checks}


def _session_tree(tmp_path: Path, session_id: str = "sid") -> tuple[Path, Path, Path, Path, Path, Path]:
    raw = tmp_path / "raw" / session_id
    validation = tmp_path / "validation" / session_id
    ingestion = tmp_path / "ingestion" / session_id
    lessons = tmp_path / "lessons" / session_id
    actions = tmp_path / "actions" / session_id
    pair = tmp_path / "pair" / "lesson_x"
    raw.mkdir(parents=True)
    validation.mkdir(parents=True)
    ingestion.mkdir(parents=True)
    lessons.mkdir(parents=True)
    actions.mkdir(parents=True)
    pair.mkdir(parents=True)
    (raw / "session_manifest.json").write_text("{}", encoding="utf-8")
    (raw / "final_status.json").write_text("{}", encoding="utf-8")
    (raw / "learning_material_handoff.json").write_text("{}", encoding="utf-8")
    (raw / "stdout.log").write_text("log", encoding="utf-8")
    (raw / "stderr.log").write_text("log", encoding="utf-8")
    (validation / "validation_report.json").write_text('{"lifecycle_state":"VALIDATED_RAW"}', encoding="utf-8")
    (validation / "validated_raw_marker.json").write_text("{}", encoding="utf-8")
    (ingestion / "ingestion_status.json").write_text('{"status":"RAW_PROCESSED"}', encoding="utf-8")
    (lessons / "lesson_extraction_report.json").write_text('{"lesson_id":"lesson_x","lessons":[{"lesson_id":"lesson_x"}]}', encoding="utf-8")
    (lessons / "lesson_quality_score.json").write_text("{}", encoding="utf-8")
    (actions / "lesson_action_decision.json").write_text('{"decision":"BOTH_SKILL_AND_PAIR_CANDIDATES"}', encoding="utf-8")
    (pair / "candidate_manifest.json").write_text('{"source_session_id":"sid","source_lesson_id":"lesson_x","target_slot":"slot32","target_pool":"slot32_pair_pool","raw_material_only":true,"direct_training_allowed":false}', encoding="utf-8")
    for name in ("contamination_report.json", "dedup_report.json", "slot_router_report.json", "dataset_gate_report.json", "final_status.json"):
        (pair / name).write_text('{"status":"PASS"}', encoding="utf-8")
    return raw, validation, ingestion, lessons, actions, pair


def test_clearance_blocks_missing_ledger(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="FAIL",
        dry_run=True,
    )
    assert decision.eligible is False
    assert "ledger replay failed" in decision.reasons


def test_clearance_blocks_missing_lesson(tmp_path: Path) -> None:
    raw, validation, ingestion, _, actions, _ = _session_tree(tmp_path)
    (tmp_path / "lessons" / "sid" / "lesson_extraction_report.json").unlink()
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=tmp_path / "lessons",
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=True,
    )
    assert decision.eligible is False
    assert "lesson missing" in decision.reasons


def test_clearance_blocks_missing_action(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, _, _ = _session_tree(tmp_path)
    (tmp_path / "actions" / "sid" / "lesson_action_decision.json").unlink()
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=tmp_path / "actions",
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=True,
    )
    assert decision.eligible is False
    assert "action decision missing" in decision.reasons


def test_clearance_blocks_missing_pair_gate_report(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, pair = _session_tree(tmp_path)
    (pair / "dataset_gate_report.json").unlink()
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=True,
    )
    assert decision.eligible is False
    assert "pair gate trace incomplete" in decision.reasons


def test_clearance_marks_processed_session_eligible(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=True,
    )
    assert decision.eligible is True
    assert decision.status == "RAW_CLEARANCE_ELIGIBLE"
    assert decision.direct_training_allowed is False


def test_clearance_dry_run_deletes_nothing(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=True,
    )
    result = apply_decision(decision, archive_root=tmp_path / "archive", mode="dry-run")
    assert raw.exists()
    assert result["archived_paths"] == []
    assert result["cleared_paths"] == []


def test_clearance_dry_run_is_non_mutating(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=True,
    )
    result = apply_decision(decision, archive_root=tmp_path / "archive", mode="dry-run")
    assert not Path(result["retained_manifest_path"]).exists()
    assert not Path(result["clearance_manifest_path"]).exists()
    assert result["mutation_performed"] is False


def test_clearance_never_allows_direct_training(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=True,
    )
    assert decision.direct_training_allowed is False


def test_clearance_run_summary_counts(tmp_path: Path, monkeypatch) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    monkeypatch.setattr("ops.logi.raw_material_clearance.replay_traceability_ledger", lambda *args, **kwargs: {"status": "PASS", "chains": []})
    report = run_clearance(
        argparse.Namespace(
            raw_root=tmp_path / "raw",
            validation_root=tmp_path / "validation",
            ingestion_root=tmp_path / "ingestion",
            lessons_root=tmp_path / "lessons",
            actions_root=tmp_path / "actions",
            pair_root=tmp_path / "pair",
            ledger=tmp_path / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl",
            archive_root=tmp_path / "archive",
            out=tmp_path / "out",
            mode="dry-run",
            deletion_confirmation=None,
        )
    )
    assert report["status"] == "PASS"
    assert report["raw_clearance_eligible_count"] == 1


def test_clearance_requires_verified_lifecycle_before_quarantine(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=False,
    )
    result = apply_decision(
        decision,
        archive_root=tmp_path / "archive",
        mode="archive",
        lifecycle_root=tmp_path,
    )
    assert result["lifecycle_ready"] is False
    assert result["mutation_performed"] is True


def test_clearance_quarantines_verified_material_but_does_not_delete_without_confirmation(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    source_path = "aims_workspace/logi/raw_material/codex_sessions/sid"
    checks = {"ledger_replay": True, "traini_gate_trace": True, "knomi_retrieval": True, "raw_transcript_excluded_from_knomi": True}
    lifecycle_for_session(
        tmp_path,
        session_id="sid",
        source_path=source_path,
        owner="Logi",
        evidence=["lesson.json"],
        benefit="retrievable",
        result="applied",
        benefit_checks=checks,
        benefit_evidence=_benefit_evidence(tmp_path, checks),
    )
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=False,
    )
    result = apply_decision(
        decision,
        archive_root=tmp_path / "archive",
        mode="clear",
        lifecycle_root=tmp_path,
    )
    assert raw.exists()
    assert result["raw_quarantined"] is True
    assert result["deletion_confirmation_valid"] is False


def test_clearance_deletes_only_after_168h_and_exact_confirmation(tmp_path: Path) -> None:
    raw, validation, ingestion, lessons, actions, _ = _session_tree(tmp_path)
    source_path = "aims_workspace/logi/raw_material/codex_sessions/sid"
    checks = {"ledger_replay": True, "traini_gate_trace": True, "knomi_retrieval": True, "raw_transcript_excluded_from_knomi": True}
    lifecycle_for_session(
        tmp_path,
        session_id="sid",
        source_path=source_path,
        owner="Logi",
        evidence=["lesson.json"],
        benefit="retrievable",
        result="applied",
        benefit_checks=checks,
        benefit_evidence=_benefit_evidence(tmp_path, checks),
        quarantined=True,
    )
    life_path = status_path(tmp_path, artifact_id("sid", source_path))
    life = json.loads(life_path.read_text())
    life["quarantine_at"] = (datetime.now(timezone.utc) - timedelta(hours=169)).isoformat()
    life["retention_hours"] = 1  # Must not weaken the Codex 168-hour minimum.
    life_path.write_text(json.dumps(life), encoding="utf-8")
    decision = decide_session(
        raw,
        validation_root=validation.parent,
        ingestion_root=ingestion.parent,
        lessons_root=lessons.parent,
        actions_root=actions.parent,
        pair_root=tmp_path / "pair",
        ledger_replay_status="PASS",
        dry_run=False,
    )
    wrong = apply_decision(
        decision,
        archive_root=tmp_path / "archive",
        mode="clear",
        lifecycle_root=tmp_path,
        deletion_confirmation={
            "approved": True,
            "action": "DELETE_QUARANTINED_RAW",
            "exact_targets": [str((tmp_path / "wrong").resolve())],
        },
    )
    assert wrong["raw_deleted"] is False
    result = apply_decision(
        decision,
        archive_root=tmp_path / "archive",
        mode="clear",
        lifecycle_root=tmp_path,
        deletion_confirmation={
            "approved": True,
            "action": "DELETE_QUARANTINED_RAW",
            "exact_targets": [str(raw.resolve())],
        },
    )
    assert result["raw_deleted"] is True
    assert not raw.exists()
