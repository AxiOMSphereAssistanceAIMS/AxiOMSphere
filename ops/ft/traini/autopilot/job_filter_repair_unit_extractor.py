"""Extract bounded Slot32 repair units from job-filter recovery evidence."""
from __future__ import annotations

import json
from typing import Any

from .learning_unit import LearningUnit


def extract_job_filter_repair_unit(record: Any) -> LearningUnit | None:
    metadata = getattr(record, "metadata", {}) or {}
    if not str(getattr(record, "record_id", "")).startswith("job_filter_recovery:"):
        return None
    payload: dict[str, Any] = {}
    try:
        value = json.loads(str(getattr(record, "content", "")))
        payload = value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        payload = {}
    # Raw wrapper metadata keeps bounded routing fields outside the payload,
    # while job-filter evidence stores them at the payload root.
    source = {**payload, **metadata}
    evidence_dir = str(source.get("evidence_dir") or "")
    files = source.get("files_changed") if isinstance(source.get("files_changed"), list) else []
    problem = str(source.get("probable_root_cause") or source.get("failure_type") or "job-filter recovery incident")[:2400]
    repair = str(source.get("repair_summary") or "")[:2400]
    verification = all(str(source.get(key) or "").upper() == "PASS" for key in ("repair_summary", "validation_status", "regression_status", "watchdog_status", "redis_requeue_status"))
    status = "PASS" if verification else "UNKNOWN"
    unit_type = "MODEL_LEARNING_UNIT" if verification and evidence_dir and files else "HOLD_EVIDENCE_INCOMPLETE"
    task_family = "runtime_repair"
    bounded_input = f"job-filter incident: {problem}"
    bounded_target = f"Apply the verified repair and validate the affected paths. Files: {', '.join(str(x) for x in files[:20])}. Outcome: {repair}"
    source_id = str(getattr(record, "record_id", ""))
    source_version = str(metadata.get("source_version") or "v1")
    unit_id = LearningUnit.deterministic_id(source_id, source_version, unit_type, bounded_input, bounded_target, "job-filter-repair-v1")
    evidence_hashes = [str(source.get(key)) for key in ("source_truth_hash", "event_hash", "model_output_hash") if source.get(key)]
    return LearningUnit(
        learning_unit_id=unit_id,
        source_id=source_id,
        source_version=source_version,
        raw_source_hash=str(getattr(record, "checksum", "")),
        evidence_hashes=evidence_hashes,
        unit_type=unit_type,
        problem=problem,
        observed_evidence=f"evidence_dir={evidence_dir}; validation={source.get('validation_status')}; regression={source.get('regression_status')}",
        root_cause=problem,
        accepted_decision=repair,
        verification_status=status,
        verification_reference=evidence_dir,
        bounded_input=bounded_input,
        bounded_target=bounded_target,
        task_family=task_family,
        extraction_version="job-filter-repair-v1",
        route_candidates=["MODEL_TRAINING_SLOT32"] if verification else ["HOLD"],
        excluded_content=["full_source_json", "transcript_body", "private_scratchpad", "container_log_body"],
        producer_mode=None,
    )
