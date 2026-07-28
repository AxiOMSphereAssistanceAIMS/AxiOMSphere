from __future__ import annotations

import pytest

import ops.agents.job_filter_change_request as jfcr


@pytest.fixture(autouse=True)
def _isolated_request_dirs(tmp_path, monkeypatch):
    base = tmp_path / "joblocator_requests"
    monkeypatch.setattr(jfcr, "_BASE_DIR", base)
    monkeypatch.setattr(jfcr, "_PENDING_DIR", base / "pending")
    monkeypatch.setattr(jfcr, "_CONFIRMED_DIR", base / "confirmed")
    monkeypatch.setattr(jfcr, "_COMPLETED_DIR", base / "completed")
    monkeypatch.setattr(jfcr, "_REJECTED_DIR", base / "rejected")
    monkeypatch.setattr(
        jfcr,
        "_ALL_DIRS",
        (base / "pending", base / "confirmed", base / "completed", base / "rejected"),
    )


def test_write_and_load_pending_request() -> None:
    record = jfcr.write_change_request(
        requested_by="8077374184",
        raw_request_text="убери из поиска чистого электрика",
        understood_summary="Add 'electrical' handling: exclude pure-electrical titles (already excluded).",
        proposed_change={"action": "add_title_exclusion", "target": "electrical", "reason": "user request"},
    )
    assert record.status == "pending"
    loaded = jfcr.load_change_request(record.request_id)
    assert loaded is not None
    assert loaded.raw_request_text == "убери из поиска чистого электрика"
    assert loaded in jfcr.list_pending()


def test_only_original_requester_can_confirm() -> None:
    record = jfcr.write_change_request(
        requested_by="111",
        raw_request_text="x",
        understood_summary="y",
        proposed_change={"action": "noop"},
    )
    assert jfcr.mark_confirmed(record.request_id, requested_by="999") is None
    confirmed = jfcr.mark_confirmed(record.request_id, requested_by="111")
    assert confirmed is not None
    assert confirmed.status == "confirmed"
    assert confirmed in jfcr.list_confirmed()
    assert confirmed not in jfcr.list_pending()


def test_cannot_confirm_twice() -> None:
    record = jfcr.write_change_request(
        requested_by="111", raw_request_text="x", understood_summary="y", proposed_change={"action": "noop"}
    )
    jfcr.mark_confirmed(record.request_id, requested_by="111")
    assert jfcr.mark_confirmed(record.request_id, requested_by="111") is None


def test_mark_completed_requires_evidence() -> None:
    record = jfcr.write_change_request(
        requested_by="111", raw_request_text="x", understood_summary="y", proposed_change={"action": "noop"}
    )
    jfcr.mark_confirmed(record.request_id, requested_by="111")
    with pytest.raises(ValueError):
        jfcr.mark_completed(record.request_id, completed_by="logi_fullstack", evidence="")


def test_mark_completed_requires_confirmed_status_first() -> None:
    """A pending (not yet confirmed) request cannot jump straight to completed —
    JobLocator must never report a change as done that the requester never
    actually confirmed asking for."""
    record = jfcr.write_change_request(
        requested_by="111", raw_request_text="x", understood_summary="y", proposed_change={"action": "noop"}
    )
    result = jfcr.mark_completed(record.request_id, completed_by="logi_fullstack", evidence="diff attached")
    assert result is None


def test_full_lifecycle_pending_to_completed() -> None:
    record = jfcr.write_change_request(
        requested_by="111",
        raw_request_text="add mechanical exclusion",
        understood_summary="Exclude pure-mechanical titles",
        proposed_change={"action": "add_title_exclusion", "target": "mechanical"},
    )
    jfcr.mark_confirmed(record.request_id, requested_by="111")
    completed = jfcr.mark_completed(
        record.request_id,
        completed_by="logi_fullstack_session_abc123",
        evidence="ops/job_filter.py title_exclusions now includes 'mechanical'; verified via _classify_jobs regression test",
    )
    assert completed is not None
    assert completed.status == "completed"
    assert completed.evidence
    assert completed in jfcr.list_completed()
    assert completed not in jfcr.list_confirmed()


def test_mark_rejected() -> None:
    record = jfcr.write_change_request(
        requested_by="111", raw_request_text="x", understood_summary="y", proposed_change={"action": "noop"}
    )
    rejected = jfcr.mark_rejected(record.request_id, reason="user cancelled")
    assert rejected is not None
    assert rejected.status == "rejected"
    assert rejected.rejected_reason == "user cancelled"


def test_is_expired() -> None:
    import dataclasses
    from datetime import datetime, timedelta, timezone

    record = jfcr.write_change_request(
        requested_by="111", raw_request_text="x", understood_summary="y", proposed_change={"action": "noop"}
    )
    fresh = jfcr.load_change_request(record.request_id)
    assert not jfcr.is_expired(fresh)

    old = dataclasses.replace(
        fresh, created_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    )
    assert jfcr.is_expired(old)
