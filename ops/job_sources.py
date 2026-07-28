"""
job_sources.py
──────────────
Fetches job listings directly from job sites via RSS / public search.
No login required. Runs once a day at scheduled time.

Supported sources:
  - Indeed — RSS feed (ae + www) for non-Australia locations; Australia uses au.indeed.com
    mobile SERP with embedded JSON (Indeed RSS HTML no longer returns raw XML reliably).
  - LinkedIn — public guest API, 3 pages per query, no account needed
  - SEEK (AU) — HTML search via curl_cffi; optional FlareSolverr not required when TLS mimic works
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape as _unescape
import urllib.parse

import httpx

logger = logging.getLogger("job_sources")

# Australia: Indeed RSS + desktop SERP are mostly empty in static HTML; mobile /m/jobs embeds Job blobs.
_INDEED_AU_MOBILE = "https://au.indeed.com/m/jobs"
_PLACEHOLDER_INDEED_JK = frozenset({"456789abcdef0123"})

# SEEK job cards (href before data-automation="jobTitle")
_SEEK_JOB_CARD_RE = re.compile(
    r'<a[^>]+href="(/job/\d+[^"]*)"[^>]+data-automation="jobTitle"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Delay between HTTP requests to avoid rate limiting (seconds)
_REQUEST_DELAY = 0.8


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    return raw in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _source_block_threshold(name: str, default: int = 3) -> int:
    return max(1, _env_int(name, default))


def _firecrawl_enabled() -> bool:
    return _env_bool("JOB_FILTER_FIRECRAWL_ENABLED", True)


def _firecrawl_max_jobs() -> int:
    return max(1, int(os.environ.get("JOB_FILTER_FIRECRAWL_MAX_JOBS", "25") or "25"))


def _firecrawl_timeout_sec() -> int:
    return max(5, int(os.environ.get("JOB_FILTER_FIRECRAWL_TIMEOUT_SEC", "35") or "35"))


def _firecrawl_base_url() -> str:
    # For self-hosted Firecrawl compatibility (no subscription/key required).
    return (os.environ.get("FIRECRAWL_BASE_URL", "http://firecrawl:3002") or "http://firecrawl:3002").rstrip("/")


def _firecrawl_use_sdk() -> bool:
    return _env_bool("JOB_FILTER_FIRECRAWL_USE_SDK", True)


def _firecrawl_auth_headers() -> dict[str, str]:
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _extract_markdown_from_response(payload: dict) -> str:
    markdown = str(payload.get("markdown") or "")
    if not markdown and isinstance(payload.get("data"), dict):
        markdown = str(payload["data"].get("markdown") or "")
    if not markdown and isinstance(payload.get("data"), list):
        for row in payload["data"]:
            if isinstance(row, dict) and row.get("markdown"):
                markdown = str(row["markdown"])
                if markdown:
                    break
    return markdown


def _firecrawl_scrape_http(url: str, timeout_sec: int) -> str:
    endpoint = f"{_firecrawl_base_url()}/v1/scrape"
    body = {"url": url, "formats": ["markdown"]}
    headers = {"Content-Type": "application/json", **_firecrawl_auth_headers()}
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.post(endpoint, json=body, headers=headers)
            if resp.status_code >= 400:
                return ""
            payload = resp.json() if resp.content else {}
        if isinstance(payload, dict):
            return _extract_markdown_from_response(payload)
        return ""
    except Exception:
        return ""


def _firecrawl_scrape_markdown(url: str, timeout_sec: int) -> str:
    # 1) Optional SDK path (cloud or self-host if SDK supports api_url)
    # 2) Direct HTTP path (works with self-host, no key)
    if _firecrawl_use_sdk():
        try:
            from firecrawl import FirecrawlApp

            api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip() or None
            app = FirecrawlApp(api_key=api_key, api_url=_firecrawl_base_url())
            result = app.scrape_url(
                url,
                params={"formats": ["markdown"], "timeout": timeout_sec},
            )
            if isinstance(result, dict):
                md = _extract_markdown_from_response(result)
                if md:
                    return md
        except Exception:
            pass
    return _firecrawl_scrape_http(url, timeout_sec)


async def _enrich_jobs_with_firecrawl(jobs: list[dict]) -> list[dict]:
    if not jobs or not _firecrawl_enabled():
        return jobs

    timeout_sec = _firecrawl_timeout_sec()
    max_jobs = min(len(jobs), _firecrawl_max_jobs())
    enriched = 0

    for job in jobs:
        if enriched >= max_jobs:
            break
        if str(job.get("description") or "").strip():
            continue
        url = str(job.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        md = await asyncio.to_thread(_firecrawl_scrape_markdown, url, timeout_sec)
        if not md:
            continue
        clean = re.sub(r"\s+", " ", md).strip()
        if len(clean) < 80:
            continue
        job["description"] = clean[:1600]
        job["firecrawl_enriched"] = True
        enriched += 1

    if enriched:
        logger.info("firecrawl: enriched %d jobs for JobLocator", enriched)
    return jobs

# ── Indeed RSS ────────────────────────────────────────────────────────────────

# Try multiple base URLs — ae.indeed.com may redirect or 404
_INDEED_RSS_BASES = [
    "https://ae.indeed.com/jobs/rss",   # UAE-specific
    "https://www.indeed.com/jobs/rss",  # global fallback
]


def _indeed_rss_url(base: str, query: str, location: str, days: int = 1) -> str:
    params = {
        "q": query,
        "l": location,
        "sort": "date",
        "fromage": str(days),
        "radius": "50",  # km radius
    }
    return base + "?" + urllib.parse.urlencode(params)


def _parse_indeed_rss(xml_bytes: bytes) -> list[dict]:
    """Parse Indeed RSS XML into list of job dicts."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.warning("indeed_rss_parse_error: %s", e)
        return []

    items = root.findall(".//item")
    results = []
    for item in items:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        desc_el = item.find("description")

        raw_title = _unescape(title_el.text or "") if title_el is not None else ""
        url = (link_el.text or "").strip() if link_el is not None else ""
        date_str = (pub_el.text or "").strip() if pub_el is not None else ""
        description = _unescape(re.sub(r"<[^>]+>", " ", desc_el.text or "")) if desc_el is not None else ""

        # Indeed RSS title format: "Job Title - Company - City, Country"
        parts = [p.strip() for p in raw_title.split(" - ")]
        job_title = parts[0] if parts else raw_title
        company = parts[1] if len(parts) > 1 else ""
        location_str = " - ".join(parts[2:]) if len(parts) > 2 else ""

        if not job_title or not url:
            continue

        # Strip tracking params that break the URL (keep jk= which is the job ID)
        clean_url = url.split("&from=")[0] if "&from=" in url else url

        try:
            pub_dt = parsedate_to_datetime(date_str)
        except Exception:
            pub_dt = None

        results.append({
            "title": job_title,
            "url": clean_url,
            "company": company,
            "location": location_str,
            "description": description[:300],
            "date_str": date_str,
            "pub_dt": pub_dt,
            "source": "indeed",
        })
    return results


async def fetch_indeed_rss(
    queries: list[str],
    locations: list[str],
    days: int = 1,
    timeout: float = 20.0,
) -> list[dict]:
    """
    Fetch jobs from Indeed RSS using curl_cffi to impersonate Chrome TLS fingerprint.
    Indeed blocks standard httpx/requests due to JA3 fingerprint detection.
    """
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        logger.warning("indeed_rss: curl_cffi not installed, skipping Indeed")
        return []

    seen_urls: set[str] = set()
    all_jobs: list[dict] = []
    access_failures = 0
    access_failure_threshold = _source_block_threshold("JOB_FILTER_INDEED_ACCESS_FAILURE_LIMIT", 3)

    # Indeed-specific headers that mimic a real browser navigating to RSS
    indeed_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.indeed.com/",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "upgrade-insecure-requests": "1",
    }

    async with AsyncSession(impersonate="chrome120", timeout=timeout) as session:
        for query in queries:
            for location in locations:
                fetched = False
                for base in _INDEED_RSS_BASES:
                    url = _indeed_rss_url(base, query, location, days)
                    try:
                        await asyncio.sleep(_REQUEST_DELAY)
                        resp = await session.get(url, headers=indeed_headers, allow_redirects=True)
                        if resp.status_code == 200:
                            content = resp.content
                            ct = resp.headers.get("content-type", "")
                            if "xml" in ct or "rss" in ct or content.startswith(b"<?xml") or content.startswith(b"<rss"):
                                jobs = _parse_indeed_rss(content)
                                added = 0
                                for job in jobs:
                                    if job["url"] not in seen_urls:
                                        seen_urls.add(job["url"])
                                        all_jobs.append(job)
                                        added += 1
                                logger.info("indeed_rss query=%r loc=%r found=%d new=%d", query, location, len(jobs), added)
                                fetched = True
                                break
                            else:
                                logger.warning("indeed_rss not-xml status=200 base=%s query=%r len=%d", base, query, len(content))
                                access_failures += 1
                        elif resp.status_code == 429:
                            logger.warning("indeed_rss rate_limit base=%s — stopping Indeed", base)
                            return all_jobs
                        elif resp.status_code in {401, 403}:
                            access_failures += 1
                            logger.warning(
                                "indeed_rss access_blocked status=%d base=%s query=%r loc=%r failures=%d/%d",
                                resp.status_code,
                                base,
                                query,
                                location,
                                access_failures,
                                access_failure_threshold,
                            )
                            if access_failures >= access_failure_threshold:
                                logger.warning("indeed_rss access failure threshold reached — stopping Indeed RSS for this run")
                                return all_jobs
                        else:
                            logger.warning("indeed_rss status=%d base=%s query=%r loc=%r", resp.status_code, base, query, location)
                        if access_failures >= access_failure_threshold:
                            logger.warning("indeed_rss access failure threshold reached — stopping Indeed RSS for this run")
                            return all_jobs
                    except Exception as e:
                        logger.warning("indeed_rss_error base=%s query=%r loc=%r: %s", base, query, location, e)
                if not fetched:
                    logger.warning("indeed_rss all_bases_failed query=%r loc=%r", query, location)

    all_jobs.sort(key=lambda j: j["pub_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return all_jobs


# ── LinkedIn public search ────────────────────────────────────────────────────

_LI_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LI_JOB_ID_RE = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"')
_LI_TITLE_RE = re.compile(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)\s*</h3>', re.IGNORECASE)
_LI_COMPANY_RE = re.compile(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?<a[^>]*>\s*([^<]+)\s*</a>', re.IGNORECASE | re.DOTALL)
_LI_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"', re.IGNORECASE)
_LI_LOCATION_RE = re.compile(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*([^<]+)\s*</span>', re.IGNORECASE)

# Pages to fetch per query (each page = 25 results)
_LI_PAGES = [0, 25, 50]


def _parse_linkedin_jobs_html(html: str) -> list[dict]:
    """Parse LinkedIn guest jobs search API HTML response."""
    job_ids = _LI_JOB_ID_RE.findall(html)
    titles = [_unescape(t.strip()) for t in _LI_TITLE_RE.findall(html)]
    companies = [_unescape(c.strip()) for c in _LI_COMPANY_RE.findall(html)]
    times = _LI_TIME_RE.findall(html)
    locations = [_unescape(l.strip()) for l in _LI_LOCATION_RE.findall(html)]

    results = []
    for i, job_id in enumerate(job_ids):
        title = titles[i] if i < len(titles) else ""
        if not title:
            continue
        results.append({
            "title": title,
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
            "company": companies[i] if i < len(companies) else "",
            "location": locations[i] if i < len(locations) else "",
            "description": "",
            "date_str": times[i] if i < len(times) else "",
            "pub_dt": None,
            "source": "linkedin",
        })
    return results


async def fetch_linkedin_jobs(
    queries: list[str],
    locations: list[str],
    days: int = 1,
    timeout: float = 25.0,
) -> list[dict]:
    """Fetch jobs from LinkedIn public guest API — 3 pages per query, no login needed."""
    seen_urls: set[str] = set()
    all_jobs: list[dict] = []

    # f_TPR: r86400=24h, r604800=7days, r2592000=30days
    tpr = "r86400" if days <= 1 else ("r604800" if days <= 7 else "r2592000")

    async with httpx.AsyncClient(headers=_HEADERS, timeout=timeout, follow_redirects=True) as client:
        for query in queries:
            for location in locations:
                for start in _LI_PAGES:
                    params = {
                        "keywords": query,
                        "location": location,
                        "f_TPR": tpr,
                        "sortBy": "DD",
                        "start": str(start),
                    }
                    if _is_au_location(location):
                        # Prevent ambiguous state abbreviations (notably WA)
                        # from returning Washington/India/global results.
                        params["geoId"] = "101452733"  # Australia
                    try:
                        await asyncio.sleep(_REQUEST_DELAY)
                        resp = await client.get(_LI_SEARCH_URL, params=params)
                        if resp.status_code == 429:
                            logger.warning("linkedin_jobs rate_limit query=%r loc=%r start=%d — waiting 10s", query, location, start)
                            await asyncio.sleep(10)
                            break  # skip remaining pages for this query/location
                        if resp.status_code != 200:
                            logger.warning("linkedin_jobs status=%d query=%r loc=%r start=%d", resp.status_code, query, location, start)
                            break
                        jobs = _parse_linkedin_jobs_html(resp.text)
                        if not jobs:
                            break  # no more results on this page
                        if _is_au_location(location):
                            for job in jobs:
                                job["country"] = "Australia"
                                actual_location = str(job.get("location") or "").strip()
                                if actual_location and "australia" not in actual_location.casefold():
                                    job["location"] = f"{actual_location}, Australia"
                        added = 0
                        for job in jobs:
                            if job["url"] not in seen_urls:
                                seen_urls.add(job["url"])
                                all_jobs.append(job)
                                added += 1
                        logger.info("linkedin_jobs query=%r loc=%r start=%d found=%d new=%d", query, location, start, len(jobs), added)
                        if added == 0 or len(jobs) < 10:
                            # LinkedIn often repeats page 1 for start=25/50 or
                            # for equivalent location aliases. Continuing only
                            # creates rate-limit pressure without new jobs.
                            break
                    except (httpx.TimeoutException, httpx.NetworkError) as e:
                        logger.warning("linkedin_jobs_error query=%r loc=%r start=%d: %s", query, location, start, e)
                        break

    return all_jobs


# ── Australia helpers ─────────────────────────────────────────────────────────

def _is_au_location(loc: str) -> bool:
    """Heuristic: treat Australian cities / states / postcodes as AU for SEEK + Indeed AU."""
    s = loc.strip().lower()
    if not s:
        return False
    if "australia" in s:
        return True
    cities = (
        "perth", "sydney", "melbourne", "brisbane", "adelaide", "darwin",
        "hobart", "canberra", "gold coast", "newcastle", "wollongong", "cairns", "townsville",
    )
    if any(c in s for c in cities):
        return True
    if re.search(r"\b(wa|nsw|qld|vic|sa|nt|tas|act)\b", s):
        return True
    return False


def _merge_unique_queries(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for q in group:
            k = q.strip()
            if not k:
                continue
            low = k.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(k)
    return out


def _indeed_fromage_days(days: int) -> int:
    return max(1, min(int(days or 1), 30))


def _seek_daterange_param(days: int) -> int:
    return max(1, min(int(days or 1), 31))


def _parse_seek_jobs_html(html: str) -> list[dict]:
    """Parse SEEK's structured search payload, preserving admission evidence.

    The old anchor-only parser discarded company, actual location, posting
    timestamp and teaser.  JOB_FILTER_TODAY_ONLY then rejected every SEEK row
    as undated, before resume matching could run.
    """
    marker = '"jobs":['
    start = html.find(marker)
    structured: list[dict] = []
    if start >= 0:
        try:
            payload, _ = json.JSONDecoder().raw_decode(html[start + len('"jobs":') :])
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = []
        if isinstance(payload, list):
            seen_ids: set[str] = set()
            for row in payload:
                if not isinstance(row, dict):
                    continue
                job_id = str(row.get("id") or "").strip()
                title = _unescape(str(row.get("title") or "").strip())
                if not job_id or not title or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                locations = row.get("locations") or []
                location = ""
                if isinstance(locations, list) and locations and isinstance(locations[0], dict):
                    location = str(locations[0].get("label") or "").strip()
                if location and "australia" not in location.casefold():
                    location = f"{location}, Australia"
                company = str(row.get("companyName") or "").strip()
                if not company and isinstance(row.get("advertiser"), dict):
                    company = str(row["advertiser"].get("description") or "").strip()
                evidence = [
                    str(row.get("teaser") or "").strip(),
                    str(row.get("salaryLabel") or "").strip(),
                ]
                evidence.extend(
                    str(item).strip()
                    for item in (row.get("bulletPoints") or [])
                    if str(item).strip()
                )
                structured.append(
                    {
                        "title": title,
                        "url": f"https://www.seek.com.au/job/{job_id}",
                        "company": _unescape(company),
                        "location": _unescape(location),
                        "description": " ".join(item for item in evidence if item)[:1600],
                        "date_str": str(row.get("listingDate") or "").strip(),
                        "pub_dt": None,
                        "source": "seek",
                    }
                )
    if structured:
        return structured

    # Compatibility fallback for a SEEK response without embedded JSON.  Such
    # rows remain undated and therefore fail closed under TODAY_ONLY.
    fallback = []
    for href_raw, title_raw in _SEEK_JOB_CARD_RE.findall(html):
        path = _unescape(href_raw.split("?")[0])
        match = re.fullmatch(r"/job/(\d+)", path)
        if not match:
            continue
        fallback.append(
            {
                "title": _unescape(re.sub(r"\s+", " ", title_raw).strip()),
                "url": f"https://www.seek.com.au/job/{match.group(1)}",
                "company": "",
                "location": "",
                "description": "",
                "date_str": "",
                "pub_dt": None,
                "source": "seek",
            }
        )
    return fallback


_INDEED_JOB_EMBED_RE = re.compile(
    r'"__typename":"Job","key":"([a-f0-9]{16})","title":"([^"]+)","sourceEmployerName":"([^"]*)"',
)


async def fetch_indeed_au_mobile_embedded(
    queries: list[str],
    locations: list[str],
    days: int = 1,
    timeout: float = 25.0,
) -> list[dict]:
    """
    Fetch au.indeed.com mobile SERP HTML and parse embedded GraphQL Job objects.
    Static HTML usually exposes only a small subset of results; pagination is limited without a browser.
    """
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        logger.warning("indeed_au: curl_cffi not installed, skipping Indeed AU")
        return []

    fromage = _indeed_fromage_days(days)
    seen_urls: set[str] = set()
    all_jobs: list[dict] = []
    access_failures = 0
    access_failure_threshold = _source_block_threshold("JOB_FILTER_INDEED_AU_ACCESS_FAILURE_LIMIT", 3)

    # Desktop Chrome — Android/mobile UA often yields a shell without embedded Job JSON in static HTML.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
        "Referer": "https://au.indeed.com/",
    }

    async with AsyncSession(impersonate="chrome120", timeout=timeout) as session:
        for query in queries:
            for location in locations:
                params = {"q": query, "l": location, "fromage": str(fromage)}
                url = _INDEED_AU_MOBILE + "?" + urllib.parse.urlencode(params)
                try:
                    await asyncio.sleep(_REQUEST_DELAY)
                    resp = await session.get(url, headers=headers, allow_redirects=True)
                    if resp.status_code != 200:
                        if resp.status_code in {401, 403, 429}:
                            access_failures += 1
                            logger.warning(
                                "indeed_au access_blocked status=%d query=%r loc=%r failures=%d/%d",
                                resp.status_code,
                                query,
                                location,
                                access_failures,
                                access_failure_threshold,
                            )
                            if access_failures >= access_failure_threshold:
                                logger.warning("indeed_au access failure threshold reached — stopping Indeed AU for this run")
                                return all_jobs
                        else:
                            logger.warning("indeed_au status=%d query=%r loc=%r", resp.status_code, query, location)
                        continue
                    html = resp.text
                    found = _INDEED_JOB_EMBED_RE.findall(html)
                    for jk, title, company in found:
                        if jk in _PLACEHOLDER_INDEED_JK:
                            continue
                        clean_url = f"https://au.indeed.com/viewjob?jk={jk}"
                        if clean_url in seen_urls:
                            continue
                        seen_urls.add(clean_url)
                        all_jobs.append({
                            "title": _unescape(title.strip()),
                            "url": clean_url,
                            "company": _unescape(company.strip()) if company else "",
                            "location": location,
                            "description": "",
                            "date_str": "",
                            "pub_dt": None,
                            "source": "indeed",
                        })
                    logger.info("indeed_au query=%r loc=%r embedded_jobs=%d", query, location, len(found))
                except Exception as e:
                    logger.warning("indeed_au_error query=%r loc=%r: %s", query, location, e)

    return all_jobs


async def fetch_seek_jobs(
    queries: list[str],
    locations: list[str],
    days: int = 1,
    max_pages: int = 2,
    timeout: float = 25.0,
) -> list[dict]:
    """Fetch SEEK Australia job search HTML and parse job cards (curl_cffi TLS mimic)."""
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        logger.warning("seek: curl_cffi not installed, skipping SEEK")
        return []

    dr = _seek_daterange_param(days)
    seen_urls: set[str] = set()
    all_jobs: list[dict] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
        "Referer": "https://www.seek.com.au/",
    }

    async with AsyncSession(impersonate="chrome120", timeout=timeout) as session:
        for query in queries:
            for location in locations:
                for page in range(1, max(1, max_pages) + 1):
                    params = {"keywords": query, "where": location, "page": page, "daterange": str(dr)}
                    url = "https://www.seek.com.au/jobs?" + urllib.parse.urlencode(params)
                    try:
                        await asyncio.sleep(_REQUEST_DELAY)
                        resp = await session.get(url, headers=headers, allow_redirects=True)
                        if resp.status_code == 429:
                            logger.warning("seek rate_limit — stopping SEEK")
                            return all_jobs
                        if resp.status_code != 200:
                            logger.warning("seek status=%d query=%r loc=%r page=%d", resp.status_code, query, location, page)
                            break
                        html = resp.text
                        if "Just a moment" in html and "Cloudflare" in html:
                            logger.warning("seek Cloudflare challenge — try FlareSolverr or network path")
                            break
                        added = 0
                        for job in _parse_seek_jobs_html(html):
                            full_url = str(job["url"])
                            if full_url in seen_urls:
                                continue
                            seen_urls.add(full_url)
                            # The structured row contains the real advertised
                            # location.  Use the query location only as a
                            # last-resort fallback.
                            if not str(job.get("location") or "").strip():
                                job["location"] = location
                            all_jobs.append(job)
                            added += 1
                        logger.info("seek query=%r loc=%r page=%d new=%d", query, location, page, added)
                        if added == 0:
                            break
                    except Exception as e:
                        logger.warning("seek_error query=%r loc=%r page=%d: %s", query, location, page, e)
                        break

    return all_jobs


# ── Combined fetch ────────────────────────────────────────────────────────────

async def fetch_all_sources(
    queries: list[str],
    locations: list[str],
    days: int = 1,
    enable_indeed: bool = True,
    enable_linkedin: bool = True,
    enable_seek: bool = False,
    visa_dama_queries: list[str] | None = None,
) -> list[dict]:
    """Fetch from all enabled sources sequentially (to respect rate limits) and return combined list."""
    combined: list[dict] = []
    seen: set[str] = set()

    extra = visa_dama_queries or []
    au_locs = [loc for loc in locations if _is_au_location(loc)]
    au_queries = _merge_unique_queries(queries, extra) if au_locs else []

    # Sequential (not parallel) to avoid triggering rate limits on both sites simultaneously
    if enable_linkedin:
        try:
            jobs = await fetch_linkedin_jobs(queries, locations, days)
            for job in jobs:
                if job["url"] not in seen:
                    seen.add(job["url"])
                    combined.append(job)
        except Exception as exc:
            logger.warning("fetch_linkedin_failed: %s", exc)

    if enable_indeed:
        # Indeed RSS: Gulf / global — skip AU (handled below) and other LinkedIn-only regions
        _linkedin_only = {"australia", "perth", "sydney", "melbourne", "brisbane",
                          "malaysia", "borneo", "singapore"}
        # Exclude AU (and legacy linkedin-only tokens) from Gulf/global RSS — AU uses au.indeed.com mobile path.
        indeed_locs = [
            l for l in locations
            if not _is_au_location(l) and l.strip().lower() not in _linkedin_only
        ]
        try:
            jobs = await fetch_indeed_rss(queries, indeed_locs, days)
            for job in jobs:
                if job["url"] not in seen:
                    seen.add(job["url"])
                    combined.append(job)
        except Exception as exc:
            logger.warning("fetch_indeed_failed: %s", exc)

        if au_locs and au_queries:
            try:
                jobs = await fetch_indeed_au_mobile_embedded(au_queries, au_locs, days)
                for job in jobs:
                    if job["url"] not in seen:
                        seen.add(job["url"])
                        combined.append(job)
            except Exception as exc:
                logger.warning("fetch_indeed_au_failed: %s", exc)

    if enable_seek and au_locs and au_queries:
        try:
            jobs = await fetch_seek_jobs(au_queries, au_locs, days)
            for job in jobs:
                if job["url"] not in seen:
                    seen.add(job["url"])
                    combined.append(job)
        except Exception as exc:
            logger.warning("fetch_seek_failed: %s", exc)

    combined = await _enrich_jobs_with_firecrawl(combined)
    logger.info("fetch_all_sources total=%d", len(combined))
    return combined
