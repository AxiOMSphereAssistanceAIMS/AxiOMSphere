from __future__ import annotations

from email.message import EmailMessage
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import job_filter_bot
from job_filter_bot import (
    _canonical_url,
    _chunk_report_text,
    _date_is_today_dubai,
    _extract_vacancy_links,
    _is_direct_vacancy_url,
    _move_processed_messages,
    dedupe_jobs,
    scan_inbox_now,
)
from scripts.job_filter_daily_outcome import fallback_rows, format_message
from job_filter_sa_dama import enrich_sa_dama_outreach


def test_linkedin_alert_is_rejected_and_job_url_is_canonicalized() -> None:
    alert = "https://www.linkedin.com/comm/jobs/alerts?trk=mail"
    tracked_job = "https://www.linkedin.com/comm/jobs/view/4424083932/?trackingId=x&refId=y"

    assert not _is_direct_vacancy_url(alert)
    assert _is_direct_vacancy_url(tracked_job)
    assert _canonical_url(tracked_job) == "https://www.linkedin.com/jobs/view/4424083932"


def test_email_cards_keep_their_own_titles() -> None:
    message = EmailMessage()
    message["Subject"] = "Subject Matter Expert – Reliability Engineering at AVEVA"
    message.set_content("LinkedIn job alert")
    message.add_alternative(
        """
        <a href="https://www.linkedin.com/comm/jobs/alerts?trk=mail">Manage alerts</a>
        <a href="https://www.linkedin.com/comm/jobs/view/4424083932/?trackingId=x">
          Subject Matter Expert – Reliability Engineering
        </a>
        <a href="https://www.linkedin.com/comm/jobs/view/4424087872/?trackingId=y">
          Subject Matter Expert – Process Engineering
        </a>
        """,
        subtype="html",
    )

    rows = _extract_vacancy_links(message, str(message["Subject"]), "LinkedIn job alert")

    assert rows == [
        {
            "url": "https://www.linkedin.com/jobs/view/4424083932",
            "title": "Subject Matter Expert – Reliability Engineering",
            "company": "",
        },
        {
            "url": "https://www.linkedin.com/jobs/view/4424087872",
            "title": "Subject Matter Expert – Process Engineering",
            "company": "",
        },
    ]


def test_linkedin_email_card_preserves_company_and_location() -> None:
    message = EmailMessage()
    message["Subject"] = "Your job alert"
    message.set_content("LinkedIn job alert")
    message.add_alternative(
        """
        <table><tr><td class="pt-3" data-test-id="job-card">
          <a href="https://www.linkedin.com/comm/jobs/view/4444931466/?trk=logo">
            <img alt="Sugar Australia">
          </a>
          <a href="https://www.linkedin.com/comm/jobs/view/4444931466/?trk=body"
             class="font-bold text-md">Maintenance &amp; Engineering Manager</a>
          <p class="text-system-gray-100 text-xs">Sugar Australia &middot; Mackay, QLD</p>
        </td></tr></table>
        """,
        subtype="html",
    )

    rows = _extract_vacancy_links(message, str(message["Subject"]), "LinkedIn job alert")

    assert rows == [
        {
            "url": "https://www.linkedin.com/jobs/view/4444931466",
            "title": "Maintenance & Engineering Manager",
            "company": "Sugar Australia",
            "location": "Mackay, QLD",
        }
    ]


def test_empty_company_does_not_inherit_santos_contact_profile() -> None:
    row = enrich_sa_dama_outreach({"company": "", "title": "Reliability Engineer"})

    assert "company_website" not in row
    assert "company_careers_url" not in row


def test_dedupe_uses_both_job_id_and_position_identity() -> None:
    rows = dedupe_jobs(
        [
            {
                "title": "Reliability Engineer",
                "company": "AVEVA",
                "location": "Abu Dhabi",
                "url": "https://www.linkedin.com/jobs/view/1001?trk=a",
                "source": "email",
            },
            {
                "title": "Reliability Engineer",
                "company": "AVEVA",
                "location": "Abu Dhabi",
                "url": "https://www.linkedin.com/jobs/view/1002?trk=b",
                "source": "email",
            },
            {
                "title": "Process Engineer",
                "company": "AVEVA",
                "location": "Abu Dhabi",
                "url": "https://www.linkedin.com/jobs/view/1003?trk=c",
                "source": "email",
            },
        ]
    )

    assert [row["url"] for row in rows] == [
        "https://www.linkedin.com/jobs/view/1001",
        "https://www.linkedin.com/jobs/view/1003",
    ]


def test_company_position_dedupe_ignores_location_and_source() -> None:
    rows = dedupe_jobs([
        {
            "title": "Maintenance Manager",
            "company": "Santos",
            "location": "Adelaide",
            "url": "https://www.linkedin.com/jobs/view/2001",
            "source": "linkedin",
        },
        {
            "title": "Maintenance Manager",
            "company": "Santos",
            "location": "Whyalla",
            "url": "https://www.seek.com.au/job/2002",
            "source": "seek",
        },
    ])

    assert len(rows) == 1


def test_dubai_calendar_date_filter_rejects_yesterday() -> None:
    now = datetime(2026, 7, 26, 5, 0, tzinfo=ZoneInfo("Asia/Dubai"))

    assert _date_is_today_dubai("2026-07-26", now=now)
    assert _date_is_today_dubai("Sun, 26 Jul 2026 01:30:00 +0000", now=now)
    assert not _date_is_today_dubai("2026-07-25", now=now)
    assert not _date_is_today_dubai("", now=now)


class _FakeIMAP:
    def __init__(self, copy_status: str = "OK") -> None:
        self.copy_status = copy_status
        self.calls: list[tuple] = []

    def uid(self, *args):
        self.calls.append(args)
        if args[0] == "copy":
            return self.copy_status, []
        return "OK", []

    def expunge(self):
        self.calls.append(("expunge",))
        return "OK", []

    def login(self, *_args):
        return "OK", []

    def select(self, *_args):
        return "OK", []

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", []


def test_processed_mail_is_copied_then_deleted_and_expunged() -> None:
    connection = _FakeIMAP()

    moved = _move_processed_messages(connection, [b"41"], "[Gmail]/Trash")

    assert moved == 1
    assert connection.calls == [
        ("copy", "41", "[Gmail]/Trash"),
        ("store", "41", "+FLAGS", "\\Deleted"),
        ("expunge",),
    ]


def test_mail_remains_in_inbox_when_classification_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    message = EmailMessage()
    message["From"] = "jobs@example.com"
    message["Subject"] = "Reliability Engineer at AVEVA"
    message["Date"] = datetime.now(ZoneInfo("Asia/Dubai")).strftime("%a, %d %b %Y %H:%M:%S %z")
    message.set_content("https://www.linkedin.com/jobs/view/1001")
    connection = _FakeIMAP()

    def uid(*args):
        connection.calls.append(args)
        if args[0] == "search":
            return "OK", [b"41"]
        if args[0] == "fetch":
            return "OK", [(b"41 (RFC822)", message.as_bytes())]
        return "OK", []

    connection.uid = uid  # type: ignore[method-assign]
    monkeypatch.setattr(job_filter_bot.imaplib, "IMAP4_SSL", lambda *_args: connection)
    monkeypatch.setattr(job_filter_bot, "_classify_jobs", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("classification failed")))
    monkeypatch.setenv("JOB_FILTER_EMAIL_ENABLED", "1")
    monkeypatch.setenv("JOB_FILTER_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("JOB_FILTER_EMAIL_USER", "user")
    monkeypatch.setenv("JOB_FILTER_EMAIL_PASSWORD", "secret")
    monkeypatch.setenv("JOB_FILTER_ALLOWED_SENDERS", "jobs@example.com")
    monkeypatch.setenv("JOB_FILTER_MOVE_TO_FOLDER", "[Gmail]/Trash")

    with pytest.raises(RuntimeError, match="classification failed"):
        scan_inbox_now()

    assert not any(call[0] in {"copy", "store", "expunge"} for call in connection.calls)


def test_daily_fallback_hides_non_actionable_duplicates_and_navigation_links() -> None:
    run = {
        "rows": [
            {
                "status": "duplicate_blocked",
                "company": "AVEVA",
                "title": "Reliability Engineer",
                "source_url": "https://www.linkedin.com/jobs/view/1001",
            },
            {
                "status": "validation_failed",
                "company": "AVEVA",
                "title": "Reliability Engineer",
                "source_url": "https://www.linkedin.com/comm/jobs/alerts?trk=mail",
            },
            {
                "status": "validation_failed",
                "company": "AVEVA",
                "title": "Process Engineer",
                "source_url": "https://www.linkedin.com/comm/jobs/view/1002?trk=mail",
            },
        ]
    }

    rows = fallback_rows(run)

    assert len(rows) == 1
    assert rows[0]["vacancy_url"] == "https://www.linkedin.com/jobs/view/1002"


def test_daily_outcome_does_not_render_failed_gmail_run_as_pass() -> None:
    message = format_message(
        {
            "run_status": "FAIL",
            "rows": [{"status": "gmail_preflight_failed"}],
            "drafts_created": 0,
            "rejected_ineligible": 0,
        },
        [],
    )

    assert "❌ Status: FAIL" in message
    assert "✅ Status: PASS" not in message


def test_daily_outcome_reports_discovered_rows_when_none_reach_draft(tmp_path) -> None:
    scan = tmp_path / "scan.json"
    scan.write_text(
        """{
          "inbox_scan": {"total": 0, "ignored": 0},
          "web_scan": {"total": 22, "ignored": 22},
          "combined_kept_after_cross_dedup": 0
        }""",
        encoding="utf-8",
    )

    message = format_message(
        {
            "run_status": "PASS",
            "source_scan": str(scan),
            "rows": [],
            "drafts_created": 0,
            "rejected_ineligible": 0,
        },
        [],
    )

    assert "⚠️ Status: NO_MATCHES_AFTER_FILTER" in message
    assert "Vacancies discovered: 22" in message
    assert "Rejected at discovery filter: 22" in message
    assert "Vacancies evaluated for draft: 0" in message


def test_chunk_report_text_never_splits_a_line() -> None:
    # A long <a href="..."> attribute value that would straddle a naive
    # text[i:i+limit] slice at several points.
    lines = [
        f'{i}. Job {i}'
        + '\n   Contact: <a href="https://example.com/search?q='
        + ("x" * 40)
        + f'{i}">HR/contact search</a>'
        for i in range(60)
    ]
    text = "\n".join(lines)

    chunks = _chunk_report_text(text, limit=200)

    assert "\n".join(chunks) == text
    for chunk in chunks:
        assert len(chunk) <= 200 or "\n" not in chunk
        assert chunk.count("<a ") == chunk.count("</a>")


def test_chunk_report_text_empty_and_short_input() -> None:
    assert _chunk_report_text("") == [""]
    assert _chunk_report_text("short line") == ["short line"]


def _dama_matching_resume_profile():
    from job_filter_resume_profile import ResumeProfile

    return ResumeProfile(
        target_roles=["maintenance superintendent", "reliability engineer", "maintenance manager"],
        seniority="manager",
        years_experience=10,
    )


def test_electrical_and_mechanical_titles_stay_excluded_even_in_dama_region(monkeypatch) -> None:
    """Regression test: the Australia/DAMA resume-admission leniency must not
    resurrect a role the classifier hard-excluded specifically for being
    electrical or pure-mechanical discipline — those don't match this CV's
    profile even when the posting is otherwise DAMA-eligible. Other hard
    exclusions (e.g. "facilities") are still eligible for the leniency
    rescue; only electrical/mechanical are carved out.
    """
    monkeypatch.setattr(job_filter_bot, "load_resume_profile", _dama_matching_resume_profile)

    jobs = [
        {
            "title": "Maintenance Electrical Superintendent",
            "url": "https://www.seek.com.au/job/1",
            "company": "Glencore",
            "location": "Perth WA, Australia",
            "description": "Maintenance Electrical Superintendent, Plant, FIFO ex Perth.",
            "source": "seek",
            "country": "Australia",
        },
        {
            "title": "Reliability & Project Engineer (Mechanical)",
            "url": "https://www.seek.com.au/job/2",
            "company": "Stilkram Professional Resources",
            "location": "Perth WA, Australia",
            "description": "Experienced Mechanical Reliability Engineer with Project Management experience. 5+ years in mining.",
            "source": "seek",
            "country": "Australia",
        },
        {
            "title": "Maintenance Manager",
            "url": "https://www.seek.com.au/job/3",
            "company": "Orana Gardens",
            "location": "Dubbo, Dubbo & Central NSW, Australia",
            "description": "Lead facilities maintenance operations in a supportive community environment.",
            "source": "seek",
            "country": "Australia",
        },
    ]

    result = job_filter_bot._classify_jobs(jobs, "seek")

    kept_titles = {j["title"] for j in result.jobs}
    assert kept_titles == {"Maintenance Manager"}

    rejected_by_title = {j["title"]: j["classification_reasons"] for j in result.rejected_jobs}
    assert any("electrical" in r for r in rejected_by_title["Maintenance Electrical Superintendent"])
    assert any("mechanical" in r for r in rejected_by_title["Reliability & Project Engineer (Mechanical)"])
