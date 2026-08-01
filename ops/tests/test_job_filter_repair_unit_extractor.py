from __future__ import annotations

from types import SimpleNamespace

from ops.ft.traini.autopilot.job_filter_repair_unit_extractor import extract_job_filter_repair_unit


def _record(**updates):
    metadata = {"evidence_dir": "/evidence", "files_changed": ["ops/job_filter_recovery.py"], "probable_root_cause": "source transient", "repair_summary": "PASS", "validation_status": "PASS", "regression_status": "PASS", "watchdog_status": "PASS", "redis_requeue_status": "PASS", "source_truth_hash": "s", "event_hash": "e", "model_output_hash": "m"}
    metadata.update(updates)
    return SimpleNamespace(record_id="job_filter_recovery:incident:repair", checksum="raw", metadata=metadata)


def test_verified_repair_becomes_bounded_slot32_unit():
    unit = extract_job_filter_repair_unit(_record())
    assert unit is not None
    assert unit.unit_type == "MODEL_LEARNING_UNIT"
    assert unit.route_candidates == ["MODEL_TRAINING_SLOT32"]
    assert "container_log_body" in unit.excluded_content


def test_failed_verification_is_held():
    unit = extract_job_filter_repair_unit(_record(watchdog_status="FAIL"))
    assert unit is not None
    assert unit.unit_type == "HOLD_EVIDENCE_INCOMPLETE"
    assert unit.route_candidates == ["HOLD"]
