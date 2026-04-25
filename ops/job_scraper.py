"""
job_scraper.py
──────────────
Playwright-based job scraper with session persistence.
Logs in once per week, scrapes 2 pages per site per day.

Sites: LinkedIn, Indeed (AE), NaukriGulf, JobLeads, Rigzone
Sessions saved to: /data/config/scraper_sessions/<site>.json
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

logger = logging.getLogger("job_scraper")

# ── Date helpers ─────────────────────────────────────────────────────────────

_24H_AGO = lambda: datetime.now(timezone.utc) - timedelta(hours=24)


def _parse_relative_date(text: str) -> datetime | None:
    """Parse relative date strings like '2 hours ago', '1 day ago', 'Just now', 'Today', '31 Mar', '30+ days ago'."""
    text = text.strip().lower()
    now = datetime.now(timezone.utc)
    if not text:
        return None
    if text in ("just now", "just posted", "moments ago"):
        return now
    if text == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    # "30+ days ago" pattern
    if "30+" in text or "30 +" in text:
        return now - timedelta(days=30)
    import re as _re
    m = _re.search(r"(\d+)\s*(second|minute|hour|day|week|month)s?\s*ago", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {
            "second": timedelta(seconds=n), "minute": timedelta(minutes=n),
            "hour": timedelta(hours=n), "day": timedelta(days=n),
            "week": timedelta(weeks=n), "month": timedelta(days=n * 30),
        }.get(unit, timedelta())
        return now - delta
    # Short date: "31 Mar", "2 Apr", "23 Mar" (NaukriGulf format)
    _MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
               "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    m = _re.search(r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", text)
    if m:
        day, mon = int(m.group(1)), _MONTHS[m.group(2)]
        year = now.year
        try:
            dt = datetime(year, mon, day, tzinfo=timezone.utc)
            if dt > now:
                dt = datetime(year - 1, mon, day, tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return None


def _parse_iso_or_relative(text: str) -> datetime | None:
    """Try ISO date first, then relative."""
    if not text:
        return None
    # ISO format: 2026-04-01, 2026-04-01T12:00:00
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass
    return _parse_relative_date(text)


def _is_within_24h(dt: datetime | None) -> bool:
    """Return True if dt is within last 24 hours or unknown (None)."""
    if dt is None:
        return True  # unknown date — include by default
    return dt >= _24H_AGO()


# Session files directory (mounted /data volume)
_SESSION_DIR: Path | None = None


def _session_dir() -> Path:
    global _SESSION_DIR
    if _SESSION_DIR is None:
        base = os.environ.get("AIMS_WORKSPACE", "/data")
        _SESSION_DIR = Path(base) / "config" / "scraper_sessions"
        _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return _SESSION_DIR


def _session_path(site: str) -> Path:
    return _session_dir() / f"{site}.json"


def session_exists(site: str) -> bool:
    p = _session_path(site)
    return p.exists() and p.stat().st_size > 100


# ── Stealth helpers ───────────────────────────────────────────────────────────

async def _stealth_page(context):
    """Apply JS stealth patches to avoid headless detection."""
    await context.add_init_script("""
        // Basic webdriver / automation flags
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
        Object.defineProperty(navigator, 'permissions', {
            get: () => ({query: () => Promise.resolve({state: 'granted'})})
        });
        // Hardware / screen signals
        Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
        Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
        Object.defineProperty(screen, 'colorDepth', {get: () => 24});
        // Canvas fingerprint noise
        const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (type === 'image/png') {
                const ctx2d = this.getContext('2d');
                if (ctx2d) {
                    ctx2d.fillStyle = 'rgba(0,0,0,' + (Math.random() * 0.0001) + ')';
                    ctx2d.fillRect(0, 0, 1, 1);
                }
            }
            return _origToDataURL.apply(this, arguments);
        };
        const _origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
            const data = _origGetImageData.call(this, x, y, w, h);
            for (let i = 0; i < data.data.length; i += 100) {
                data.data[i] ^= Math.floor(Math.random() * 3);
            }
            return data;
        };
        // WebGL fingerprint masking
        const _origGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return _origGetParameter.call(this, param);
        };
        try {
            const _origGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(param) {
                if (param === 37445) return 'Intel Inc.';
                if (param === 37446) return 'Intel Iris OpenGL Engine';
                return _origGetParameter2.call(this, param);
            };
        } catch(e) {}
        // Notification permission
        if (window.Notification) {
            Object.defineProperty(Notification, 'permission', {get: () => 'default'});
        }
    """)


async def _new_browser_context(playwright, headless: bool = True):
    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--lang=en-US",
            "--disable-http2",          # fixes ERR_HTTP2_PROTOCOL_ERROR on some sites
            "--ignore-certificate-errors",
        ],
    )
    context = await browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Asia/Dubai",
        java_script_enabled=True,
        accept_downloads=False,
    )
    await _stealth_page(context)
    return browser, context


# ── LinkedIn ──────────────────────────────────────────────────────────────────

async def login_linkedin(email: str, password: str) -> bool:
    """Login to LinkedIn and save session. Returns True on success."""
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser, ctx = await _new_browser_context(pw)
        page = await ctx.new_page()
        try:
            await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            await page.fill("#username", email)
            await asyncio.sleep(0.5)
            await page.fill("#password", password)
            await asyncio.sleep(0.5)
            await page.click('button[type="submit"]')
            await page.wait_for_url("**/feed**", timeout=20000)
            storage = await ctx.storage_state()
            _session_path("linkedin").write_text(json.dumps(storage))
            logger.info("login_linkedin: success, session saved")
            return True
        except Exception as e:
            logger.warning("login_linkedin failed: %s", e)
            return False
        finally:
            await browser.close()


async def scrape_linkedin(pages: int = 20) -> list[dict]:
    """Scrape LinkedIn public job search — all jobs from last 24h, no login needed."""
    from playwright.async_api import async_playwright
    import re

    max_pages = pages  # safety cap
    queries = os.environ.get("JOB_FILTER_SOURCE_QUERIES", "maintenance manager;reliability manager").split(";")
    locations = os.environ.get("JOB_FILTER_SOURCE_LOCATIONS", "Dubai;Abu Dhabi;Qatar").split(";")

    results: list[dict] = []
    seen_urls: set[str] = set()

    async with async_playwright() as pw:
        browser, ctx = await _new_browser_context(pw)
        page = await ctx.new_page()
        for query in queries:
            for location in locations:
                for pg in range(max_pages):
                    start = pg * 25
                    url = (
                        f"https://www.linkedin.com/jobs/search/"
                        f"?keywords={query.replace(' ', '%20')}"
                        f"&location={location.replace(' ', '%20')}"
                        f"&f_TPR=r86400&sortBy=DD&start={start}"
                    )
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(3)
                        # Check if redirected to login/authwall
                        if "linkedin.com/login" in page.url or "authwall" in page.url:
                            logger.warning("scrape_linkedin: blocked by authwall, trying next query")
                            break
                        cards = await page.query_selector_all(".job-search-card, .base-search-card, .jobs-search__results-list > li")
                        if not cards:
                            logger.info("scrape_linkedin: no cards query=%r loc=%r page=%d", query, location, pg + 1)
                            break
                        found_old = False
                        dated_count = 0
                        new_on_page = 0
                        for card in cards:
                            try:
                                title_el = await card.query_selector("h3, .base-search-card__title")
                                link_el = await card.query_selector("a.base-card__full-link, a[href*='/jobs/view/']")
                                company_el = await card.query_selector(".base-search-card__subtitle, h4")
                                location_el = await card.query_selector(".job-search-card__location")
                                time_el = await card.query_selector("time[datetime]")
                                title = (await title_el.inner_text()).strip() if title_el else ""
                                href = await link_el.get_attribute("href") if link_el else ""
                                company = (await company_el.inner_text()).strip() if company_el else ""
                                loc = (await location_el.inner_text()).strip() if location_el else ""
                                date_raw = await time_el.get_attribute("datetime") if time_el else ""
                                if not date_raw and time_el:
                                    date_raw = (await time_el.inner_text()).strip()
                                pub_dt = _parse_iso_or_relative(date_raw or "")
                                if pub_dt is not None:
                                    dated_count += 1
                                if not _is_within_24h(pub_dt):
                                    logger.info("scrape_linkedin: old job (%s) query=%r — stopping page", date_raw, query)
                                    found_old = True
                                    break
                                if not title or not href:
                                    continue
                                m = re.search(r'linkedin\.com/jobs/view/(\d+)', href)
                                clean_url = f"https://www.linkedin.com/jobs/view/{m.group(1)}" if m else href.split("?")[0]
                                if clean_url not in seen_urls:
                                    seen_urls.add(clean_url)
                                    new_on_page += 1
                                    results.append({"title": title, "url": clean_url,
                                                    "company": company, "location": loc,
                                                    "source": "linkedin", "description": "",
                                                    "pub_dt": pub_dt})
                            except Exception:
                                continue
                        logger.info("scrape_linkedin query=%r loc=%r page=%d cards=%d new=%d dated=%d", query, location, pg + 1, len(cards), new_on_page, dated_count)
                        if found_old:
                            break
                        # Stop if all results are duplicates (LinkedIn repeating same page)
                        if new_on_page == 0:
                            logger.info("scrape_linkedin: all duplicates query=%r loc=%r — stopping", query, location)
                            break
                        # Safety: if no dates found on page, limit to 3 pages max
                        if dated_count == 0 and pg >= 2:
                            logger.info("scrape_linkedin: no dates on 3 pages query=%r loc=%r — stopping", query, location)
                            break
                        await asyncio.sleep(2.5)
                    except Exception as e:
                        logger.warning("scrape_linkedin error query=%r loc=%r pg=%d: %s", query, location, pg, e)
                        break
        await browser.close()
    logger.info("scrape_linkedin total=%d", len(results))
    return results


# ── OTP / Passkey callback ────────────────────────────────────────────────────
# The bot sets this queue before login so Playwright can wait for the user's code.
# cmd_otp in job_filter_bot.py puts the code here.
_otp_queue: asyncio.Queue[str] | None = None


def set_otp_queue(q: asyncio.Queue[str] | None) -> None:
    global _otp_queue
    _otp_queue = q


async def _wait_for_otp(timeout_sec: int = 90) -> str | None:
    """Wait up to timeout_sec for user to send /otp <code> via Telegram."""
    if _otp_queue is None:
        return None
    try:
        code = await asyncio.wait_for(_otp_queue.get(), timeout=timeout_sec)
        return code.strip()
    except asyncio.TimeoutError:
        logger.warning("otp_wait: timed out after %ds", timeout_sec)
        return None


# ── Indeed ────────────────────────────────────────────────────────────────────

# Selectors that indicate Indeed is asking for verification
_INDEED_VERIFY_SELECTORS = [
    'input[name="code"]',               # email/SMS OTP input
    'input[autocomplete="one-time-code"]',
    '[data-testid="verification-code-input"]',
    'input[name="oneTimePassword"]',
]

# Passkey screen — Indeed may offer "use a different method" link
_INDEED_PASSKEY_SELECTORS = [
    '[data-testid="passkey-prompt"]',
    'button[data-testid="use-different-method"]',
    'a[href*="challengeType=passkey"]',
    'text=Use a passkey',
    'text=Verify your identity',
]


async def login_indeed(
    email: str,
    password: str,
    notify_cb=None,          # async callable(text, screenshot_bytes|None) → sends to Telegram
) -> bool:
    """
    Login to Indeed AE with interactive OTP/passkey support.

    If Indeed shows a verification screen, sends a screenshot + message
    via notify_cb, then waits up to 90s for /otp <code> from Telegram.
    Tries 'Use a different method' link to switch from passkey to email code.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser, ctx = await _new_browser_context(pw)
        page = await ctx.new_page()
        async def _handle_otp_screen() -> bool:
            """Detect OTP input, notify user, wait for code. Returns True if handled."""
            otp_input = None
            for sel in _INDEED_VERIFY_SELECTORS:
                try:
                    otp_input = await page.wait_for_selector(sel, timeout=3000)
                    if otp_input:
                        break
                except Exception:
                    continue
            if not otp_input:
                return False
            logger.info("login_indeed: OTP screen detected, url=%s", page.url)
            screenshot = await page.screenshot()
            if notify_cb:
                await notify_cb(
                    "Indeed: введи код подтверждения из письма.\n"
                    "Отправь: /otp <код> (90 сек)",
                    screenshot,
                )
            code = await _wait_for_otp(timeout_sec=90)
            if not code:
                if notify_cb:
                    await notify_cb("Время вышло — код не получен. Indeed login отменён.", None)
                return False
            await otp_input.fill(code)
            await asyncio.sleep(0.4)
            submit = await page.query_selector('button[type="submit"]')
            if submit:
                await submit.click()
            await asyncio.sleep(3)
            return True

        async def _try_switch_from_passkey() -> bool:
            """If passkey screen shown, click 'Use a different method'. Returns True if switched."""
            for sel in _INDEED_PASSKEY_SELECTORS:
                try:
                    el = await page.wait_for_selector(sel, timeout=2500)
                    if el:
                        logger.info("login_indeed: passkey/verify screen at %s", page.url)
                        # Try all known "alternate method" selectors
                        for alt_sel in [
                            'button:has-text("Use a different sign in option")',
                            'button:has-text("different")',
                            'button:has-text("email")',
                            'a:has-text("different")',
                            'a:has-text("email code")',
                            '[data-testid="use-different-method"]',
                            'button:has-text("Sign in another way")',
                            'a[href*="challengeType=email"]',
                        ]:
                            try:
                                alt = await page.query_selector(alt_sel)
                                if alt:
                                    await alt.click()
                                    await asyncio.sleep(2)
                                    return True
                            except Exception:
                                continue
                        # No alternate button — send screenshot and inform user
                        screenshot = await page.screenshot()
                        if notify_cb:
                            await notify_cb(
                                "Indeed: экран passkey — кнопка 'другой метод' не найдена.\n"
                                "Если видишь код в письме — отправь /otp <код>.\n"
                                "Иначе отключи passkey в настройках Indeed и повтори /login_sites",
                                screenshot,
                            )
                        # Still try to wait for OTP in case email code was auto-sent
                        await _handle_otp_screen()
                        return True
                except Exception:
                    continue
            return False

        try:
            # Step 1: Navigate to login
            await page.goto("https://ae.indeed.com/account/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Step 2: Enter email and click Continue
            email_input = await page.query_selector('input[type="email"], input[name="__email"]')
            if email_input:
                await email_input.fill(email)
                await asyncio.sleep(0.6)
                continue_btn = await page.query_selector(
                    'button[type="submit"], #loginFormSubmit, button:has-text("Continue"), button:has-text("Next")'
                )
                if continue_btn:
                    await continue_btn.click()
                    await asyncio.sleep(2.5)

            # Step 3: Detect what screen appeared next — passkey, password, or OTP
            # Check for passkey/verify screen first (Indeed shows this instead of password now)
            switched = await _try_switch_from_passkey()

            if not switched:
                # Step 4a: Classic password field (older flow or after switching)
                try:
                    pwd_input = await page.wait_for_selector(
                        'input[type="password"], input[name="__password"]', timeout=4000
                    )
                    if pwd_input:
                        await pwd_input.fill(password)
                        await asyncio.sleep(0.5)
                        submit = await page.query_selector('button[type="submit"], #loginFormSubmit')
                        if submit:
                            await submit.click()
                        await asyncio.sleep(3)
                except Exception:
                    pass

            # Step 4b: OTP after password or after switching from passkey
            await _handle_otp_screen()

            # Step 5: Check if still on auth page — another OTP round
            if any(x in page.url for x in ("login", "challenge", "verify", "auth")):
                await _try_switch_from_passkey()
                await _handle_otp_screen()

            # Step 6: Save session regardless of URL (cookies may still be valid)
            storage = await ctx.storage_state()
            _session_path("indeed").write_text(json.dumps(storage))
            logger.info("login_indeed: session saved, final_url=%s", page.url)
            if notify_cb:
                final_ok = not any(x in page.url for x in ("login", "challenge", "verify"))
                status = "сессия сохранена ✓" if final_ok else "сессия сохранена (проверь вход вручную)"
                await notify_cb(f"Indeed: {status}", None)
            return True

        except Exception as e:
            logger.warning("login_indeed failed: %s", e)
            if notify_cb:
                await notify_cb(f"Indeed login error: {e!s}"[:200], None)
            return False
        finally:
            await browser.close()


async def scrape_indeed(pages: int = 20) -> list[dict]:
    """Scrape Indeed AE public job search — all jobs from last 24h, no login needed."""
    from playwright.async_api import async_playwright
    import re

    max_pages = pages  # safety cap
    queries = os.environ.get("JOB_FILTER_SOURCE_QUERIES", "maintenance manager").split(";")
    # LinkedIn-only regions (no Indeed presence)
    _linkedin_only = {"australia", "perth", "sydney", "melbourne", "brisbane",
                      "malaysia", "borneo", "singapore"}
    # USA locations use indeed.com; Gulf uses ae.indeed.com
    _usa_locations = {"united states", "usa", "houston", "texas"}
    all_locs = [l.strip() for l in os.environ.get("JOB_FILTER_SOURCE_LOCATIONS", "Dubai").split(";")
                if l.strip().lower() not in _linkedin_only]

    results: list[dict] = []
    seen_urls: set[str] = set()

    async with async_playwright() as pw:
        browser, ctx = await _new_browser_context(pw)
        page = await ctx.new_page()
        for query in queries:
            for location in all_locs:
                is_usa = location.strip().lower() in _usa_locations
                domain = "www.indeed.com" if is_usa else "ae.indeed.com"
                for pg in range(max_pages):
                    url = (
                        f"https://{domain}/jobs?"
                        f"q={query.replace(' ', '+')}"
                        f"&l={location.replace(' ', '+')}"
                        f"&sort=date&fromage=1&start={pg * 10}"
                    )
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(3)
                        if "indeed.com/account" in page.url or "indeed.com/login" in page.url:
                            logger.warning("scrape_indeed: redirected to login, skipping")
                            break
                        cards = await page.query_selector_all('[data-jk], .job_seen_beacon')
                        if not cards:
                            logger.info("scrape_indeed: no cards query=%r loc=%r page=%d", query, location, pg + 1)
                            break
                        found_old = False
                        for card in cards:
                            try:
                                title_el = await card.query_selector('h2.jobTitle a, [data-testid="job-title"] a, h2 a')
                                company_el = await card.query_selector('[data-testid="company-name"], .companyName')
                                loc_el = await card.query_selector('[data-testid="text-location"], .companyLocation')
                                date_el = await card.query_selector('.date, [data-testid="myJobsStateDate"], .result-footer .date')
                                title = (await title_el.inner_text()).strip() if title_el else ""
                                href = await title_el.get_attribute("href") if title_el else ""
                                company = (await company_el.inner_text()).strip() if company_el else ""
                                loc = (await loc_el.inner_text()).strip() if loc_el else ""
                                date_raw = (await date_el.inner_text()).strip() if date_el else ""
                                pub_dt = _parse_relative_date(date_raw) if date_raw else None
                                if not _is_within_24h(pub_dt):
                                    logger.info("scrape_indeed: old job (%s) query=%r — stopping page", date_raw, query)
                                    found_old = True
                                    break
                                if not title:
                                    continue
                                jk_match = re.search(r'jk=([a-f0-9]+)', href or "")
                                if jk_match:
                                    clean_url = f"https://{domain}/viewjob?jk={jk_match.group(1)}"
                                else:
                                    clean_url = f"https://{domain}{href}" if href and href.startswith("/") else href
                                if clean_url and clean_url not in seen_urls:
                                    seen_urls.add(clean_url)
                                    results.append({"title": title, "url": clean_url,
                                                    "company": company, "location": loc,
                                                    "source": "indeed", "description": "",
                                                    "pub_dt": pub_dt})
                            except Exception:
                                continue
                        logger.info("scrape_indeed query=%r loc=%r page=%d found=%d", query, location, pg + 1, len(cards))
                        if found_old:
                            break
                        await asyncio.sleep(2.5)
                    except Exception as e:
                        logger.warning("scrape_indeed error: %s", e)
                        break
        await browser.close()
    logger.info("scrape_indeed total=%d", len(results))
    return results


# ── NaukriGulf ────────────────────────────────────────────────────────────────
# NaukriGulf is protected by Cloudflare — Playwright headless is fully blocked.
# Strategy: use curl_cffi (Chrome TLS fingerprint) for HTTP requests.
# Login via curl_cffi session (POST to API endpoint) + store cookies.

_NG_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

_NG_SEARCH_TERMS = [
    "maintenance-manager",
    "reliability-engineer",
    "asset-integrity",
    "integrity-engineer",
    "technical-authority",
    "senior-engineer-maintenance",
    "senior-engineer-integrity",
    "functional-safety",
    "instrument-engineer",
    "lead-maintenance",
    "alarm-management",
    "principal-engineer",
]

_NG_LOC_MAP = {
    "Dubai": "uae",
    "Abu Dhabi": "uae",
    "UAE": "uae",
    "United Arab Emirates": "uae",
    "Qatar": "qatar",
    "Saudi Arabia": "ksa",
    "KSA": "ksa",
    "Kuwait": "kuwait",
    "Oman": "oman",
    "Bahrain": "bahrain",
}


def _parse_naukrigulf_html(html_text: str, location_label: str) -> list[dict]:
    """
    Extract job listings from a NaukriGulf search-results page.
    Parses srp-tuple blocks with designation-title, info-org, info-loc, description.
    """
    import re
    import html as html_mod

    jobs: list[dict] = []
    seen_urls: set[str] = set()

    # Each job card is a <div class="... srp-tuple">, parse via <a class="info-position"> blocks
    for m in re.finditer(
        r'<a[^>]+href="(https://www\.naukrigulf\.com/[^"]+)"[^>]*class="info-position[^"]*"[^>]*>(.*?)</a>',
        html_text,
        re.DOTALL,
    ):
        url = m.group(1).strip()
        inner = m.group(2)
        title_m = re.search(r'<p class="designation-title">(.*?)</p>', inner, re.DOTALL)
        title = html_mod.unescape(title_m.group(1).strip()) if title_m else ""
        # Company may be inside the same <a> or in a sibling <a class="info-org">
        comp_m = re.search(r'class="info-org[^"]*"[^>]*title="([^"]*)"', inner)
        company = html_mod.unescape(comp_m.group(1).strip()) if comp_m else ""
        if not title or url in seen_urls:
            continue
        seen_urls.add(url)
        # Look for company in sibling <a class="info-org"> after this match
        if not company:
            after = html_text[m.end():m.end() + 500]
            comp_m2 = re.search(r'class="info-org[^"]*"[^>]*title="([^"]*)"', after)
            if comp_m2:
                company = html_mod.unescape(comp_m2.group(1).strip())
        # Location from sibling <li class="info-loc">, date from <span class="time">
        after_block = html_text[m.end():m.end() + 1200]
        loc_m = re.search(r'class="info-loc[^"]*"[^>]*>.*?<span>([^<]+)</span>', after_block, re.DOTALL)
        location = html_mod.unescape(loc_m.group(1).strip()) if loc_m else location_label
        # Description
        desc_m = re.search(r'class="description">(.*?)</p>', after_block, re.DOTALL)
        description = html_mod.unescape(desc_m.group(1).strip()) if desc_m else ""
        # Date — NaukriGulf uses <span class="time">31 Mar</span> or "30+ days ago"
        date_m = re.search(r'class="time"[^>]*>(.*?)</(?:span|div|li)', after_block, re.DOTALL | re.IGNORECASE)
        if not date_m:
            date_m = re.search(r'(\d+\s+(?:day|hour|minute|week|month)s?\s+ago|just\s+now|today|\d{1,2}\s+\w{3})', after_block, re.IGNORECASE)
        date_raw = html_mod.unescape(date_m.group(1).strip()) if date_m else ""
        pub_dt = _parse_relative_date(date_raw) if date_raw else None
        jobs.append({
            "title": title, "url": url, "company": company,
            "location": location, "source": "naukrigulf", "description": description[:300],
            "pub_dt": pub_dt, "date_raw": date_raw,
        })

    return jobs


# FlareSolverr URL — Docker service on same network
_FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191/v1")


async def _flaresolverr_get(url: str, timeout: int = 90) -> dict | None:
    """
    Call FlareSolverr to solve Cloudflare JS challenge and return page solution dict.
    Returns solution dict with keys: cookies, userAgent, response (HTML), status.
    Returns None on failure.
    """
    import httpx
    payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}
    try:
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            resp = await client.post(_FLARESOLVERR_URL, json=payload)
        data = resp.json()
        if data.get("status") == "ok" and "solution" in data:
            sol = data["solution"]
            logger.info(
                "flaresolverr: solved url=%s status=%s cookies=%d ua=%s",
                url, sol.get("status"), len(sol.get("cookies", [])),
                sol.get("userAgent", "")[:60],
            )
            return sol
        logger.warning("flaresolverr: failed status=%s msg=%s", data.get("status"), data.get("message", "")[:100])
        return None
    except Exception as e:
        logger.warning("flaresolverr: error for %s: %s", url, e)
        return None


async def login_naukrigulf(email: str = "", password: str = "") -> bool:
    """
    Get NaukriGulf Cloudflare clearance via FlareSolverr.
    Saves cf_clearance + session cookies for scrape_naukrigulf().
    Public search works with just CF clearance — no login API needed.
    """
    solution = await _flaresolverr_get("https://www.naukrigulf.com/", timeout=90)
    if not solution:
        logger.warning("login_naukrigulf: FlareSolverr could not get CF clearance")
        return False

    cf_cookies = {c["name"]: c["value"] for c in solution.get("cookies", [])}
    user_agent = solution.get("userAgent", "")

    cookies_list = [
        {"name": k, "value": v, "domain": ".naukrigulf.com", "path": "/"}
        for k, v in cf_cookies.items()
    ]
    storage = {"cookies": cookies_list, "origins": [], "user_agent": user_agent}
    _session_path("naukrigulf").write_text(json.dumps(storage))
    logger.info("login_naukrigulf: CF clearance saved (%d cookies, ua=%s)", len(cookies_list), user_agent[:60])
    return True


async def scrape_naukrigulf(pages: int = 3) -> list[dict]:
    """
    Scrape NaukriGulf via FlareSolverr (every request proxied through real Chrome).

    cf_clearance cookies are bound to the TLS fingerprint of the browser that solved
    the challenge, so curl_cffi cannot reuse them.  Each search page is fetched
    through FlareSolverr directly (~5-10s per page, but 100% reliable).
    """
    locations_raw = os.environ.get("JOB_FILTER_SOURCE_LOCATIONS", "Dubai").split(";")
    ng_locs: dict[str, str] = {}
    for loc in locations_raw:
        loc = loc.strip()
        code = _NG_LOC_MAP.get(loc)
        if code:
            ng_locs[code] = loc
    if not ng_locs:
        ng_locs["uae"] = "UAE"

    results: list[dict] = []
    seen_urls: set[str] = set()

    for term in _NG_SEARCH_TERMS:
        for loc_code, loc_label in ng_locs.items():
            for pg in range(pages):
                page_num = pg + 1
                url = f"https://www.naukrigulf.com/{term}-jobs-in-{loc_code}-{page_num}"
                solution = await _flaresolverr_get(url, timeout=60)
                if not solution:
                    logger.warning("scrape_naukrigulf: FlareSolverr failed for %s", url)
                    break
                body = solution.get("response", "")
                page_title = _extract_title(body)
                logger.info(
                    "scrape_naukrigulf: len=%d term=%r loc=%r page=%d title=%r",
                    len(body), term, loc_code, page_num, page_title,
                )
                # Detect Cloudflare challenge page
                if page_title == "Naukrigulf" and len(body) < 50000:
                    logger.warning("scrape_naukrigulf: CF challenge page for %s — skipping term", url)
                    break
                jobs = _parse_naukrigulf_html(body, loc_label)
                if not jobs:
                    logger.info("scrape_naukrigulf: no jobs parsed — term=%r loc=%r page=%d", term, loc_code, page_num)
                    break
                found_old = False
                for job in jobs:
                    if not _is_within_24h(job.get("pub_dt")):
                        logger.info("scrape_naukrigulf: old job (%s) term=%r — stopping", job.get("date_raw", ""), term)
                        found_old = True
                        break
                    u = job.get("url", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        results.append(job)
                logger.info("scrape_naukrigulf: term=%r loc=%r page=%d found=%d", term, loc_code, page_num, len(jobs))
                if found_old:
                    break
                await asyncio.sleep(1)

    logger.info("scrape_naukrigulf total=%d", len(results))
    return results


# ── JobLeads ──────────────────────────────────────────────────────────────────

async def login_jobleads(email: str, password: str) -> bool:
    """
    Login to JobLeads via Playwright.
    JobLeads is a Vue.js SPA. The homepage shows a location banner that must be
    dismissed first, then "Log in" in the header opens a modal with the form.
    """
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser, ctx = await _new_browser_context(pw)
        page = await ctx.new_page()
        try:
            await page.goto(
                "https://www.jobleads.com/external-home",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(3)

            # Step 1: Dismiss the location banner ("Continue" button at the top)
            for sel in [
                'button:has-text("Continue")',
                'a:has-text("Continue")',
                'button.continue',
            ]:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        logger.info("login_jobleads: dismissed location banner")
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue

            # Step 2: Click "Log in" button in header
            login_btn = None
            for sel in [
                'header button:has-text("Log in")',
                'button:has-text("Log in")',
                'a:has-text("Log in")',
            ]:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        login_btn = btn
                        break
                except Exception:
                    continue
            if login_btn:
                await login_btn.click()
                logger.info("login_jobleads: clicked Log in button")
                await asyncio.sleep(3)
            else:
                # Try navigating directly to login modal URL
                await page.goto(
                    "https://www.jobleads.com/login",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                await asyncio.sleep(3)

            # Step 3: Find email input in the modal
            email_input = None
            for sel in [
                'input[type="email"]',
                'input[name="email"]',
                'input[placeholder*="mail" i]',
                'input[placeholder*="Email"]',
                'input[autocomplete="email"]',
            ]:
                email_input = await page.query_selector(sel)
                if email_input and await email_input.is_visible():
                    break
                email_input = None

            if not email_input:
                # Maybe a "Log in with email" button needs clicking first
                for sel in [
                    'button:has-text("email")',
                    'button:has-text("Email")',
                    'a:has-text("Log in with email")',
                    'button:has-text("Continue with email")',
                ]:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            await btn.click()
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        continue
                email_input = await page.query_selector('input[type="email"], input[name="email"]')

            if not email_input:
                logger.warning("login_jobleads: email input not found, url=%s", page.url)
                screenshot = await page.screenshot()
                Path(_session_dir() / "jobleads_debug.png").write_bytes(screenshot)
                return False

            await email_input.fill(email)
            await asyncio.sleep(0.5)

            # Find and fill password
            pwd_input = await page.query_selector(
                'input[type="password"], input[name="password"]'
            )
            if pwd_input:
                await pwd_input.fill(password)
                await asyncio.sleep(0.5)

            # Submit — look for various button patterns
            for btn_sel in [
                'button[type="submit"]',
                'button:has-text("Log in")',
                'button:has-text("Sign in")',
                'button:has-text("Continue")',
                'form button',
            ]:
                submit = await page.query_selector(btn_sel)
                if submit and await submit.is_visible():
                    await submit.click()
                    break

            await asyncio.sleep(4)

            # Check if login succeeded
            final_url = page.url
            logger.info("login_jobleads: final_url=%s", final_url)
            if any(x in final_url for x in ("my-account", "search/jobs", "dashboard", "home")):
                # Check it's not the external-home login page still
                if "modal=login" not in final_url:
                    storage = await ctx.storage_state()
                    _session_path("jobleads").write_text(json.dumps(storage))
                    logger.info("login_jobleads: success, session saved")
                    return True

            # Save session anyway — cookies may still be valid
            storage = await ctx.storage_state()
            _session_path("jobleads").write_text(json.dumps(storage))
            logger.info("login_jobleads: session saved (login may have partially succeeded), url=%s", final_url)
            return "modal=login" not in final_url

        except Exception as e:
            logger.warning("login_jobleads failed: %s", e)
            # Save debug screenshot
            try:
                screenshot = await page.screenshot()
                Path(_session_dir() / "jobleads_debug.png").write_bytes(screenshot)
            except Exception:
                pass
            return False
        finally:
            await browser.close()


async def scrape_jobleads(pages: int = 2) -> list[dict]:
    """Scrape JobLeads search pages using saved authenticated session."""
    if not session_exists("jobleads"):
        logger.warning("scrape_jobleads: no session, skipping")
        return []
    from playwright.async_api import async_playwright

    queries = os.environ.get("JOB_FILTER_SOURCE_QUERIES", "maintenance manager;reliability manager").split(";")
    locations = os.environ.get("JOB_FILTER_SOURCE_LOCATIONS", "Dubai;Abu Dhabi;Qatar").split(";")

    results: list[dict] = []
    seen_urls: set[str] = set()

    async with async_playwright() as pw:
        browser, ctx = await _new_browser_context(pw)
        try:
            storage = json.loads(_session_path("jobleads").read_text())
            await ctx.add_cookies(storage.get("cookies", []))
        except Exception as e:
            logger.warning("scrape_jobleads: failed to load session: %s", e)
            await browser.close()
            return []

        page = await ctx.new_page()
        for query in queries:
            for location in locations:
                for pg in range(1, pages + 1):
                    url = (
                        "https://www.jobleads.com/search/jobs"
                        f"?q={quote_plus(query)}&location={quote_plus(location)}&page={pg}"
                    )
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(2.5)
                        cards = await page.query_selector_all('a[href*="/job/"], a[href*="/jobs/"], [data-testid*="job"] a')
                        if not cards:
                            break
                        for card in cards:
                            try:
                                title = ((await card.inner_text()) or "").strip()
                                href = await card.get_attribute("href")
                                if not href:
                                    continue
                                full_url = f"https://www.jobleads.com{href}" if href.startswith("/") else href
                                if "jobleads.com" not in full_url:
                                    continue
                                if not title:
                                    title = "JobLeads Vacancy"
                                if full_url not in seen_urls:
                                    seen_urls.add(full_url)
                                    results.append(
                                        {
                                            "title": title[:160],
                                            "url": full_url,
                                            "company": "",
                                            "location": location,
                                            "source": "jobleads",
                                            "description": "",
                                        }
                                    )
                            except Exception:
                                continue
                    except Exception as e:
                        logger.warning("scrape_jobleads error query=%r loc=%r page=%d: %s", query, location, pg, e)
                        break
        await browser.close()
    logger.info("scrape_jobleads total=%d", len(results))
    return results


def _extract_title(html_text: str) -> str:
    """Extract <title> from HTML for logging."""
    import re
    m = re.search(r"<title>([^<]{0,80})</title>", html_text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# ── Rigzone ───────────────────────────────────────────────────────────────────

async def scrape_rigzone(pages: int = 10) -> list[dict]:
    """Scrape Rigzone via FlareSolverr (Cloudflare-protected)."""
    import re
    import html as html_mod

    results: list[dict] = []
    seen_urls: set[str] = set()
    search_terms = ["maintenance", "reliability", "asset integrity", "integrity engineer"]

    for term in search_terms:
        for pg in range(pages):
            url = f"https://www.rigzone.com/oil/jobs/search/?q={term.replace(' ', '+')}&pg={pg + 1}&sort=posted"
            solution = await _flaresolverr_get(url, timeout=60)
            if not solution:
                logger.warning("scrape_rigzone: flaresolverr failed term=%r page=%d", term, pg + 1)
                break
            html = solution.get("response", "")
            if len(html) < 500:
                break
            found = 0
            found_old = False
            for m in re.finditer(
                r'href="(/oil/jobs/postings/[^"]+)"[^>]*>([^<]{5,100})</a>',
                html,
            ):
                href, title = m.group(1), html_mod.unescape(m.group(2).strip())
                clean_url = f"https://www.rigzone.com{href}"
                # Look for date near this job link (within next 500 chars)
                after = html[m.end():m.end() + 500]
                date_m = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', after)
                if not date_m:
                    date_m = re.search(r'(\d+\s+(?:day|hour|minute|week|month)s?\s+ago|just\s+now|today)', after, re.IGNORECASE)
                date_raw = date_m.group(1).strip() if date_m else ""
                pub_dt = _parse_iso_or_relative(date_raw) if date_raw else None
                if not _is_within_24h(pub_dt):
                    logger.info("scrape_rigzone: old job (%s) term=%r — stopping", date_raw, term)
                    found_old = True
                    break
                if clean_url not in seen_urls:
                    seen_urls.add(clean_url)
                    results.append({"title": title, "url": clean_url,
                                    "company": "", "location": "",
                                    "source": "rigzone", "description": "",
                                    "pub_dt": pub_dt})
                    found += 1
            logger.info("scrape_rigzone term=%r page=%d found=%d", term, pg + 1, found)
            if not found or found_old:
                break
    logger.info("scrape_rigzone total=%d", len(results))
    return results


# ── MyCareersFuture (Singapore government job portal) ────────────────────────

_MCF_API = "https://api.mycareersfuture.gov.sg/v2/jobs"


async def scrape_mycareersfuture(pages: int = 10) -> list[dict]:
    """Scrape MyCareersFuture.gov.sg via public JSON API — Singapore jobs."""
    import httpx as _httpx

    queries = os.environ.get("JOB_FILTER_SOURCE_QUERIES", "maintenance manager").split(";")
    results: list[dict] = []
    seen_urls: set[str] = set()

    async with _httpx.AsyncClient(timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }) as client:
        for query in queries:
            for pg in range(pages):
                params = {
                    "search": query,
                    "limit": 20,
                    "page": pg,
                    "sortBy": "new_posting_date",
                }
                try:
                    await asyncio.sleep(1)
                    resp = await client.get(_MCF_API, params=params)
                    if resp.status_code != 200:
                        logger.warning("scrape_mcf status=%d query=%r page=%d", resp.status_code, query, pg)
                        break
                    data = resp.json()
                    results_list = data.get("results", [])
                    if not results_list:
                        break
                    found_old = False
                    for job in results_list:
                        title = job.get("title", "").strip()
                        uuid = job.get("uuid", "")
                        company = job.get("postedCompany", {}).get("name", "")
                        posted = job.get("metadata", {}).get("newPostingDate", "")
                        desc = job.get("description", "")[:300]
                        salary_data = job.get("salary", {})
                        salary_min = salary_data.get("minimum")
                        salary_max = salary_data.get("maximum")
                        salary_type = salary_data.get("type", {}).get("salaryType", "")
                        salary_text = ""
                        if salary_min and salary_max:
                            salary_text = f"SGD {salary_min}-{salary_max} {salary_type}"
                        clean_url = f"https://www.mycareersfuture.gov.sg/job/{uuid}" if uuid else ""
                        pub_dt = _parse_iso_or_relative(posted) if posted else None
                        if not _is_within_24h(pub_dt):
                            logger.info("scrape_mcf: old job (%s) query=%r — stopping", posted, query)
                            found_old = True
                            break
                        if not title or not clean_url or clean_url in seen_urls:
                            continue
                        seen_urls.add(clean_url)
                        results.append({
                            "title": title, "url": clean_url, "company": company,
                            "location": "Singapore", "source": "mycareersfuture",
                            "description": desc + (" " + salary_text if salary_text else ""),
                            "pub_dt": pub_dt,
                        })
                    logger.info("scrape_mcf query=%r page=%d found=%d", query, pg, len(results_list))
                    if found_old or len(results_list) < 10:
                        break
                except Exception as e:
                    logger.warning("scrape_mcf error query=%r page=%d: %s", query, pg, e)
                    break

    logger.info("scrape_mcf total=%d", len(results))
    return results


# ── JobStreet (Malaysia / Singapore / Borneo) ────────────────────────────────

_JS_DOMAINS = {
    "Malaysia": "www.jobstreet.com.my",
    "Borneo": "www.jobstreet.com.my",
    "Singapore": "www.jobstreet.com.sg",
}
_JS_LOC_MAP = {
    "Malaysia": "Kuala Lumpur",
    "Borneo": "Miri",  # O&G hub in Sarawak
    "Singapore": "",    # no sub-location needed
}


async def scrape_jobstreet(pages: int = 5) -> list[dict]:
    """Scrape JobStreet (MY/SG) via FlareSolverr — Cloudflare-protected."""
    import html as html_mod

    locations_raw = os.environ.get("JOB_FILTER_SOURCE_LOCATIONS", "").split(";")
    queries = os.environ.get("JOB_FILTER_SOURCE_QUERIES", "maintenance manager").split(";")
    # Only process JobStreet-relevant locations
    js_targets: list[tuple[str, str]] = []  # (domain, location_query)
    for loc in locations_raw:
        loc = loc.strip()
        if loc in _JS_DOMAINS:
            js_targets.append((_JS_DOMAINS[loc], _JS_LOC_MAP.get(loc, "")))
    if not js_targets:
        return []

    results: list[dict] = []
    seen_urls: set[str] = set()

    for domain, loc_query in js_targets:
        for query in queries:
            for pg in range(pages):
                q_enc = query.replace(" ", "-")
                loc_enc = loc_query.replace(" ", "-") if loc_query else ""
                if loc_query:
                    url = f"https://{domain}/{q_enc}-jobs-in-{loc_enc}?pg={pg + 1}&sortBy=posting-date"
                else:
                    url = f"https://{domain}/{q_enc}-jobs?pg={pg + 1}&sortBy=posting-date"
                solution = await _flaresolverr_get(url, timeout=60)
                if not solution:
                    logger.warning("scrape_jobstreet: FlareSolverr failed for %s", url)
                    break
                body = solution.get("response", "")
                if len(body) < 1000:
                    break
                # Parse job cards — JobStreet uses article tags or data-job-id
                found = 0
                found_old = False
                for m in re.finditer(
                    r'<a[^>]+href="(https://www\.jobstreet\.com\.[^"]+/job/[^"]+)"[^>]*>',
                    body,
                ):
                    job_url = m.group(1).split("?")[0]
                    after = body[m.end():m.end() + 1000]
                    # Title
                    title_m = re.search(r'>([^<]{5,120})</(?:a|h[1-4]|span)', after)
                    title = html_mod.unescape(title_m.group(1).strip()) if title_m else ""
                    # Company
                    comp_m = re.search(r'class="[^"]*company[^"]*"[^>]*>([^<]+)<', after, re.IGNORECASE)
                    company = html_mod.unescape(comp_m.group(1).strip()) if comp_m else ""
                    # Location
                    loc_m = re.search(r'class="[^"]*location[^"]*"[^>]*>([^<]+)<', after, re.IGNORECASE)
                    location = html_mod.unescape(loc_m.group(1).strip()) if loc_m else loc_query or domain.split(".")[-1].upper()
                    # Date
                    date_m = re.search(r'class="[^"]*date[^"]*"[^>]*>([^<]+)<', after, re.IGNORECASE)
                    if not date_m:
                        date_m = re.search(r'(\d+[dh]\s*ago|\d+\s+(?:day|hour|minute)s?\s+ago|today|just now)', after, re.IGNORECASE)
                    date_raw = html_mod.unescape(date_m.group(1).strip()) if date_m else ""
                    pub_dt = _parse_relative_date(date_raw) if date_raw else None
                    if not _is_within_24h(pub_dt):
                        found_old = True
                        break
                    if not title or job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)
                    results.append({
                        "title": title, "url": job_url, "company": company,
                        "location": location, "source": "jobstreet",
                        "description": "", "pub_dt": pub_dt,
                    })
                    found += 1
                logger.info("scrape_jobstreet domain=%s query=%r page=%d found=%d", domain, query, pg + 1, found)
                if not found or found_old:
                    break
                await asyncio.sleep(1)

    logger.info("scrape_jobstreet total=%d", len(results))
    return results


# ── Combined scrape ───────────────────────────────────────────────────────────

async def scrape_all_sites(pages: int = 20) -> list[dict]:
    """Scrape all configured job sites sequentially.
    Each scraper self-terminates when no more results found on a page.
    The pages parameter is a safety cap only.
    """
    combined: list[dict] = []
    seen: set[str] = set()

    sites = [
        ("linkedin", scrape_linkedin),
        ("indeed", scrape_indeed),
        ("naukrigulf", scrape_naukrigulf),
        ("mycareersfuture", scrape_mycareersfuture),
        # ("jobstreet", scrape_jobstreet),  # JobStreet SPA too complex, using LinkedIn+Rigzone
        # ("jobleads", scrape_jobleads),  # temporarily disabled
        ("rigzone", scrape_rigzone),
    ]

    for site_name, scrape_fn in sites:
        try:
            jobs = await scrape_fn(pages=pages)
            for job in jobs:
                url = job.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    combined.append(job)
                elif not url:
                    combined.append(job)
        except Exception as e:
            logger.warning("scrape_all: %s failed: %s", site_name, e)

    logger.info("scrape_all_sites total=%d", len(combined))
    return combined


# ── Per-URL job description fetching ─────────────────────────────────────────

_FIRECRAWL_URL = (os.environ.get("FIRECRAWL_BASE_URL", "http://firecrawl-api:3002") or "http://firecrawl-api:3002").rstrip("/")
_DESC_MAX_CHARS = 3000


async def fetch_job_description(url: str, timeout: float = 30.0) -> str:
    """Fetch full job description text from a job posting URL.

    Tries Firecrawl (markdown) first; falls back to plain httpx GET + HTML strip.
    Returns empty string on any failure.
    """
    import httpx

    # 1. Firecrawl
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                _FIRECRAWL_URL + "/v1/scrape",
                json={"url": url, "formats": ["markdown"]},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code == 200:
            data = resp.json()
            md = (data.get("data") or {}).get("markdown") or data.get("markdown") or ""
            if len(md) > 200:
                logger.debug("fetch_job_description: firecrawl ok url=%s chars=%d", url[:80], len(md))
                return md[:_DESC_MAX_CHARS]
    except Exception as e:
        logger.debug("fetch_job_description: firecrawl error url=%s err=%s", url[:80], e)

    # 2. Plain httpx fallback — strip HTML tags
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        ) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s{2,}", " ", text).strip()
            if len(text) > 200:
                logger.debug("fetch_job_description: httpx fallback ok url=%s chars=%d", url[:80], len(text))
                return text[:_DESC_MAX_CHARS]
    except Exception as e:
        logger.debug("fetch_job_description: httpx error url=%s err=%s", url[:80], e)

    return ""


async def enrich_jobs_with_descriptions(
    jobs: list[dict],
    max_concurrent: int = 4,
    skip_if_has_description: bool = True,
) -> list[dict]:
    """Fetch full descriptions for job dicts that have a URL but empty description.

    Mutates each dict in-place: sets ``description`` and ``firecrawl_enriched=True``.
    Returns the same list.
    """
    to_enrich = [
        j for j in jobs
        if j.get("url")
        and (not skip_if_has_description or not j.get("description", "").strip())
    ]
    if not to_enrich:
        return jobs

    sem = asyncio.Semaphore(max_concurrent)

    async def _fetch_one(job: dict) -> None:
        async with sem:
            text = await fetch_job_description(job["url"])
            if text:
                job["description"] = text
                job["firecrawl_enriched"] = True

    await asyncio.gather(*[_fetch_one(j) for j in to_enrich], return_exceptions=True)
    enriched = sum(1 for j in to_enrich if j.get("firecrawl_enriched"))
    logger.info("enrich_jobs_with_descriptions: total=%d enriched=%d", len(to_enrich), enriched)
    return jobs


# ── Schedule: 7-week rotating pattern + random coefficient ───────────────────

# Base scan times per weekday (Mon=0 … Sat=5, Sun=6 skipped)
# Format: seconds from midnight
_BASE_TIMES_SEC = {
    0: 5 * 3600 + 33 * 60,   # Mon 05:33
    1: 5 * 3600 + 48 * 60,   # Tue 05:48
    2: 5 * 3600 + 47 * 60,   # Wed 05:47
    3: 6 * 3600 + 11 * 60,   # Thu 06:11
    4: 6 * 3600 + 8 * 60,    # Fri 06:08
    5: 5 * 3600 + 43 * 60,   # Sat 05:43
    # 6 = Sunday: no scan
}

# Cumulative offset per week-index (0=week1 … 6=week7), seconds
_WEEK_OFFSETS_SEC = [0, 93, 236, 152, 413, 42, 103]

# Allowed time window for scans: 05:00–07:00
_WINDOW_START = 5 * 3600   # 18000 s
_WINDOW_END   = 7 * 3600   # 25200 s


def _base_time_today(reference_monday_iso: str) -> int | None:
    """Return 7-week hardcoded base time for today (seconds from midnight), or None on Sunday."""
    from datetime import date
    today = date.today()
    weekday = today.weekday()
    if weekday == 6:
        return None
    ref = date.fromisoformat(reference_monday_iso)
    weeks_elapsed = (today - ref).days // 7
    week_idx = weeks_elapsed % 7
    base = _BASE_TIMES_SEC.get(weekday)
    if base is None:
        return None
    return base + _WEEK_OFFSETS_SEC[week_idx]


def calculate_scan_time(reference_monday_iso: str) -> int | None:
    """
    Calculate today's actual scan time using the randomised formula:

        c       = −random.uniform(0.0001, 0.1)          # small negative coefficient
        t_adj   = t_base × (1 + c)                       # shift slightly earlier
        t_final = round(t_adj / 60) × 60                 # round to nearest minute

    If t_final is within 05:00–07:00 → use it.
    Otherwise → fall back to t_base (7-week hardcoded value).
    Returns seconds-from-midnight, or None if Sunday.

    Examples:
        base=05:33 (19980s), c=−0.034 → t_adj=19300s → 05:21 ✓ use 05:21
        base=06:11 (22260s), c=−0.095 → t_adj=20144s → 05:36 ✓ use 05:36
        base=05:33 (19980s), c=−0.100 → t_adj=17982s → 04:59 ✗ use 05:33 (fallback)
    """
    import random
    t_base = _base_time_today(reference_monday_iso)
    if t_base is None:
        return None

    c = -random.uniform(0.0001, 0.1)
    t_adj = t_base * (1 + c)
    t_rounded = round(t_adj / 60) * 60

    if _WINDOW_START <= t_rounded <= _WINDOW_END:
        logger.debug(
            "scan_time: base=%02d:%02d c=%.4f → %02d:%02d (random)",
            t_base // 3600, (t_base % 3600) // 60,
            c,
            t_rounded // 3600, (t_rounded % 3600) // 60,
        )
        return t_rounded
    else:
        logger.debug(
            "scan_time: base=%02d:%02d c=%.4f → %02d:%02d out of window → fallback",
            t_base // 3600, (t_base % 3600) // 60,
            c,
            int(t_adj) // 3600, (int(t_adj) % 3600) // 60,
        )
        return t_base


def should_scan_now(
    reference_monday_iso: str,
    last_scan_date_iso: str | None,
    cached_scan_time: int | None = None,
) -> tuple[bool, int | None]:
    """
    Returns (should_run, scan_time_sec).

    scan_time_sec is today's calculated time (caller should persist it so we
    don't regenerate a new random value on every tick).
    """
    from datetime import date, datetime as dt
    today_iso = date.today().isoformat()
    if last_scan_date_iso == today_iso:
        return False, cached_scan_time  # already ran today

    # Use cached time if already calculated for today, else generate new
    scan_time = cached_scan_time if cached_scan_time is not None else calculate_scan_time(reference_monday_iso)
    if scan_time is None:
        return False, None  # Sunday

    now_sec = dt.now().hour * 3600 + dt.now().minute * 60 + dt.now().second
    return now_sec >= scan_time, scan_time
