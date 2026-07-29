from __future__ import annotations

import json

from ops.logi.codex_learning_traceability import (
    append_traceability_record,
    create_skill_change_candidate,
    create_traini_pair_candidate,
    decide_lesson_action,
    extract_lesson_from_ingested_session,
    ingest_validated_codex_package,
    replay_traceability_ledger,
    run_e2e_traceability_for_session,
    scan_codex_raw_packages,
    validate_codex_package,
)
from ops.tests.codex_learning_test_helpers import write_codex_package


def test_logi_ingestion_includes_codex_validated_raw_source(tmp_path):
    session_dir = write_codex_package(tmp_path)
    validate_codex_package(session_dir, tmp_path)
    status = ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    assert status["status"] == "RAW_PROCESSED"


def test_logi_ingestion_ignores_unvalidated_codex_raw_package(tmp_path):
    write_codex_package(tmp_path)
    status = ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    assert status["status"] == "RAW_REJECTED_INCOMPLETE"


def test_logi_ingestion_rejects_quarantined_package(tmp_path):
    write_codex_package(tmp_path, complete=False, status="RUNNING")
    scan_codex_raw_packages(tmp_path, stale_running_seconds=0)
    status = ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    assert status["status"] == "RAW_QUARANTINED"


def test_logi_ingestion_writes_session_trace(tmp_path):
    session_dir = write_codex_package(tmp_path)
    validate_codex_package(session_dir, tmp_path)
    status = ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    assert (tmp_path / status["ingestion_status_path"]).exists()


def test_logi_ingestion_does_not_admit_training_data(tmp_path):
    session_dir = write_codex_package(tmp_path)
    validate_codex_package(session_dir, tmp_path)
    status = ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    assert status["direct_training_allowed"] is False


def test_codex_lesson_pair_candidate_routes_to_slot32_when_coding_repair(tmp_path):
    session_dir = write_codex_package(tmp_path)
    validate_codex_package(session_dir, tmp_path)
    ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    lesson = extract_lesson_from_ingested_session("logi_codex_fixture", tmp_path)
    lesson["affected_component"] = "coding_repair"
    pair = create_traini_pair_candidate(lesson, decide_lesson_action(lesson, tmp_path), tmp_path)
    report = json.loads((tmp_path / pair["slot_router_report_path"]).read_text())
    assert report["proposed_slot"] == "slot32"


def test_codex_lesson_pair_candidate_routes_to_agent_skill_pool_when_process_skill(tmp_path):
    result = _pair_for_lesson(tmp_path, affected_component="codex_logi_learning_traceability")
    assert result["target_pool"] == "agent_skill_learning_pool"


def test_codex_lesson_pair_candidate_rejects_slot14_coding_only(tmp_path):
    result = _pair_for_lesson(tmp_path, affected_component="coding_repair", slot="slot14")
    contamination = json.loads((tmp_path / result["contamination_report_path"]).read_text())
    assert contamination["status"] == "FAIL_SLOT_MISMATCH"
    slot_report = json.loads((tmp_path / result["slot_router_report_path"]).read_text())
    assert slot_report["proposed_slot"] == "slot14"


def test_codex_lesson_pair_candidate_rejects_slot120_under_750_training_admission(tmp_path):
    result = _pair_for_lesson(tmp_path, affected_component="reasoning_repair", slot="slot120")
    dataset = json.loads((tmp_path / result["dataset_gate_report_path"]).read_text())
    assert dataset["reason"] == "SLOT120_BLOCKED_UNTIL_750_VERIFIED_PAIRS"
    assert dataset["training_scheduled"] is False


def test_slot_router_report_links_candidate_lesson_session(tmp_path):
    result = _pair_for_lesson(tmp_path)
    report = json.loads((tmp_path / result["slot_router_report_path"]).read_text())
    assert report["candidate_id"] == result["pair_candidate_id"]
    assert report["source_lesson_id"] == result["source_lesson_id"]
    assert report["source_session_id"] == result["source_session_id"]


def test_traceability_ledger_is_append_only_and_idempotent_per_session(tmp_path):
    result = _complete_chain(tmp_path)
    ledger = tmp_path / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    before = ledger.read_text()
    append_traceability_record(
        session_id="logi_codex_fixture",
        lesson=result["lesson"],
        decision=result["decision"],
        skill=result["skill"],
        pair=result["pair"],
        workspace=tmp_path,
    )
    assert ledger.read_text().startswith(before)
    # Append-only means prior rows are never rewritten; replaying the same
    # source session must not create a duplicate terminal chain.
    assert len(ledger.read_text().splitlines()) == 1


def test_traceability_ledger_links_raw_to_lesson_to_action(tmp_path):
    result = _complete_chain(tmp_path)
    row = result["ledger"]
    assert row["raw_package_path"]
    assert row["lesson_id"] == result["lesson"]["lesson_id"]
    assert row["action_decision_path"]


def test_traceability_ledger_replay_reconstructs_chain(tmp_path):
    _complete_chain(tmp_path)
    replay = replay_traceability_ledger(tmp_path)
    assert replay["status"] == "PASS"


def test_traceability_ledger_rejects_missing_artifact_paths(tmp_path):
    result = _complete_chain(tmp_path)
    (tmp_path / result["ledger"]["lesson_report_path"]).unlink()
    replay = replay_traceability_ledger(tmp_path)
    assert replay["status"] == "FAIL"


def test_e2e_traceability_fixture_proves_no_training(tmp_path):
    write_codex_package(tmp_path)
    write_codex_package(tmp_path, "logi_codex_incomplete", complete=False, status="RUNNING")
    scan = scan_codex_raw_packages(tmp_path, stale_running_seconds=0)
    result = run_e2e_traceability_for_session("logi_codex_fixture", tmp_path)
    assert scan["quarantined"] == 1
    assert result["status"] == "PASSED"
    assert result["training_scheduled"] is False
    assert result["direct_training_allowed"] is False


def _pair_for_lesson(tmp_path, *, affected_component="codex_logi_learning_traceability", slot="slot32"):
    session_dir = write_codex_package(tmp_path)
    validate_codex_package(session_dir, tmp_path)
    ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    lesson = extract_lesson_from_ingested_session("logi_codex_fixture", tmp_path)
    lesson["affected_component"] = affected_component
    lesson["slot_relevance"] = slot
    decision = decide_lesson_action(lesson, tmp_path)
    return create_traini_pair_candidate(lesson, decision, tmp_path)


def _complete_chain(tmp_path):
    session_dir = write_codex_package(tmp_path)
    validate_codex_package(session_dir, tmp_path)
    ingest_validated_codex_package("logi_codex_fixture", tmp_path)
    lesson = extract_lesson_from_ingested_session("logi_codex_fixture", tmp_path)
    decision = decide_lesson_action(lesson, tmp_path)
    skill = create_skill_change_candidate(lesson, decision, tmp_path)
    pair = create_traini_pair_candidate(lesson, decision, tmp_path)
    ledger = append_traceability_record(session_id="logi_codex_fixture", lesson=lesson, decision=decision, skill=skill, pair=pair, workspace=tmp_path)
    return {"lesson": lesson, "decision": decision, "skill": skill, "pair": pair, "ledger": ledger}
