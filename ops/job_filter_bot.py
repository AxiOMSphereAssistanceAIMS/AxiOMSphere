#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import email
import imaplib
import html
import hashlib
import json
import logging
import os
import re
import signal
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import parse as urlparse
from urllib import error as urlerror
from urllib import request as urlrequest
from zoneinfo import ZoneInfo

from job_filter import JobFilterConfig, classify_job
from job_filter_resume_profile import (
    australian_role_level_allowed,
    load_resume_profile,
    resume_match_percent,
    score_job_against_resume,
    summarize_resume_profile,
)
from job_filter_sa_dama import (
    build_sa_dama_config,
    enrich_sa_dama_outreach,
    match_dama_region,
    sa_dama_enabled,
    sa_dama_locations,
    sa_dama_queries,
    sa_dama_visa_queries,
)
from job_sources import fetch_all_sources


log = logging.getLogger("job_filter_bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

DUBAI_TZ = ZoneInfo("Asia/Dubai")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _merge_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _workspace_root() -> Path:
    root = os.environ.get("AIMS_WORKSPACE", "/data").strip() or "/data"
    return Path(root)


def _state_dir() -> Path:
    p = _workspace_root() / "job_filter"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _published_token(job: dict[str, Any]) -> str:
    for key in ("published", "published_at", "date_str", "pub_date", "date"):
        val = str(job.get(key, "") or "").strip()
        if val:
            return val[:24]
    return ""


def _date_is_today_dubai(value: str, *, now: datetime | None = None) -> bool:
    """Accept only records published/received on the current Dubai date."""
    raw = str(value or "").strip()
    if not raw:
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(DUBAI_TZ)
    lowered = raw.casefold()
    if lowered in {"today", "just posted", "just now"} or re.fullmatch(r"\d+\s+(?:minute|minutes|hour|hours)\s+ago", lowered):
        return True
    if lowered == "yesterday" or re.fullmatch(r"\d+\s+(?:day|days)\s+ago", lowered):
        return False
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return False
    if parsed.tzinfo is None:
        return parsed.date() == current.date()
    return parsed.astimezone(DUBAI_TZ).date() == current.date()


def _job_is_today_dubai(job: dict[str, Any], *, now: datetime | None = None) -> bool:
    return _date_is_today_dubai(_published_token(job), now=now)


def _canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlparse.urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw

    host = parts.netloc.lower()
    if "linkedin.com" in host:
        match = re.search(r"/jobs/view/(\d+)", parts.path)
        if match:
            return f"https://www.linkedin.com/jobs/view/{match.group(1)}"

    drop_keys = {
        "from",
        "eid",
        "lipi",
        "midsig",
        "midtoken",
        "otptoken",
        "refid",
        "trk",
        "trkemail",
        "trackingid",
    }
    kept = []
    for key, value in urlparse.parse_qsl(parts.query, keep_blank_values=True):
        key_l = key.lower()
        if key_l.startswith("utm_"):
            continue
        if key_l in drop_keys:
            continue
        kept.append((key, value))
    kept.sort()
    canonical_query = urlparse.urlencode(kept, doseq=True)
    return urlparse.urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            canonical_query,
            "",
        )
    )


def _is_direct_vacancy_url(url: str) -> bool:
    """Return true only for a link that identifies one concrete vacancy."""
    raw = html.unescape((url or "").strip())
    if not raw:
        return False
    parts = urlparse.urlsplit(raw)
    host = parts.netloc.lower()
    path = parts.path.lower().rstrip("/")
    query = dict(urlparse.parse_qsl(parts.query, keep_blank_values=True))
    if "linkedin.com" in host:
        return bool(re.search(r"/jobs/view/\d+$", path))
    if "seek.com.au" in host:
        return bool(re.search(r"/job/\d+$", path))
    if "indeed" in host:
        return bool(query.get("jk") or query.get("jobkey"))
    blocked = ("/alerts", "/alert", "/search", "/preferences", "/unsubscribe", "/feed", "/login")
    if any(token in path for token in blocked):
        return False
    return bool(re.search(r"/(?:jobs?|vacancies|positions?|opportunities)/[^/]+", path))


def _stable_job_key_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlparse.urlsplit(raw)
    host = parts.netloc.lower()
    path = parts.path.rstrip("/")
    query = dict(urlparse.parse_qsl(parts.query, keep_blank_values=True))

    if "linkedin.com" in host:
        m = re.search(r"/jobs/view/(\d+)", path)
        if m:
            return f"linkedin:{m.group(1)}"
    if "seek.com.au" in host:
        m = re.search(r"/job/(\d+)", path)
        if m:
            return f"seek:{m.group(1)}"
    if "indeed" in host:
        jk = query.get("jk") or query.get("jobkey")
        if jk:
            return f"indeed:{jk}"
    return ""


def _job_fingerprint(job: dict[str, Any]) -> str:
    title = _norm(str(job.get("title", "")))
    company = _norm(str(job.get("company", "")))
    location = _norm(str(job.get("location", "")))
    published = _norm(_published_token(job))
    source = _norm(str(job.get("source", "")))
    stable_url_key = _stable_job_key_from_url(str(job.get("url", "") or ""))

    if stable_url_key:
        payload = f"id|{stable_url_key}"
    else:
        payload = f"meta|{title}|{company}|{location}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sent_ledger_path() -> Path:
    return _state_dir() / "sent_jobs_ledger.jsonl"


def _load_sent_job_fingerprints() -> set[str]:
    path = _sent_ledger_path()
    fingerprints: set[str] = set()
    if not path.exists():
        return fingerprints

    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fingerprint = str(payload.get("fingerprint", "") or "").strip()
                if fingerprint:
                    fingerprints.add(fingerprint)
    except Exception as exc:
        log.warning("failed to load job sent ledger %s: %s", path, exc)
    return fingerprints


def _append_sent_jobs(jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        return
    path = _sent_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now_utc()
    try:
        with path.open("a", encoding="utf-8") as fh:
            for job in jobs:
                record = {
                    "recorded_at_utc": now,
                    "fingerprint": _job_fingerprint(job),
                    "title": str(job.get("title", "") or "").strip(),
                    "company": str(job.get("company", "") or "").strip(),
                    "url": str(job.get("url", "") or "").strip(),
                    "published": _published_token(job),
                    "source": str(job.get("source", "") or "").strip(),
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.warning("failed to append job sent ledger %s: %s", path, exc)


def _filter_already_sent_jobs(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen = _load_sent_job_fingerprints()
    kept: list[dict[str, Any]] = []
    skipped = 0
    for job in jobs:
        fingerprint = _job_fingerprint(job)
        if fingerprint in seen:
            skipped += 1
            continue
        record = dict(job)
        record["fingerprint"] = fingerprint
        kept.append(record)
    return kept, skipped


def dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by vacancy id and, when available, position identity."""
    seen_url_keys: set[str] = set()
    seen_position_keys: set[str] = set()
    out: list[dict[str, Any]] = []
    for job in jobs:
        record = dict(job)
        title = _norm(str(job.get("title", "")))
        company = _norm(str(job.get("company", "")))
        location = _norm(str(job.get("location", "")))
        if not title:
            continue
        raw_url = str(job.get("url", "") or "")
        if _norm(str(job.get("source", ""))) in {"email", "inbox"} and not _is_direct_vacancy_url(raw_url):
            continue
        canonical_url = _canonical_url(raw_url)
        if canonical_url:
            record["url"] = canonical_url
        stable_url_key = _stable_job_key_from_url(canonical_url)
        # Operator contract: one vacancy identity is Company + Position.
        # Location/source differences must not create duplicate draft letters.
        position_key = f"{company}|{title}" if company else ""
        if stable_url_key and stable_url_key in seen_url_keys:
            continue
        if position_key and position_key in seen_position_keys:
            continue
        if stable_url_key:
            seen_url_keys.add(stable_url_key)
        if position_key:
            seen_position_keys.add(position_key)
        out.append(record)
    return out


def _decode_subject(raw: str | None) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    buf: list[str] = []
    for txt, enc in parts:
        if isinstance(txt, bytes):
            buf.append(txt.decode(enc or "utf-8", errors="replace"))
        else:
            buf.append(txt)
    return "".join(buf)


def _extract_text_from_message(msg: email.message.Message) -> str:
    texts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain":
                try:
                    texts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace"))
                except Exception:
                    continue
    else:
        try:
            texts.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace"))
        except Exception:
            pass
    return "\n".join(texts)


def _extract_html_from_message(msg: email.message.Message) -> str:
    texts: list[str] = []
    for part in msg.walk() if msg.is_multipart() else (msg,):
        if (part.get_content_type() or "").lower() != "text/html":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            texts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        except Exception:
            continue
    return "\n".join(texts)


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href = ""
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href:
            return
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text)))
            self._href = ""
            self._text = []


def _clean_vacancy_title(value: str) -> str:
    title = re.sub(r"\s+", " ", html.unescape(value or "")).strip()
    title = re.sub(r"^(?:view|see|apply(?: for)?|open)\s+(?:this\s+)?job\s*[:\-]?\s*", "", title, flags=re.I)
    if not title or len(title) > 180 or _norm(title) in {"view job", "apply", "learn more", "see more"}:
        return ""
    return title


def _strip_html_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _extract_linkedin_email_cards(html_body: str) -> list[dict[str, str]]:
    """Extract one vacancy identity from each LinkedIn alert card."""
    if not html_body or 'data-test-id="job-card"' not in html_body:
        return []
    blocks = re.split(
        r"<td\b[^>]*data-test-id=[\"']job-card[\"'][^>]*>",
        html_body,
        flags=re.IGNORECASE,
    )[1:]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in blocks:
        # Bound the card before the next major alert section when possible.
        block = block[: block.find('data-test-id="job-card"')] if 'data-test-id="job-card"' in block else block
        title_match = re.search(
            r'<a\b[^>]*href="([^"]*linkedin\.com/(?:comm/)?jobs/view/\d+[^"]*)"'
            r'[^>]*class="[^"]*font-bold[^"]*"[^>]*>(.*?)</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        canonical = _canonical_url(html.unescape(title_match.group(1)))
        if not canonical or canonical in seen:
            continue
        title = _clean_vacancy_title(_strip_html_text(title_match.group(2)))
        if not title:
            continue
        company = ""
        location = ""
        meta_match = re.search(
            r'<p\b[^>]*class="[^"]*text-system-gray-100[^"]*"[^>]*>(.*?)</p>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if meta_match:
            metadata = _strip_html_text(meta_match.group(1))
            parts = [part.strip() for part in metadata.split("·", 1)]
            company = parts[0] if parts else ""
            location = parts[1] if len(parts) > 1 else ""
        australia_alert = "geoId=101452733" in html_body or "geoId%3D101452733" in html_body
        if (
            australia_alert
            and location
            and re.search(r"\b(?:WA|SA|NT|QLD|NSW|VIC|TAS|ACT)\b", location)
            and "australia" not in location.casefold()
        ):
            location = f"{location}, Australia"
        seen.add(canonical)
        out.append(
            {
                "url": canonical,
                "title": title,
                "company": company,
                "location": location,
            }
        )
    return out


def _extract_vacancy_links(msg: email.message.Message, subject: str, plain_text: str) -> list[dict[str, str]]:
    """Extract only direct vacancy links and preserve each card's own title."""
    candidates: dict[str, dict[str, str]] = {}
    html_body = _extract_html_from_message(msg)
    for card in _extract_linkedin_email_cards(html_body):
        candidates[card["url"]] = card
    if html_body:
        parser = _AnchorCollector()
        try:
            parser.feed(html_body)
        except Exception:
            parser.links = []
        for href, anchor_text in parser.links:
            if not _is_direct_vacancy_url(href):
                continue
            canonical = _canonical_url(href)
            title = _clean_vacancy_title(anchor_text)
            existing = candidates.get(canonical)
            if existing is None or (title and not existing.get("title")):
                candidates[canonical] = {"url": canonical, "title": title, "company": "", "location": ""}

    for href in re.findall(r"https?://[^\s)>\"]+", plain_text):
        href = html.unescape(href).rstrip(".,;]")
        if not _is_direct_vacancy_url(href):
            continue
        canonical = _canonical_url(href)
        candidates.setdefault(canonical, {"url": canonical, "title": "", "company": "", "location": ""})

    only_one = len(candidates) == 1
    out: list[dict[str, str]] = []
    for candidate in candidates.values():
        title = candidate.get("title") or (_clean_vacancy_title(subject) if only_one else "")
        if not title:
            stable_key = _stable_job_key_from_url(candidate["url"])
            title = f"Vacancy {stable_key.replace(':', ' ')}" if stable_key else "Vacancy"
        company = str(candidate.get("company") or "").strip()
        location = str(candidate.get("location") or "").strip()
        if not company and " at " in title:
            title, company = (part.strip() for part in title.rsplit(" at ", 1))
        row = {"url": candidate["url"], "title": title, "company": company}
        if location:
            row["location"] = location
        out.append(row)
    return out


def _move_processed_messages(con: imaplib.IMAP4_SSL, uids: list[bytes], folder: str) -> int:
    """Copy successfully processed messages to the configured folder, then delete originals."""
    if not folder or not uids:
        return 0
    moved = 0
    for uid in uids:
        uid_s = uid.decode("ascii") if isinstance(uid, bytes) else str(uid)
        copy_status, _ = con.uid("copy", uid_s, folder)
        if copy_status != "OK":
            log.warning("imap copy failed uid=%s folder=%s", uid_s, folder)
            continue
        delete_status, _ = con.uid("store", uid_s, "+FLAGS", "\\Deleted")
        if delete_status != "OK":
            log.warning("imap delete flag failed uid=%s after copy folder=%s", uid_s, folder)
            continue
        moved += 1
    if moved:
        con.expunge()
    return moved


@dataclass
class ScanResult:
    source: str
    total: int
    classified: int
    kept: int
    ignored: int
    jobs: list[dict[str, Any]]
    rejected_jobs: list[dict[str, Any]] = field(default_factory=list)
    deduplicated: int = 0


def _active_filter_config() -> JobFilterConfig:
    cfg = JobFilterConfig()
    if sa_dama_enabled():
        cfg = build_sa_dama_config(cfg)
    return cfg


def _classify_jobs(raw_jobs: list[dict[str, Any]], source: str, cfg: JobFilterConfig | None = None) -> ScanResult:
    cfg = cfg or _active_filter_config()
    resume_profile = load_resume_profile()
    kept: list[dict[str, Any]] = []
    rejected_jobs: list[dict[str, Any]] = []
    ignored = 0
    for job in raw_jobs:
        title = str(job.get("title", "") or "")
        desc = str(job.get("description", "") or "")
        company = str(job.get("company", "") or "")
        location = str(job.get("location", "") or "")
        industry = str(job.get("industry", "") or "")
        source_name = str(job.get("source", "") or source or "")
        text = f"{title}\n{company}\n{location}\n{industry}\n{source_name}\n{desc}"
        cls = classify_job(text, cfg, title=title)
        record = enrich_sa_dama_outreach(job) if sa_dama_enabled() else dict(job)
        record["priority"] = cls.priority.value
        record["score"] = cls.score
        match_score_10, match_reasons, match_buckets = score_job_against_resume(record, resume_profile)
        ats_percent, ats_details = resume_match_percent(record, resume_profile)
        record["display_score_10"] = match_score_10
        record["resume_match_percent"] = ats_percent
        record["resume_match_details"] = ats_details
        record["match_reasons"] = match_reasons[:6]
        record["match_buckets"] = match_buckets
        record["reasons"] = cls.reasons[:6]
        region = match_dama_region(f"{location} {job.get('country', '')}")
        role_level_ok, role_level_reason = australian_role_level_allowed(title)
        resume_role_hits = list(ats_details.get("role_hits") or [])
        # Electrical and pure-mechanical-discipline titles are a deliberate
        # "never show me this — doesn't match my CV" exclusion. DAMA-region
        # leniency below is meant to rescue borderline eligibility calls
        # (e.g. "experience requirement too low", or other hard exclusions
        # like "facilities" the user has not asked to exclude), not override
        # a discipline mismatch the classifier already flagged specifically
        # for these two terms.
        _non_overridable_domain_terms = ("electrical", "mechanical")
        is_domain_exclusion = any(
            reason.startswith(("Hard exclusion matched", "Title exclusion", "Content exclusion"))
            and any(term in reason for term in _non_overridable_domain_terms)
            for reason in cls.reasons
        )
        australia_resume_admit = bool(
            not is_domain_exclusion
            and region.get("matched")
            and role_level_ok
            and resume_role_hits
            and ats_percent >= 20.0
        )
        if cls.priority.value != "IGNORE" or australia_resume_admit:
            if cls.priority.value == "IGNORE":
                record["priority"] = "MEDIUM PRIORITY"
                record["admission_path"] = "australia_resume_role_match"
                record["reasons"] = [
                    "Australia resume admission: configured DAMA region + CV target role",
                    *record["reasons"],
                ][:6]
            else:
                record["admission_path"] = "static_filter"
            kept.append(record)
        else:
            ignored += 1
            rejected_jobs.append(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": str(job.get("url", "") or ""),
                    "source": source_name,
                    "published": _published_token(job),
                    "classification_reasons": cls.reasons[:6],
                    "resume_match_percent": ats_percent,
                    "resume_role_hits": resume_role_hits,
                    "role_level_reason": role_level_reason,
                    "dama_region_matched": bool(region.get("matched")),
                }
            )
    deduped = dedupe_jobs(kept)
    return ScanResult(
        source=source,
        total=len(raw_jobs),
        classified=len(kept) + ignored,
        kept=len(deduped),
        ignored=ignored,
        jobs=deduped,
        rejected_jobs=rejected_jobs,
        deduplicated=len(kept) - len(deduped),
    )


def scan_inbox_now(limit: int = 60) -> ScanResult:
    if not _env_bool("JOB_FILTER_EMAIL_ENABLED", False):
        return ScanResult("inbox", 0, 0, 0, 0, [])
    host = os.environ.get("JOB_FILTER_IMAP_HOST", "").strip()
    user = os.environ.get("JOB_FILTER_EMAIL_USER", "").strip()
    password = os.environ.get("JOB_FILTER_EMAIL_PASSWORD", "").strip()
    mailbox = os.environ.get("JOB_FILTER_EMAIL_MAILBOX", "INBOX").strip() or "INBOX"
    move_to_folder = os.environ.get("JOB_FILTER_MOVE_TO_FOLDER", "").strip()
    allowed_senders = {
        item.strip().casefold()
        for item in os.environ.get("JOB_FILTER_ALLOWED_SENDERS", "").split(",")
        if item.strip()
    }
    port = int(os.environ.get("JOB_FILTER_IMAP_PORT", "993") or "993")
    if not host or not user or not password:
        log.warning("inbox scan skipped: missing IMAP credentials")
        return ScanResult("inbox", 0, 0, 0, 0, [])

    raw_jobs: list[dict[str, Any]] = []
    processed_uids: list[bytes] = []
    con = imaplib.IMAP4_SSL(host, port)
    try:
        con.login(user, password)
        con.select(mailbox)
        since = datetime.now(timezone.utc).astimezone(DUBAI_TZ).strftime("%d-%b-%Y")
        status, data = con.uid("search", None, "SINCE", since)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")
        ids = (data[0] or b"").split()[-limit:]
        for uid in ids:
            uid_s = uid.decode("ascii") if isinstance(uid, bytes) else str(uid)
            status, payload = con.uid("fetch", uid_s, "(RFC822)")
            if status != "OK":
                continue
            if not payload or not isinstance(payload[0], tuple):
                continue
            try:
                msg = email.message_from_bytes(payload[0][1])
                sender = _decode_subject(msg.get("From")).casefold()
                if allowed_senders and not any(allowed in sender for allowed in allowed_senders):
                    continue
                if not _date_is_today_dubai(str(msg.get("Date") or "")):
                    continue
                subj = _decode_subject(msg.get("Subject"))
                text = _extract_text_from_message(msg)
                vacancies = _extract_vacancy_links(msg, subj, text)
            except Exception as exc:
                log.warning("inbox message parse failed uid=%s: %s", uid, exc)
                continue
            for vacancy in vacancies:
                raw_jobs.append(
                    {
                        "title": vacancy["title"],
                        "company": vacancy["company"],
                        "location": vacancy.get("location", ""),
                        "url": vacancy["url"],
                        "description": text[:800],
                        "date_str": msg.get("Date", ""),
                        "source": "email",
                    }
                )
            processed_uids.append(uid)

        # Classification is part of successful processing.  Do not move any
        # message if it fails: it must remain available for the next run.
        result = _classify_jobs(raw_jobs, "inbox")
        moved = _move_processed_messages(con, processed_uids, move_to_folder)
        log.info(
            "inbox processed=%d moved=%d direct_vacancies=%d folder=%s",
            len(processed_uids),
            moved,
            len(raw_jobs),
            move_to_folder or "disabled",
        )
        return result
    finally:
        try:
            con.logout()
        except Exception:
            pass

    raise AssertionError("unreachable")


async def scan_sources_now() -> ScanResult:
    if not _env_bool("JOB_FILTER_SOURCES_ENABLED", True):
        return ScanResult("web", 0, 0, 0, 0, [])
    strict_dama_locations = _env_bool("JOB_FILTER_STRICT_DAMA_LOCATIONS", False)
    query_raw = "" if strict_dama_locations else os.environ.get(
        "JOB_FILTER_QUERIES",
        "maintenance manager,asset integrity manager,reliability manager,lead instrument engineer",
    )
    location_raw = "" if strict_dama_locations else os.environ.get(
        "JOB_FILTER_LOCATIONS",
        "UAE,Saudi Arabia,Qatar",
    )
    queries = [x.strip() for x in query_raw.split(",") if x.strip()]
    locations = [x.strip() for x in location_raw.split(",") if x.strip()]
    visa_dama_queries: list[str] = []
    cfg = _active_filter_config()
    if sa_dama_enabled():
        sa_queries = sa_dama_queries()
        sa_locations = sa_dama_locations()
        visa_dama_queries = sa_dama_visa_queries()
        queries = _merge_unique([*queries, *sa_queries])
        locations = _merge_unique([*locations, *sa_locations])
        log.info(
            "sa_dama branch enabled: queries=%d locations=%d dama_codes=%s",
            len(sa_queries),
            len(sa_locations),
            ",".join(("233512", "233513")),
        )
    days = int(os.environ.get("JOB_FILTER_SOURCE_DAYS", "1") or "1")
    jobs = await fetch_all_sources(
        queries=queries,
        locations=locations,
        days=days,
        enable_indeed=_env_bool("JOB_FILTER_SOURCE_INDEED", False),
        enable_linkedin=_env_bool("JOB_FILTER_SOURCE_LINKEDIN", True),
        enable_seek=_env_bool("JOB_FILTER_SOURCE_SEEK", True),
        visa_dama_queries=visa_dama_queries,
    )
    if _env_bool("JOB_FILTER_TODAY_ONLY", True):
        before = len(jobs)
        jobs = [job for job in jobs if _job_is_today_dubai(job)]
        log.info("web today-only filter: kept=%d dropped_stale_or_undated=%d", len(jobs), before - len(jobs))
    return _classify_jobs(jobs, "web", cfg)


def _save_scan_report(
    inbox: ScanResult,
    scan: ScanResult,
    combined: list[dict[str, Any]],
    suppressed_already_sent: int,
) -> Path:
    out_dir = _state_dir() / "nightly_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"job_filter_scan_{ts}.json"
    payload = {
        "generated_at_utc": _now_utc(),
        "sequence": ["inbox", "web"],
        "mode": "scan",
        "inbox_scan": {
            "total": inbox.total,
            "classified": inbox.classified,
            "kept": inbox.kept,
            "ignored": inbox.ignored,
            "deduplicated": inbox.deduplicated,
        },
        "web_scan": {
            "total": scan.total,
            "classified": scan.classified,
            "kept": scan.kept,
            "ignored": scan.ignored,
            "deduplicated": scan.deduplicated,
        },
        "combined_kept_after_cross_dedup": len(combined),
        "suppressed_already_sent": suppressed_already_sent,
        "rejected_jobs": (inbox.rejected_jobs + scan.rejected_jobs)[:500],
        "jobs": combined[:300],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _cleanup_report_file(path: Path) -> None:
    try:
        path.unlink()
        log.info("temporary report removed: %s", path)
    except FileNotFoundError:
        return
    except Exception as exc:
        log.warning("failed to remove temporary report %s: %s", path, exc)


def _telegram_token() -> str:
    for name in (
        "JOB_FILTER_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "AXI_BOT_TOKEN",
        "OMI_TELEGRAM_BOT_TOKEN",
        "OMI_TELEGRAM_TOKEN",
    ):
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return ""


def _telegram_chat_ids() -> list[str]:
    for name in (
        "JOB_FILTER_NOTIFY_CHAT_IDS",
        "JOB_FILTER_ALLOWED_USER_IDS",
        "AXI_ALLOWED_USER_IDS",
        "TELEGRAM_GROUP_ID",
    ):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        ids = [part.strip() for part in raw.split(",") if part.strip()]
        if ids:
            return list(dict.fromkeys(ids))
    return []


def _chunk_report_text(text: str, limit: int = 3800) -> list[str]:
    """Split ``text`` into <=``limit``-char chunks, breaking only between
    lines.

    Every ``<a href="...">...</a>`` tag this module builds is constructed on
    a single line. A blind ``text[i:i+limit]`` slice can land inside one of
    those tags, which both breaks the visible link (split across two
    Telegram messages) and produces malformed HTML for that chunk — Telegram
    then rejects it with HTTP 400, triggering the plain-text fallback, whose
    regex tag-stripper can't cleanly remove a tag that's already been cut in
    half. Splitting only at line boundaries makes that class of corruption
    impossible.
    """
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        added_len = len(line) + (1 if current else 0)  # +1 for the join newline
        if current and current_len + added_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += added_len
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def _telegram_send(text: str) -> list[str]:
    token = _telegram_token()
    if not token:
        log.warning("telegram report skipped: no bot token available")
        return []
    chat_ids = _telegram_chat_ids()
    if not chat_ids:
        log.warning("telegram report skipped: no chat ids available")
        return []

    delivered: list[str] = []
    # Telegram hard-limits message text to 4096 characters. Preserve the
    # complete report by sending bounded chunks in order, split only at
    # line boundaries (see _chunk_report_text).
    chunks = _chunk_report_text(text)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chat_ids:
      for chunk_index, chunk in enumerate(chunks, start=1):
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlrequest.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                delivered.append(f"{chat_id}:{body['result']['message_id']}:part{chunk_index}")
                log.info("telegram report delivered to %s", chat_id)
            else:
                log.warning("telegram report failed for %s: %s", chat_id, body)
        except urlerror.HTTPError as exc:
            # Telegram rejects malformed HTML with HTTP 400. Preserve the
            # report and retry the identical content as plain text so a
            # formatting defect cannot turn a completed scan into a failed
            # production run.
            if exc.code == 400:
                fallback = urlrequest.Request(
                    url,
                    data=json.dumps({
                        "chat_id": chat_id,
                        "text": re.sub(r"<[^>]+>", "", chunk),
                        "disable_web_page_preview": True,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urlrequest.urlopen(fallback, timeout=20) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    if body.get("ok"):
                        delivered.append(f"{chat_id}:{body['result']['message_id']}:part{chunk_index}:plain_fallback")
                        log.warning("telegram HTML rejected for %s; plain-text fallback delivered", chat_id)
                        continue
                except (urlerror.URLError, TimeoutError, OSError, json.JSONDecodeError) as fallback_exc:
                    log.warning("telegram plain-text fallback failed for %s: %s", chat_id, fallback_exc)
            log.warning("telegram HTTP error for %s: %s", chat_id, exc)
        except (urlerror.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            log.warning("telegram report send failed for %s: %s", chat_id, exc)
    return delivered


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _display_score_10(job: dict[str, Any]) -> float:
    value = job.get("display_score_10", job.get("score", 0))
    try:
        return round(float(value), 1)
    except Exception:
        return 0.0


def _job_display(job: dict[str, Any]) -> str:
    title = html.escape(str(job.get("title", "") or "").strip()) or "Untitled job"
    company = html.escape(str(job.get("company", "") or "").strip()) or "Unknown company"
    location = html.escape(str(job.get("location", "") or "").strip())
    url = str(job.get("url", "") or "").strip()
    source = html.escape(str(job.get("source", "") or "").strip()) or "source"
    priority = html.escape(str(job.get("priority", "") or "").strip()) or "N/A"
    display_score = _display_score_10(job)
    company_website = str(job.get("company_website", "") or "").strip()
    company_careers_url = str(job.get("company_careers_url", "") or "").strip()
    company_linkedin_url = str(job.get("company_linkedin_url", "") or "").strip()
    contact_hint = html.escape(str(job.get("contact_hint", "") or "").strip())
    contact_linkedin_search_url = str(job.get("contact_linkedin_search_url", "") or "").strip()

    if url:
        title_line = f'<a href="{html.escape(url, quote=True)}">{title}</a>'
    else:
        title_line = title

    lines = [
        title_line,
        f"<i>{company}</i>",
    ]
    if location:
        lines.append(f"Location: {location}")

    links: list[str] = []
    if company_website:
        links.append(f'<a href="{html.escape(company_website, quote=True)}">site</a>')
    if company_careers_url:
        links.append(f'<a href="{html.escape(company_careers_url, quote=True)}">careers</a>')
    if company_linkedin_url:
        links.append(f'<a href="{html.escape(company_linkedin_url, quote=True)}">company LinkedIn</a>')
    if links:
        lines.append("Company: " + " · ".join(links))

    if contact_hint or contact_linkedin_search_url:
        contact_parts = []
        if contact_hint:
            contact_parts.append(contact_hint)
        if contact_linkedin_search_url:
            contact_parts.append(f'<a href="{html.escape(contact_linkedin_search_url, quote=True)}">HR/contact search</a>')
        lines.append("Contact: " + " · ".join(contact_parts))

    lines.append(f"{source} · {priority} · score {display_score:.1f}/10")
    return "\n".join(lines)


def _source_label(source: str) -> str:
    key = (source or "").strip().lower()
    mapping = {
        "linkedin": "📡 LinkedIn",
        "seek": "🧭 SEEK",
        "email": "✉️ Email",
        "rss/public": "📰 RSS/Public",
        "rss": "📰 RSS/Public",
        "web": "🌐 Web",
        "inbox": "✉️ Inbox",
    }
    return mapping.get(key, f"📡 {source or 'Source'}")


def _priority_emoji(priority: str) -> str:
    key = (priority or "").upper()
    if "DIGITAL" in key:
        return "🟣"
    if key.startswith("HIGH"):
        return "🔴"
    if key.startswith("MEDIUM"):
        return "🟡"
    return "⚪"


def _format_job_grouped(job: dict[str, Any], index: int | None = None) -> str:
    display_lines = _job_display(job).splitlines()
    if index is not None and display_lines:
        display_lines[0] = f"{index}. {display_lines[0]}"
        display_lines = [display_lines[0]] + [f"   {line}" for line in display_lines[1:]]
    match_reasons = job.get("match_reasons") or []
    lines = display_lines[:]
    if match_reasons:
        reason_line = "; ".join(str(item) for item in match_reasons[:3] if str(item).strip())
        if reason_line:
            lines.append(f"   <i>{html.escape(reason_line)}</i>")
    return "\n".join(lines)


def _format_telegram_report(
    inbox: ScanResult,
    scan: ScanResult,
    combined: list[dict[str, Any]],
    suppressed_already_sent: int,
    _report_path: Path,
) -> str:
    resume_profile = load_resume_profile()
    resume_line = "Resume criteria: <b>not loaded</b>"
    if resume_profile is not None:
        summary = summarize_resume_profile(resume_profile)
        source_names = ", ".join(Path(p).name for p in summary.get("source_paths", [])[:3])
        resume_line = (
            f"Resume criteria: <b>loaded</b>"
            + (f" ({html.escape(source_names)})" if source_names else "")
            + f" · {html.escape(summary.get('short_summary', ''))}"
        )

    lines = [
        f"Inbox scan: {inbox.kept} kept from {inbox.total} items",
        f"Web scan: {scan.kept} kept from {scan.total} items",
        f"Combined after dedupe: <b>{len(combined)}</b>",
        resume_line,
    ]
    if suppressed_already_sent:
        lines.append(f"Already sent suppressed: <b>{suppressed_already_sent}</b>")

    if not combined:
        if suppressed_already_sent:
            lines.append("No new vacancies: all kept matches were already sent previously.")
        else:
            lines.append("No matches kept this run.")
        return "\n".join(lines)

    lines.append("")
    lines.append("<b>Top matches</b>")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in combined:
        grouped[str(job.get("source", "") or "source").strip()].append(job)

    source_order = sorted(grouped.keys(), key=lambda s: (s.lower() != "linkedin", s.lower() != "email", s.lower()))
    max_per_source = int(os.environ.get("JOB_FILTER_REPORT_MAX_PER_SOURCE", "7") or "7")
    max_total = int(os.environ.get("JOB_FILTER_REPORT_MAX_TOTAL", "20") or "20")
    emitted = 0
    for source in source_order:
        if emitted >= max_total:
            break
        source_jobs = sorted(
            grouped[source],
            key=lambda job: (_display_score_10(job), _safe_float(job.get("score", 0))),
            reverse=True,
        )[:max_per_source]
        if not source_jobs:
            continue
        lines.append(f"\n{_source_label(source)}")

        priority_order = ["HIGH PRIORITY (DIGITAL)", "HIGH PRIORITY", "MEDIUM PRIORITY", "IGNORE"]
        by_priority: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for job in source_jobs:
            by_priority[str(job.get("priority", "") or "IGNORE")].append(job)

        for priority in priority_order:
            jobs = by_priority.get(priority, [])
            if not jobs:
                continue
            emoji = _priority_emoji(priority)
            lines.append(f"{emoji} {priority} ({len(jobs)})")
            for idx, job in enumerate(jobs, start=1):
                if emitted >= max_total:
                    break
                lines.append(_format_job_grouped(job, idx))
                emitted += 1
        if emitted >= max_total:
            break

    if len(combined) > emitted:
        lines.append(f"\n…and {len(combined) - emitted} more matches")
    return "\n".join(lines)


async def run_sequence(inbox_now: bool, scan_now: bool, send_telegram: bool) -> int:
    inbox_res = ScanResult("inbox", 0, 0, 0, 0, [])
    scan_res = ScanResult("web", 0, 0, 0, 0, [])
    if inbox_now:
        inbox_res = scan_inbox_now()
        log.info("inbox-scan: total=%d kept=%d ignored=%d", inbox_res.total, inbox_res.kept, inbox_res.ignored)
    if scan_now:
        scan_res = await scan_sources_now()
        log.info("web-scan: total=%d kept=%d ignored=%d", scan_res.total, scan_res.kept, scan_res.ignored)

    combined = dedupe_jobs(inbox_res.jobs + scan_res.jobs)
    # Only verified Gmail Draft state may suppress outreach. Telegram delivery
    # and discovery history are deliberately not dedupe authorities.
    filtered_combined, suppressed_already_sent = combined, 0
    log.info(
        "cross-dedup: combined_kept=%d suppressed_already_sent=%d (inbox=%d, scan=%d)",
        len(filtered_combined),
        suppressed_already_sent,
        len(inbox_res.jobs),
        len(scan_res.jobs),
    )
    report = _save_scan_report(inbox_res, scan_res, filtered_combined, suppressed_already_sent)
    log.info("report: %s", report)

    if send_telegram:
        telegram_report = _format_telegram_report(
            inbox_res,
            scan_res,
            filtered_combined,
            suppressed_already_sent,
            report,
        )
        delivered = _telegram_send(telegram_report)
        if delivered:
            log.info("telegram report summary delivered: %s", ", ".join(delivered))
            _cleanup_report_file(report)
        else:
            log.warning("telegram report was not delivered")
        # Scan mode: run once and exit (scheduler stops container afterwards).
        return 0
    return 0


def _daemon_loop() -> int:
    """Default container behavior: keep process alive for exec-triggered commands.

    Also runs the JobLocator Telegram command listener (chat-driven filter
    tuning) when JOB_FILTER_BOT_TOKEN is set and python-telegram-bot is
    importable. If either is missing, or the listener fails to start for any
    reason, this falls back to the plain heartbeat loop — the docker-exec
    -triggered scan mechanism the scheduler relies on doesn't depend on the
    listener at all, so a listener failure must never take the container down.
    """
    interval = max(10, int(os.environ.get("JOB_FILTER_DAEMON_HEARTBEAT_SEC", "60") or "60"))

    if os.environ.get("JOB_FILTER_BOT_TOKEN", "").strip():
        try:
            import job_filter_telegram_listener as _listener

            log.info("job-filter daemon mode active (heartbeat=%ss, telegram listener enabled)", interval)
            _listener.run_polling_forever()
            log.info("job-filter daemon stopping cleanly")
            return 0
        except Exception:
            log.exception("JobLocator telegram listener failed to start; falling back to heartbeat-only daemon")

    log.info("job-filter daemon mode active (heartbeat=%ss, telegram listener disabled)", interval)
    stopping = False
    def _stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not stopping:
        time.sleep(interval)
    log.info("job-filter daemon stopping cleanly")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Job filter scanner (email + sources)")
    ap.add_argument("--scan", action="store_true", help="run full scan cycle (inbox + web + dedupe + Telegram)")
    ap.add_argument("--daemon", action="store_true", help="keep container alive for exec-triggered scans")
    args = ap.parse_args()

    if args.daemon or not args.scan:
        return _daemon_loop()

    return asyncio.run(run_sequence(inbox_now=True, scan_now=True, send_telegram=True))


if __name__ == "__main__":
    raise SystemExit(main())
