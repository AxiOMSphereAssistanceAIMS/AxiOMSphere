import hashlib
from datetime import datetime, timedelta, timezone

from ops.logi.artifact_lifecycle import audit, create, lifecycle_for_session, quarantine_ready, transition


def _evidence(root, checks, source_id):
    support = root / "support.json"
    support.write_text('{"status":"PASS"}', encoding="utf-8")
    support_hash = hashlib.sha256(support.read_bytes()).hexdigest()
    path = root / "probe.json"
    path.write_text(
        __import__("json").dumps(
            {
                "schema": "aims.closed_loop.benefit_probe.v1",
                "source_session_id": source_id,
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


def test_lifecycle_requires_benefit_before_cleanup(tmp_path):
    record = create(tmp_path, source_id="s1", source_path="raw/s1", artifact_type="test", owner="Logi")
    assert record["state"] == "CREATED"
    record = transition(tmp_path, record, "USED", reason="consumed")
    checks = {"ledger_replay": True, "traini_gate_trace": True, "knomi_retrieval": True, "raw_transcript_excluded_from_knomi": True}
    record = transition(tmp_path, record, "BENEFIT_VERIFIED", reason="verified", benefit="lesson extracted", result="skill updated", benefit_checks=checks, benefit_evidence=_evidence(tmp_path, checks, "s1"))
    record = transition(tmp_path, record, "APPLIED", reason="prevention applied")
    record = transition(tmp_path, record, "QUARANTINED", reason="retention")
    assert quarantine_ready(record) is False
    assert quarantine_ready(record, datetime.now(timezone.utc)) is False
    old = datetime.fromisoformat(record["quarantine_at"]) + timedelta(hours=169)
    assert quarantine_ready(record, old) is True


def test_session_lifecycle_is_idempotent(tmp_path):
    checks = {"ledger_replay": True, "traini_gate_trace": True, "knomi_retrieval": True, "raw_transcript_excluded_from_knomi": True}
    evidence = _evidence(tmp_path, checks, "s2")
    first = lifecycle_for_session(tmp_path, session_id="s2", source_path="raw/s2", owner="Logi", evidence=["lesson.json"], benefit="used", result="applied", benefit_checks=checks, benefit_evidence=evidence, quarantined=True)
    second = lifecycle_for_session(tmp_path, session_id="s2", source_path="raw/s2", owner="Logi", evidence=["lesson.json"], benefit="used", result="applied", benefit_checks=checks, benefit_evidence=evidence, quarantined=True)
    assert first["artifact_id"] == second["artifact_id"]
    assert second["state"] == "QUARANTINED"
    assert audit(tmp_path)["counts"]["QUARANTINED"] == 1


def test_session_cannot_claim_benefit_without_downstream_checks(tmp_path):
    record = lifecycle_for_session(
        tmp_path,
        session_id="s3",
        source_path="raw/s3",
        owner="Logi",
        evidence=["lesson.json"],
        benefit="unproven",
        result="unproven",
    )
    assert record["state"] == "USED"
    assert audit(tmp_path)["status"] == "OPEN"


def test_direct_benefit_transition_requires_named_passing_checks(tmp_path):
    record = create(tmp_path, source_id="s4", source_path="raw/s4", artifact_type="test", owner="Logi")
    record = transition(tmp_path, record, "USED", reason="consumed")
    try:
        transition(tmp_path, record, "BENEFIT_VERIFIED", reason="claim only")
    except ValueError as exc:
        assert "exact passing downstream probe profile" in str(exc)
    else:
        raise AssertionError("benefit transition unexpectedly accepted without probes")


def test_codex_quarantine_cannot_shorten_168_hour_minimum(tmp_path):
    record = create(
        tmp_path,
        source_id="s5",
        source_path="raw/s5",
        artifact_type="codex_learning_material",
        owner="Logi",
        retention_hours=1,
    )
    assert record["retention_hours"] == 168
    record = transition(tmp_path, record, "USED", reason="used")
    checks = {"ledger_replay": True, "traini_gate_trace": True, "knomi_retrieval": True, "raw_transcript_excluded_from_knomi": True}
    record = transition(tmp_path, record, "BENEFIT_VERIFIED", reason="verified", benefit_checks=checks, benefit_evidence=_evidence(tmp_path, checks, "s5"))
    record = transition(tmp_path, record, "APPLIED", reason="applied")
    record = transition(tmp_path, record, "QUARANTINED", reason="quarantine")
    record["retention_hours"] = 1
    at = datetime.fromisoformat(record["quarantine_at"]) + timedelta(hours=2)
    assert quarantine_ready(record, at) is False
    record["retention_hours"] = "invalid"
    assert quarantine_ready(record, at) is False


def test_direct_deleted_transition_requires_retention_and_exact_confirmation(tmp_path):
    checks = {"ledger_replay": True, "traini_gate_trace": True, "knomi_retrieval": True, "raw_transcript_excluded_from_knomi": True}
    record = lifecycle_for_session(
        tmp_path,
        session_id="s6",
        source_path="raw/s6",
        owner="Logi",
        evidence=["lesson.json"],
        benefit="verified",
        result="applied",
        benefit_checks=checks,
        benefit_evidence=_evidence(tmp_path, checks, "s6"),
        quarantined=True,
    )
    try:
        transition(tmp_path, record, "DELETED", reason="bypass")
    except ValueError as exc:
        assert "168 hours" in str(exc)
    else:
        raise AssertionError("direct deletion bypass unexpectedly accepted")
