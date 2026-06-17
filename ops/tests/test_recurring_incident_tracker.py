"""10 required tests for the recurring incident tracking system.

Tests:
  1. One raw endpoint-refused event → no Telegram alert
  2. Endpoint refused repaired once → no alert, history updated
  3. Endpoint refused repaired 5 times in 7d → RECURRING_REPAIRED_ESCALATION
  4. Repaired recurring issue creates training case (recurring_repaired type)
  5. Repair failed after 5 attempts → REPAIR_FAILED_ESCALATION raised
  6. Chronic incident creates external teacher review package
  7. Repeated alerts respect cooldown (second call within window → suppressed)
  8. Fingerprints normalise variable timestamps and paths
  9. Unrelated incidents do not merge into same fingerprint
 10. slot120 not used as teacher/judge in chronic review packages
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_tracker(tmp_path):
    from ops.argus.recurring_incident_tracker import RecurringIncidentTracker
    return RecurringIncidentTracker(root=tmp_path / "recurring")


@pytest.fixture()
def tmp_ledger(tmp_path):
    from ops.argus.repair_ledger import RepairLedger
    return RepairLedger(root=tmp_path / "recurring")


@pytest.fixture()
def tmp_export_dir(tmp_path):
    return tmp_path / "traini_exports"


@pytest.fixture()
def tmp_pkg_root(tmp_path):
    return tmp_path / "chronic_reviews"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _endpoint_refused_fp():
    from ops.argus.recurring_incident_tracker import make_fingerprint
    return make_fingerprint(
        component="repairman_api",
        task="slot32_gateway",
        symptom_class="endpoint_refused",
        endpoint="/repair",
        error_type="ConnectionRefused",
        subsystem="http_client",
    )


def _record_n_repaired(tracker, fingerprint: str, n: int, days_ago: float = 0.0) -> None:
    base_ts = time.time() - days_ago * 86_400
    for i in range(n):
        tracker.record_event(
            fingerprint,
            ts=base_ts + i * 60,
            repair_status="REPAIRED",
            downtime_sec=30.0,
            repair_attempts=1,
        )


# ── Test 1: one raw event → no Telegram alert ─────────────────────────────────

def test_single_raw_event_no_alert(tmp_tracker):
    fp = _endpoint_refused_fp()
    tmp_tracker.record_event(fp, repair_status="NONE")

    levels = tmp_tracker.evaluate_thresholds(fp)
    assert not any(
        l in levels for l in ["RECURRENCE_WARN", "CHRONIC_INCIDENT", "STRUCTURAL_PROBLEM",
                               "REPAIR_FAILED_ESCALATION", "RECURRING_REPAIRED_ESCALATION"]
    ), f"Unexpected escalation on single event: {levels}"

    assert not tmp_tracker.should_alert(fp), "Single raw event must not trigger alert"


# ── Test 2: one repaired event → no alert, history updated ────────────────────

def test_single_repair_no_alert_history_updated(tmp_tracker):
    fp = _endpoint_refused_fp()
    history = tmp_tracker.record_event(fp, repair_status="REPAIRED", downtime_sec=45.0)

    assert history["repaired_count"] == 1
    assert history["total_events"] == 1
    assert history["total_downtime_sec"] == 45.0

    assert not tmp_tracker.should_alert(fp), "Single repaired event must not trigger alert"


# ── Test 3: 5 repaired events in 7d → RECURRING_REPAIRED_ESCALATION ───────────

def test_five_repairs_in_7d_triggers_recurring_repaired_escalation(tmp_tracker):
    fp = _endpoint_refused_fp()
    _record_n_repaired(tmp_tracker, fp, n=5)

    levels = tmp_tracker.evaluate_thresholds(fp)
    assert "RECURRING_REPAIRED_ESCALATION" in levels, (
        f"Expected RECURRING_REPAIRED_ESCALATION after 5 repairs in 7d, got: {levels}"
    )


# ── Test 4: repaired recurring issue creates training case ────────────────────

def test_recurring_repaired_creates_training_case(tmp_tracker, tmp_export_dir):
    from ops.argus.incident_training_exporter import export_recurring_repaired_case

    fp = _endpoint_refused_fp()
    _record_n_repaired(tmp_tracker, fp, n=5)
    history = tmp_tracker.get_history(fp)

    export_path = export_recurring_repaired_case(
        fingerprint=fp,
        history=history,
        repair_timeline=[],
        export_dir=tmp_export_dir,
    )

    assert export_path.exists(), "Export file must be created"
    case = json.loads(export_path.read_text())
    assert case["case_type"] == "recurring_repaired_incident"
    assert case["slot_target"] == "32"
    assert case["future_slot_target"] == "14"
    assert case["metadata"]["no_slot120"] is True
    # slot_target must not be 120; "no_slot120" key itself is the safety declaration (not a violation)
    assert str(case.get("slot_target")) != "120"
    assert case.get("future_slot_target") != "120"


# ── Test 5: repair failed 5 times → REPAIR_FAILED_ESCALATION ─────────────────

def test_repair_failed_triggers_escalation(tmp_tracker):
    fp = _endpoint_refused_fp()
    for _ in range(5):
        tmp_tracker.record_event(fp, repair_status="REPAIR_FAILED")

    levels = tmp_tracker.evaluate_thresholds(fp)
    assert "REPAIR_FAILED_ESCALATION" in levels, (
        f"Expected REPAIR_FAILED_ESCALATION after 5 failed repairs, got: {levels}"
    )


# ── Test 6: chronic incident creates external teacher package ─────────────────

def test_chronic_incident_creates_review_package(tmp_tracker, tmp_pkg_root):
    from ops.argus.chronic_review_package import create_chronic_review_package

    fp = _endpoint_refused_fp()
    _record_n_repaired(tmp_tracker, fp, n=5)
    history = tmp_tracker.get_history(fp)

    artifacts = create_chronic_review_package(
        fingerprint=fp,
        history=history,
        repair_timeline=[],
        escalation_levels=["CHRONIC_INCIDENT", "RECURRING_REPAIRED_ESCALATION"],
        package_root=tmp_pkg_root,
    )

    assert artifacts["markdown_report"].exists()
    assert artifacts["json_dossier"].exists()
    assert artifacts["teacher_prompt"].exists()
    assert artifacts["training_case"].exists()

    dossier = json.loads(artifacts["json_dossier"].read_text())
    policy = dossier.get("teacher_slot_policy", {})
    assert "slot120" not in policy.get("allowed", []), (
        "slot120 must not appear in allowed teacher slots"
    )
    assert any("120" in s for s in policy.get("forbidden", [])), (
        "slot120 must be listed as forbidden"
    )

    case_text = artifacts["training_case"].read_text()
    case = json.loads(case_text.splitlines()[0])
    assert case["case_type"] == "chronic_root_cause_analysis"
    assert case["metadata"]["no_slot120"] is True


# ── Test 7: cooldown suppresses repeated alerts ───────────────────────────────

def test_alert_cooldown_suppresses_repeat(tmp_tracker):
    fp = _endpoint_refused_fp()
    _record_n_repaired(tmp_tracker, fp, n=5)

    # First check: should alert (no cooldown recorded yet)
    assert tmp_tracker.should_alert(fp, cooldown_sec=3600)

    # Record that alert was sent
    tmp_tracker.record_alert_sent(fp)

    # Immediately after: should be suppressed
    assert not tmp_tracker.should_alert(fp, cooldown_sec=3600), (
        "Alert must be suppressed within cooldown window"
    )


# ── Test 8: fingerprints normalise variable parts ─────────────────────────────

def test_fingerprint_normalises_variable_parts():
    from ops.argus.recurring_incident_tracker import make_fingerprint

    fp1 = make_fingerprint(
        component="repairman_api",
        task="slot32_gateway",
        symptom_class="endpoint_refused",
        endpoint="/repair?ts=2026-05-19T21:34:00Z&pid=12345",
        error_type="ConnectionRefused port=8010",
        subsystem="http_client",
    )
    fp2 = make_fingerprint(
        component="repairman_api",
        task="slot32_gateway",
        symptom_class="endpoint_refused",
        endpoint="/repair?ts=2026-05-20T08:12:55Z&pid=99999",
        error_type="ConnectionRefused port=8010",
        subsystem="http_client",
    )
    assert fp1 == fp2, (
        "Fingerprints with different timestamps/PIDs but same logical failure must match"
    )


# ── Test 9: unrelated incidents do not merge ──────────────────────────────────

def test_unrelated_incidents_have_different_fingerprints():
    from ops.argus.recurring_incident_tracker import make_fingerprint

    fp_a = make_fingerprint(
        component="repairman_api",
        task="slot32_gateway",
        symptom_class="endpoint_refused",
        endpoint="/repair",
        error_type="ConnectionRefused",
        subsystem="http_client",
    )
    fp_b = make_fingerprint(
        component="omi_quality_gate",
        task="ft_prepare_chain_run",
        symptom_class="container_exit_137",
        endpoint="docker",
        error_type="OOMKilled",
        subsystem="docker_runtime",
    )

    assert fp_a != fp_b, "Unrelated incidents must not share the same fingerprint"


# ── Test 10: slot120 never used as teacher/judge in chronic review ─────────────

def test_slot120_not_in_chronic_review_artifacts(tmp_tracker, tmp_pkg_root):
    from ops.argus.chronic_review_package import create_chronic_review_package

    fp = _endpoint_refused_fp()
    _record_n_repaired(tmp_tracker, fp, n=5)
    history = tmp_tracker.get_history(fp)

    artifacts = create_chronic_review_package(
        fingerprint=fp,
        history=history,
        repair_timeline=[],
        escalation_levels=["CHRONIC_INCIDENT"],
        root_cause_hypotheses=["Config drift after each restart"],
        recommended_fixes=["Persist config in volume mount"],
        package_root=tmp_pkg_root,
    )

    # The teacher prompt and markdown report are allowed to *mention* slot120 as excluded.
    # The invariant is that slot120 must NOT appear as an allowed/recommended model.
    dossier = json.loads(artifacts["json_dossier"].read_text())
    policy = dossier.get("teacher_slot_policy", {})
    assert "slot120" not in policy.get("allowed", []), (
        "slot120 must not appear in allowed teacher slots"
    )
    assert any("120" in s for s in policy.get("forbidden", [])), (
        "slot120 must be listed as forbidden in teacher_slot_policy"
    )
    assert str(dossier.get("slot_target", "")) != "120", "slot_target must not be 120"

    training_case = json.loads(artifacts["training_case"].read_text().splitlines()[0])
    assert training_case["metadata"]["no_slot120"] is True
    assert training_case["slot_target"] == "32"

    # Confirm allowed slots are mentioned in the teacher prompt
    teacher_text = artifacts["teacher_prompt"].read_text()
    assert "slot32" in teacher_text.lower() or "slot14" in teacher_text.lower(), (
        "Teacher prompt must reference allowed teacher slots"
    )
