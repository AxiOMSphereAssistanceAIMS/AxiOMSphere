from __future__ import annotations

import asyncio
import hashlib
import imaplib
import json
import logging
import os
import re
from datetime import datetime, timedelta
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from html import unescape as _html_unescape
from pathlib import Path
import tempfile

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from aims_paths import workspace_root
from job_filter import JobFilterConfig, Priority, classify_job, normalize_text
from job_sources import _merge_unique_queries
from ollama_resolve import ollama_apply_keep_alive
from cv_key_factors import (
    CvKeyFactors, MatchResult,
    extract_key_factors, extract_key_factors_async,
    score_jobs_batch,
    URGENT_THRESHOLD, DIGEST_THRESHOLD,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("job_filter_bot")

BOT_NAME = os.environ.get("JOB_FILTER_BOT_NAME", "JobFilter")


def _load_bot_token() -> str:
    raw = os.environ.get("JOB_FILTER_BOT_TOKEN", "").strip()
    if raw:
        return raw
    path = os.environ.get("JOB_FILTER_BOT_TOKEN_FILE", "").strip()
    if path:
        try:
            p = Path(path)
            if p.is_file():
                return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        except OSError as e:
            logging.getLogger("job_filter_bot").warning("JOB_FILTER_BOT_TOKEN_FILE: %s", e)
    return ""


BOT_TOKEN = _load_bot_token()
EMAIL_ENABLED = os.environ.get("JOB_FILTER_EMAIL_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
EMAIL_IMAP_HOST = os.environ.get("JOB_FILTER_IMAP_HOST", "").strip()
EMAIL_IMAP_PORT = int(os.environ.get("JOB_FILTER_IMAP_PORT", "993").strip() or "993")
EMAIL_USERNAME = os.environ.get("JOB_FILTER_EMAIL_USER", "").strip()
EMAIL_PASSWORD = os.environ.get("JOB_FILTER_EMAIL_PASSWORD", "").strip()
EMAIL_MAILBOX = os.environ.get("JOB_FILTER_EMAIL_MAILBOX", "INBOX").strip() or "INBOX"
EMAIL_ALLOWED_SENDERS_RAW = os.environ.get("JOB_FILTER_ALLOWED_SENDERS", "").strip()
ALLOWED_USER_IDS_RAW = os.environ.get("JOB_FILTER_ALLOWED_USER_IDS", "").strip()
IMAP_MODE = os.environ.get("JOB_FILTER_IMAP_MODE", "new_uid").strip().lower()
NIGHT_START_HOUR = int(os.environ.get("JOB_FILTER_NIGHT_START_HOUR", "22"))
NIGHT_END_HOUR = int(os.environ.get("JOB_FILTER_NIGHT_END_HOUR", "8"))
# Утреннее окно JobLocator (почта + RSS/источники + scraper): TZ контейнера (обычно Asia/Dubai)
MORNING_START_HOUR = int(os.environ.get("JOB_FILTER_MORNING_START_HOUR", "8"))
MORNING_END_HOUR = int(os.environ.get("JOB_FILTER_MORNING_END_HOUR", "10"))
CHECK_INTERVAL_MIN = int(os.environ.get("JOB_FILTER_CHECK_INTERVAL_MIN", "10"))
# 1 (default): один батч (почта + источники + scraper) не чаще 1 раза за календарные сутки (TZ контейнера).
#   При night_and_morning и batch_once=1 срабатывает первое попавшееся окно (ночь или утро).
#   Строго один утренний батч — JOB_FILTER_AUTO_POLL_MODE=morning (не night_and_morning).
# 0: при каждом тике в разрешённом окне (каждые CHECK_INTERVAL_MIN минут).
JOB_FILTER_VACANCY_BATCH_ONCE_PER_DAY = os.environ.get(
    "JOB_FILTER_VACANCY_BATCH_ONCE_PER_DAY", "1"
).strip().lower() in ("1", "true", "yes", "on")
REPORT_HOUR = int(os.environ.get("JOB_FILTER_REPORT_HOUR", "7"))
REPORT_MINUTE = int(os.environ.get("JOB_FILTER_REPORT_MINUTE", "50"))
REPORT_CHAT_ID = int(os.environ.get("JOB_FILTER_REPORT_CHAT_ID", "0") or "0")
# night | morning | night_and_morning | always
# morning — только утро (JOB_FILTER_MORNING_*), рекомендуется с batch_once=1 для одного запуска в день.
# night_and_morning — ночь или утро; с batch_once=1 выполнится только первое окно за сутки.
AUTO_POLL_MODE = os.environ.get("JOB_FILTER_AUTO_POLL_MODE", "morning").strip().lower()
REGISTRY_INCLUDE_NON_MATCH = os.environ.get("JOB_FILTER_REGISTRY_INCLUDE_NON_MATCH", "0").strip().lower() in {"1", "true", "yes", "on"}
LLM_ENABLED = os.environ.get("JOB_FILTER_LLM_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
# Ранжирование вакансий по профилю CV: высокий fit — первый блок, средний — второй, низкий — не показывать.
CV_ENABLED = os.environ.get("JOB_FILTER_CV_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
CV_MODEL = os.environ.get("JOB_FILTER_CV_MODEL", "").strip() or None
CV_BATCH_SIZE = int(os.environ.get("JOB_FILTER_CV_BATCH_SIZE", "20") or "20")
CV_TIMEOUT_SEC = float(os.environ.get("JOB_FILTER_CV_TIMEOUT_SEC", "120"))
# LLM: короткая отрасль работодателя (Oil & Gas, Semiconductors, …) в дайджесте и registry.
# При выключении — только title/company/location как раньше.
INDUSTRY_LLM_ENABLED = os.environ.get("JOB_FILTER_INDUSTRY_LLM_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_RULE_PRIO_RANK = {
    "HIGH PRIORITY": 0,
    "HIGH PRIORITY (DIGITAL)": 1,
    "MEDIUM PRIORITY": 2,
}


def _llm_base_url() -> str:
    from ollama_resolve import effective_job_filter_llm_base_url

    return effective_job_filter_llm_base_url()


# Дефолт = DGX 70B; переопределение через env при необходимости.
LLM_MODEL = os.environ.get("JOB_FILTER_LLM_MODEL", "axi_omi_sphere").strip() or "axi_omi_sphere"
LLM_TIMEOUT_SEC = float(os.environ.get("JOB_FILTER_LLM_TIMEOUT_SEC", "180"))
MOVE_TO_FOLDER = os.environ.get("JOB_FILTER_MOVE_TO_FOLDER", "").strip()

SOURCES_ENABLED = os.environ.get("JOB_FILTER_SOURCES_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
SOURCE_DAYS = int(os.environ.get("JOB_FILTER_SOURCE_DAYS", "1") or "1")
SOURCE_INDEED = os.environ.get("JOB_FILTER_SOURCE_INDEED", "1").strip().lower() in {"1", "true", "yes", "on"}
SOURCE_LINKEDIN = os.environ.get("JOB_FILTER_SOURCE_LINKEDIN", "1").strip().lower() in {"1", "true", "yes", "on"}
SOURCE_SEEK = os.environ.get("JOB_FILTER_SOURCE_SEEK", "1").strip().lower() in {"1", "true", "yes", "on"}
FIRECRAWL_HEALTHCHECK_ENABLED = os.environ.get("JOB_FILTER_FIRECRAWL_HEALTHCHECK_ENABLED", "1").strip().lower() in {
    "1", "true", "yes", "on"
}
FIRECRAWL_HEALTHCHECK_HOUR = int(os.environ.get("JOB_FILTER_FIRECRAWL_HEALTHCHECK_HOUR", "23") or "23")
FIRECRAWL_HEALTHCHECK_MINUTE = int(os.environ.get("JOB_FILTER_FIRECRAWL_HEALTHCHECK_MINUTE", "55") or "55")
FIRECRAWL_BASE_URL = (os.environ.get("FIRECRAWL_BASE_URL", "http://firecrawl-api:3002") or "http://firecrawl-api:3002").rstrip("/")

SCRAPER_EMAIL = os.environ.get("JOB_SCRAPER_EMAIL", "").strip()
SCRAPER_PASSWORD = os.environ.get("JOB_SCRAPER_PASSWORD", "").strip()
SCRAPER_WEEK1_MONDAY = os.environ.get("JOB_SCRAPER_WEEK1_MONDAY", "2026-03-30").strip()
SCRAPER_PAGES = int(os.environ.get("JOB_SCRAPER_PAGES", "20") or "20")


def _parse_semicolon_list(env_key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return default
    return [v.strip() for v in raw.split(";") if v.strip()]


SOURCE_QUERIES = _parse_semicolon_list(
    "JOB_FILTER_SOURCE_QUERIES",
    ["maintenance manager", "reliability manager", "asset integrity manager", "principal engineer"],
)
SOURCE_LOCATIONS = _parse_semicolon_list(
    "JOB_FILTER_SOURCE_LOCATIONS",
    ["Dubai", "Abu Dhabi", "Qatar"],
)

# Extra search phrases for Australia-only sources (Indeed AU + SEEK): visa / DAMA / sponsorship.
SOURCE_VISA_DAMA_QUERIES = _parse_semicolon_list(
    "JOB_FILTER_SOURCE_VISA_DAMA_QUERIES",
    [
        "visa sponsorship",
        "482 visa",
        "DAMA",
        "employer sponsored",
        "subclass 482",
    ],
)
# Role + visa/DAMA terms (deduped) — used for query-title boost and AU Indeed/SEEK fetch merge.
SOURCE_QUERIES_MATCH = _merge_unique_queries(SOURCE_QUERIES, SOURCE_VISA_DAMA_QUERIES)


OVERRIDES_PATH = workspace_root() / "config" / "job_filter_overrides.json"
STATE_PATH = workspace_root() / "config" / "job_filter_state.json"
_OVERRIDES_CACHE: dict | None = None
_OVERRIDES_MTIME_NS: int | None = None
REGISTRY_MAX_ITEMS = 2000


def _sender_list() -> list[str]:
    out: list[str] = []
    for item in EMAIL_ALLOWED_SENDERS_RAW.split(","):
        v = item.strip().lower()
        if v:
            out.append(v)
    return sorted(set(out))


def _allowed_user_ids() -> set[int]:
    out: set[int] = set()
    for item in ALLOWED_USER_IDS_RAW.split(","):
        v = item.strip()
        if not v:
            continue
        try:
            out.add(int(v))
        except ValueError:
            logger.warning("invalid JOB_FILTER_ALLOWED_USER_IDS item: %r", v)
    return out


ALLOWED_USER_IDS = _allowed_user_ids()
SENDER_LIST = _sender_list()


def _is_allowed(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    if not ALLOWED_USER_IDS:
        return True
    return bool(user_id is not None and user_id in ALLOWED_USER_IDS)


async def _deny_if_needed(update: Update) -> bool:
    if _is_allowed(update):
        return False
    if update.message:
        await update.message.reply_text(f"{BOT_NAME}: access denied.")
    return True


def _masked_email(value: str) -> str:
    if "@" not in value:
        return value[:2] + "***" if value else "-"
    name, domain = value.split("@", 1)
    if len(name) <= 2:
        name_masked = name[:1] + "***"
    else:
        name_masked = name[:2] + "***"
    return f"{name_masked}@{domain}"


def _email_config_text() -> str:
    senders = SENDER_LIST
    return (
        f"{BOT_NAME}: email source config\n"
        f"Enabled: {'yes' if EMAIL_ENABLED else 'no'}\n"
        f"IMAP host: {EMAIL_IMAP_HOST or '-'}\n"
        f"IMAP port: {EMAIL_IMAP_PORT}\n"
        f"Mailbox: {EMAIL_MAILBOX}\n"
        f"Email user: {_masked_email(EMAIL_USERNAME)}\n"
        f"Password: {'set' if bool(EMAIL_PASSWORD) else 'not set'}\n"
        f"IMAP mode: {IMAP_MODE}\n"
        f"Allowed senders ({len(senders)}): {', '.join(senders[:20]) or '-'}\n"
        f"Auto poll mode: {AUTO_POLL_MODE}\n"
        f"Registry non-match logging: {'on' if REGISTRY_INCLUDE_NON_MATCH else 'off'}\n"
        f"Night window: {NIGHT_START_HOUR:02d}:00-{NIGHT_END_HOUR:02d}:00\n"
        f"Morning batch window: {MORNING_START_HOUR:02d}:00-{MORNING_END_HOUR:02d}:00\n"
        f"Report time: {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}"
    )


def _load_overrides() -> dict:
    global _OVERRIDES_CACHE, _OVERRIDES_MTIME_NS
    try:
        current_mtime = OVERRIDES_PATH.stat().st_mtime_ns if OVERRIDES_PATH.exists() else -1
    except OSError:
        current_mtime = -1
    if _OVERRIDES_CACHE is not None and _OVERRIDES_MTIME_NS == current_mtime:
        return _OVERRIDES_CACHE
    if not OVERRIDES_PATH.exists():
        _OVERRIDES_CACHE = {"extra_exclusions": [], "extra_inclusions": []}
        _OVERRIDES_MTIME_NS = current_mtime
        return _OVERRIDES_CACHE
    try:
        data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"extra_exclusions": [], "extra_inclusions": []}
        if "extra_exclusions" not in data or not isinstance(data["extra_exclusions"], list):
            data["extra_exclusions"] = []
        if "extra_inclusions" not in data or not isinstance(data["extra_inclusions"], list):
            data["extra_inclusions"] = []
        _OVERRIDES_CACHE = data
        _OVERRIDES_MTIME_NS = current_mtime
        return _OVERRIDES_CACHE
    except Exception as exc:
        logger.warning("failed_to_load_overrides: %s", exc)
        _OVERRIDES_CACHE = {"extra_exclusions": [], "extra_inclusions": []}
        _OVERRIDES_MTIME_NS = current_mtime
        return _OVERRIDES_CACHE


def _save_overrides(data: dict) -> None:
    global _OVERRIDES_CACHE, _OVERRIDES_MTIME_NS
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
    try:
        _OVERRIDES_MTIME_NS = OVERRIDES_PATH.stat().st_mtime_ns
    except OSError:
        _OVERRIDES_MTIME_NS = None
    _OVERRIDES_CACHE = data


def _build_config() -> JobFilterConfig:
    cfg = JobFilterConfig()
    data = _load_overrides()
    for term in data.get("extra_exclusions", []):
        t = str(term).strip().lower()
        if t:
            cfg.hard_exclusions.add(t)
    return cfg


def _inclusions() -> set[str]:
    data = _load_overrides()
    out: set[str] = set()
    for term in data.get("extra_inclusions", []):
        t = str(term).strip().lower()
        if t:
            out.add(t)
    return out


def _load_state() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    default = {
        "paused": False,
        "last_uid": 0,
        "report_chat_id": REPORT_CHAT_ID or 0,
        "daily": {
            "date": today,
            "seen": 0,
            "high": 0,
            "high_digital": 0,
            "medium": 0,
            "ignore": 0,
            "report_sent": False,
        },
        "registry": [],
        "pending_actions": {},
    }
    if not STATE_PATH.exists():
        return default
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        default.update(raw)
        if not isinstance(default.get("daily"), dict):
            default["daily"] = {}
        if not isinstance(default.get("registry"), list):
            default["registry"] = []
        if not isinstance(default.get("pending_actions"), dict):
            default["pending_actions"] = {}
        d = default["daily"]
        if d.get("date") != today:
            default["daily"] = {
                "date": today,
                "seen": 0,
                "high": 0,
                "high_digital": 0,
                "medium": 0,
                "ignore": 0,
                "report_sent": False,
            }
        return default
    except Exception:
        return default


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def _registry_append(state: dict, entry: dict) -> None:
    reg = state.setdefault("registry", [])
    reg.append(entry)
    if len(reg) > REGISTRY_MAX_ITEMS:
        state["registry"] = reg[-REGISTRY_MAX_ITEMS:]


def _build_dedup_set(registry: list[dict], days: int = 7) -> tuple[set[str], set[str]]:
    """
    Build dedup sets from registry entries within the last `days` days.
    Returns (known_urls, known_signatures).
    Signature = normalized "title|company|location" — catches duplicates even if URL differs.
    """
    from job_filter import normalize_text
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    known_urls: set[str] = set()
    known_sigs: set[str] = set()
    for r in registry:
        ts = r.get("ts") or r.get("registered_at") or ""
        if ts < cutoff:
            continue
        url = r.get("url", "")
        if url:
            known_urls.add(url)
        title = normalize_text(r.get("title", ""))
        company = normalize_text(r.get("company", ""))
        location = normalize_text(r.get("location", ""))
        if title:
            known_sigs.add(f"{title}|{company}|{location}")
    return known_urls, known_sigs


def _is_duplicate(job: dict, known_urls: set[str], known_sigs: set[str]) -> bool:
    """Check if a job is a duplicate by URL or by (title, company, location) signature."""
    from job_filter import normalize_text
    url = job.get("url", "").strip()
    if url and url in known_urls:
        return True
    title = normalize_text(job.get("title", ""))
    company = normalize_text(job.get("company", ""))
    location = normalize_text(job.get("location", ""))
    sig = f"{title}|{company}|{location}"
    return sig in known_sigs


def _format_registry_lines(items: list[dict], limit: int = 20) -> str:
    if not items:
        return "Registry is empty."
    out = [f"Last {min(limit, len(items))} of {len(items)} item(s):"]
    for i, row in enumerate(reversed(items[-limit:]), 1):
        title = (row.get("title") or row.get("subject") or "-")[:90]
        url = row.get("url") or ""
        prio = row.get("priority", "-")
        date = row.get("date", "-")
        line = f"{i}. [{prio}] {date[:16]}\n   {title}"
        ind = (row.get("industry") or "").strip()
        if ind:
            line += f"\n   🏭 {ind[:100]}"
        if url:
            line += f"\n   {url}"
        out.append(line)
    return "\n".join(out)


def _update_daily_counts(state: dict, priority: Priority) -> None:
    daily = state.setdefault("daily", {})
    daily["seen"] = int(daily.get("seen", 0)) + 1
    if priority == Priority.HIGH:
        daily["high"] = int(daily.get("high", 0)) + 1
    elif priority == Priority.HIGH_DIGITAL:
        daily["high_digital"] = int(daily.get("high_digital", 0)) + 1
    elif priority == Priority.MEDIUM:
        daily["medium"] = int(daily.get("medium", 0)) + 1
    else:
        daily["ignore"] = int(daily.get("ignore", 0)) + 1


def _in_night_window() -> bool:
    h = datetime.now().hour
    if NIGHT_START_HOUR <= NIGHT_END_HOUR:
        return NIGHT_START_HOUR <= h < NIGHT_END_HOUR
    return h >= NIGHT_START_HOUR or h < NIGHT_END_HOUR


def _in_morning_batch_window() -> bool:
    """Окно «утром» для автоматического батча (IMAP + job_sources + scraper по тем же флагам)."""
    h = datetime.now().hour
    if MORNING_START_HOUR <= MORNING_END_HOUR:
        return MORNING_START_HOUR <= h < MORNING_END_HOUR
    return h >= MORNING_START_HOUR or h < MORNING_END_HOUR


def _should_auto_poll_now() -> bool:
    if AUTO_POLL_MODE == "always":
        return True
    if AUTO_POLL_MODE == "morning":
        return _in_morning_batch_window()
    if AUTO_POLL_MODE in ("night_and_morning", "night+morning"):
        return _in_night_window() or _in_morning_batch_window()
    return _in_night_window()


def _firecrawl_healthcheck_due(now: datetime, state: dict) -> bool:
    if not FIRECRAWL_HEALTHCHECK_ENABLED:
        return False
    if now.hour != FIRECRAWL_HEALTHCHECK_HOUR or now.minute != FIRECRAWL_HEALTHCHECK_MINUTE:
        return False
    done_date = str(state.get("firecrawl_healthcheck_date") or "")
    return done_date != now.strftime("%Y-%m-%d")


async def _run_firecrawl_healthcheck(application: Application, state: dict) -> None:
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    target_chat = int(state.get("report_chat_id") or 0) or REPORT_CHAT_ID
    endpoint = f"{FIRECRAWL_BASE_URL}/v1/scrape"
    ok = False
    detail = ""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                endpoint,
                json={"url": "https://example.com", "formats": ["markdown"]},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code < 400:
            payload = resp.json() if resp.content else {}
            md = ""
            if isinstance(payload, dict):
                md = str(payload.get("markdown") or "")
                if not md and isinstance(payload.get("data"), dict):
                    md = str(payload["data"].get("markdown") or "")
            ok = len(md.strip()) > 20
            detail = f"http {resp.status_code}, markdown_len={len(md)}"
        else:
            detail = f"http {resp.status_code}"
    except Exception as exc:
        detail = f"error: {exc!s}"[:200]

    state["firecrawl_healthcheck_date"] = today
    state["firecrawl_healthcheck_last_at"] = now.isoformat(timespec="seconds")
    state["firecrawl_healthcheck_last_ok"] = bool(ok)
    state["firecrawl_healthcheck_last_detail"] = detail

    logger.info("firecrawl_healthcheck ok=%s detail=%s", ok, detail)
    if target_chat:
        text = (
            f"{BOT_NAME}: Firecrawl health-check 23:55 — {'OK' if ok else 'FAIL'}\n"
            f"Endpoint: {endpoint}\n"
            f"Detail: {detail}"
        )
        try:
            await application.bot.send_message(chat_id=target_chat, text=text[:3500])
        except Exception as exc:
            logger.warning("firecrawl_healthcheck_notify_failed: %s", exc)


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_text_from_msg(msg) -> str:
    if msg.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                txt = payload.decode(charset, errors="ignore")
            except Exception:
                txt = payload.decode("utf-8", errors="ignore")
            if ctype == "text/plain":
                plain_parts.append(txt)
            elif ctype == "text/html":
                html_parts.append(txt)
        if plain_parts:
            return "\n".join(plain_parts)
        if html_parts:
            html = "\n".join(html_parts)
            return re.sub(r"<[^>]+>", " ", html)
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="ignore")
    except Exception:
        return payload.decode("utf-8", errors="ignore")


_JOB_URL_RE = re.compile(
    r'https?://(?:[\w.-]+\.)?(?:'
    r'linkedin\.com/(?:comm/)?jobs/view/\d+'
    r'|linkedin\.com/jobs/view/\d+'
    r'|indeed\.com/(?:viewjob|rc/clk|applystart)'
    r'|seek\.com\.au/job/\d+'
    r'|naukrigulf\.com/[^\s"\'<>&]+'
    r'|rigzone\.com/[^\s"\'<>&]+'
    r'|jobleads\.com/[^\s"\'<>&]+'
    r'|dupont\.com/[^\s"\'<>&]+'
    r')',
    re.IGNORECASE,
)

# Broader pattern to capture any href from known job domains (for fallback)
_JOB_DOMAIN_RE = re.compile(
    r'https?://[^\s"\'<>&]*(?:linkedin\.com|indeed\.com|seek\.com\.au|naukrigulf\.com|rigzone\.com|jobleads\.com|dupont\.com)[^\s"\'<>&]*',
    re.IGNORECASE,
)


def _extract_vacancies_from_msg(msg) -> list[dict]:
    """Extract [{title, url}] from job-alert HTML email body."""
    html_parts: list[str] = []
    for part in msg.walk():
        ctype = (part.get_content_type() or "").lower()
        disp = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disp:
            continue
        if ctype == "text/html":
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                html_parts.append(payload.decode(charset, errors="ignore"))
            except Exception:
                html_parts.append(payload.decode("utf-8", errors="ignore"))
    if not html_parts:
        return []
    html = "\n".join(html_parts)
    # Match href with single, double quotes or unquoted
    anchor_re = re.compile(
        r'<a[^>]+href=(?:["\']([^"\']+)["\']|([^\s>]+))[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    seen: set[str] = set()
    vacancies: list[dict] = []
    all_hrefs: list[str] = []
    for m in anchor_re.finditer(html):
        raw_url = _html_unescape((m.group(1) or m.group(2) or "").strip())
        if not raw_url:
            continue
        all_hrefs.append(raw_url[:120])
        if not _JOB_URL_RE.match(raw_url):
            continue
        base_url = raw_url.split("?")[0].rstrip("/")
        if base_url in seen:
            continue
        seen.add(base_url)
        raw_title = m.group(3) or ""
        title = re.sub(r"<[^>]+>", " ", raw_title)
        title = re.sub(r"\s+", " ", _html_unescape(title)).strip()
        if len(title) < 4:
            continue
        vacancies.append({"title": title, "url": base_url})
    if not vacancies:
        logger.info("vacancy_extract_empty hrefs_found=%d sample=%s", len(all_hrefs), all_hrefs[:5])
    else:
        logger.info("vacancy_extract found=%d", len(vacancies))
    return vacancies


_VIEW_JOB_RE = re.compile(
    r'View job:\s*(https?://[^\s]+)',
    re.IGNORECASE,
)
_CLEAN_URL_RE = re.compile(
    r'(https?://(?:www\.)?linkedin\.com/comm/jobs/view/\d+|'
    r'https?://(?:www\.)?linkedin\.com/jobs/view/\d+|'
    r'https?://[^\s]*indeed\.com/[^\s]*|'
    r'https?://[^\s]*seek\.com\.au/job/[^\s]*|'
    r'https?://[^\s]*naukrigulf\.com/[^\s]*|'
    r'https?://[^\s]*rigzone\.com/[^\s]*)',
    re.IGNORECASE,
)


def _extract_vacancies_from_text(plain_text: str) -> list[dict]:
    """Parse LinkedIn/Indeed/NaukriGulf plain-text job alert emails into [{title, url}]."""
    if not plain_text:
        return []

    skip_words = {"new jobs match", "your job alert", "view all", "unsubscribe",
                  "manage alerts", "linkedin", "update preferences", "indeed job alert",
                  "new vacancies", "jobs match your", "salary guide", "privacy policy",
                  "terms of service", "help center", "email preferences"}

    def _clean_url(raw: str) -> str:
        """Keep LinkedIn job URLs clean (strip tracking); preserve Indeed/others as-is."""
        # LinkedIn: job ID is in the path — strip query params
        if re.search(r'linkedin\.com/(?:comm/)?jobs/view/\d+', raw, re.IGNORECASE):
            return raw.split("?")[0].rstrip("/")
        # Indeed / others: job ID may be in query params — keep URL intact
        return raw.rstrip("/")

    def _pick_url(lines: list[str]) -> str:
        """Return cleaned job URL from block lines, or empty string."""
        # LinkedIn: "View job: <url>"
        for line in lines:
            m = _VIEW_JOB_RE.search(line)
            if m:
                cm = _CLEAN_URL_RE.match(m.group(1))
                if cm:
                    return _clean_url(cm.group(1))
        # Indeed / NaukriGulf: bare URL line matching known job domains
        for line in reversed(lines):  # URL usually at end of block
            if line.startswith("http"):
                cm = _CLEAN_URL_RE.match(line)
                if cm:
                    return _clean_url(cm.group(1))
                # Fallback: any job-domain URL
                if _JOB_DOMAIN_RE.search(line):
                    return _clean_url(line)
        return ""

    def _pick_title(lines: list[str]) -> str:
        """Return first meaningful non-URL line from block."""
        for line in lines:
            low = line.lower()
            if any(s in low for s in skip_words):
                continue
            if len(line) < 5:
                continue
            if line.startswith("http"):
                continue
            return line
        return ""

    def _parse_blocks(blocks: list[str]) -> list[dict]:
        vacancies: list[dict] = []
        seen_urls: set[str] = set()
        for block in blocks:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            if not lines:
                continue
            url = _pick_url(lines)
            if not url:
                continue
            title = _pick_title(lines)
            if not title:
                continue
            if url not in seen_urls:
                seen_urls.add(url)
                vacancies.append({"title": title, "url": url})
        return vacancies

    # LinkedIn format: blocks separated by 10+ dashes
    dash_blocks = re.split(r'-{10,}', plain_text)
    if len(dash_blocks) > 2:
        result = _parse_blocks(dash_blocks)
        if result:
            logger.info("text_extract(linkedin-dashes) found=%d from %d blocks", len(result), len(dash_blocks))
            return result

    # Indeed / NaukriGulf format: blocks separated by blank lines
    para_blocks = re.split(r'\n\s*\n', plain_text)
    result = _parse_blocks(para_blocks)
    logger.info("text_extract(paragraphs) found=%d from %d blocks", len(result), len(para_blocks))
    return result


async def _llm_extract_vacancies(email_text: str, email_html: str) -> list[dict]:
    """Extract vacancies from email: plain text parser first, LLM fallback if needed."""
    # Try plain text parsing first (fast, no LLM needed)
    result = _extract_vacancies_from_text(email_text)
    if result:
        return result
    # LLM fallback for non-standard formats (Indeed, NaukriGulf, etc.)
    if not LLM_ENABLED:
        return []
    content = email_text.strip() or re.sub(r"<[^>]+>", " ", email_html)
    content = re.sub(r"\s+", " ", content).strip()[:4000]
    if not content:
        return []
    prompt = (
        "Extract job vacancies from this email. "
        "Return ONLY a JSON array, no explanation.\n"
        "Each item: {\"title\": \"job title only\", \"url\": \"job URL or \"\"}\n"
        "Email:\n" + content
    )
    loop = asyncio.get_event_loop()
    try:
        def _call():
            with httpx.Client(timeout=LLM_TIMEOUT_SEC) as client:
                _gen = {"model": LLM_MODEL, "prompt": prompt, "stream": False}
                ollama_apply_keep_alive(_gen)
                resp = client.post(f"{_llm_base_url()}/api/generate", json=_gen)
                if resp.status_code != 200:
                    return []
                raw = resp.json().get("response", "")
                first, last = raw.find("["), raw.rfind("]")
                if first == -1 or last <= first:
                    return []
                items = json.loads(raw[first:last + 1])
                return [
                    {"title": str(x.get("title", "")).strip(), "url": str(x.get("url", "")).strip()}
                    for x in items if isinstance(x, dict) and x.get("title", "").strip()
                ]
        result = await loop.run_in_executor(None, _call)
        if result:
            logger.info("llm_extract found=%d", len(result))
        return result
    except Exception as exc:
        logger.warning("llm_extract_failed: %s", exc)
        return []


def _format_date_short(date_str: str) -> str:
    """Strip timezone offset: 'Mon, 30 Mar 2026 18:01:32 +0000' → 'Mon, 30 Mar 2026 18:01:32'"""
    if not date_str:
        return ""
    return re.sub(r"\s+[+-]\d{4}(\s+\([A-Z]+\))?$", "", date_str.strip())


def _fetch_email_candidates(last_uid: int) -> tuple[int, list[dict]]:
    if not (EMAIL_ENABLED and EMAIL_IMAP_HOST and EMAIL_USERNAME and EMAIL_PASSWORD):
        return last_uid, []
    allowed_senders = SENDER_LIST
    max_uid = last_uid
    out: list[dict] = []
    with imaplib.IMAP4_SSL(EMAIL_IMAP_HOST, EMAIL_IMAP_PORT) as m:
        m.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        m.select(EMAIL_MAILBOX)
        if IMAP_MODE == "unread":
            from datetime import timedelta
            since_date = (datetime.now() - timedelta(weeks=2)).strftime("%d-%b-%Y")
            typ, data = m.uid("search", None, f"UNSEEN SINCE {since_date}")
        else:
            uid_from = max(1, last_uid + 1)
            typ, data = m.uid("search", None, f"UID {uid_from}:*")
        if typ != "OK":
            return last_uid, []
        uids = [int(x) for x in (data[0] or b"").split() if x.isdigit()]
        uids_new = [u for u in uids if u > last_uid] if IMAP_MODE != "unread" else uids
        logger.info("imap_search last_uid=%d total_found=%d to_process=%d mode=%s", last_uid, len(uids), len(uids_new), IMAP_MODE)
        for uid in sorted(uids_new):
            typ2, msg_data = m.uid("fetch", str(uid), "(RFC822)")
            if typ2 != "OK" or not msg_data:
                continue
            raw = None
            for row in msg_data:
                if isinstance(row, tuple):
                    raw = row[1]
                    break
            if not raw:
                continue
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            sender = _decode_header(msg.get("From", ""))
            sender_l = sender.lower()
            if allowed_senders and not any(s in sender_l for s in allowed_senders):
                logger.debug("imap_skip_sender uid=%d from=%r", uid, sender[:60])
                max_uid = max(max_uid, uid)
                continue
            subject = _decode_header(msg.get("Subject", ""))
            body = _extract_text_from_msg(msg)
            # Extract HTML for LLM processing
            html_parts = []
            for part in msg.walk():
                if (part.get_content_type() or "").lower() == "text/html":
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    html_parts.append(payload.decode(charset, errors="ignore"))
            html_body = "\n".join(html_parts)
            out.append(
                {
                    "uid": uid,
                    "from": sender,
                    "subject": subject,
                    "date": _decode_header(msg.get("Date", "")),
                    "text": f"{subject}\n\n{body}".strip(),
                    "html": html_body,
                    "vacancies": [],  # filled by LLM in poll loop
                }
            )
            try:
                m.uid("store", str(uid), "+FLAGS", "\\Seen")
            except Exception as exc:
                logger.debug("mark_seen_failed uid=%s: %s", uid, exc)
            max_uid = max(max_uid, uid)
        if MOVE_TO_FOLDER and out:
            moved = 0
            for item in out:
                uid_s = str(item["uid"])
                try:
                    m.uid("copy", uid_s, MOVE_TO_FOLDER)
                    m.uid("store", uid_s, "+FLAGS", "\\Deleted")
                    moved += 1
                except Exception as exc:
                    logger.debug("move_to_folder_failed uid=%s folder=%s: %s", uid_s, MOVE_TO_FOLDER, exc)
            if moved:
                try:
                    m.expunge()
                    logger.info("moved_to_folder count=%d folder=%s", moved, MOVE_TO_FOLDER)
                except Exception as exc:
                    logger.debug("expunge_failed: %s", exc)
    return max_uid, out


def _apply_inclusion_if_needed(text: str, result) -> tuple[Priority, int, list[str]]:
    inc = _inclusions()
    if not inc:
        return result.priority, result.score, list(result.reasons)
    norm = normalize_text(text)
    hits = [x for x in sorted(inc) if re.search(rf"\b{re.escape(x)}\b", norm)]
    reasons = list(result.reasons)
    if hits and result.priority == Priority.IGNORE:
        reasons.insert(0, f"Manual inclusion matched: {', '.join(hits[:3])}")
        return Priority.MEDIUM, max(result.score, 6), reasons
    if hits:
        reasons.append(f"Manual inclusion matched: {', '.join(hits[:3])}")
    return result.priority, result.score, reasons


def _mail_item_hash(item: dict) -> str:
    key = "|".join(
        [
            str(item.get("from") or "").lower(),
            str(item.get("subject") or "").lower(),
            str(item.get("date") or ""),
        ]
    )
    return hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()


def _llm_validate_priority(text: str, current_priority: Priority, current_reasons: list[str]) -> tuple[Priority, list[str]]:
    if not LLM_ENABLED:
        return current_priority, current_reasons
    # Keep this conservative: only try to upgrade uncertain classes.
    if current_priority not in {Priority.MEDIUM, Priority.IGNORE}:
        return current_priority, current_reasons
    prompt = (
        "You are a strict job vacancy classifier for oil&gas maintenance leadership.\n"
        "Return JSON only: {\"priority\":\"HIGH|HIGH_DIGITAL|MEDIUM|IGNORE\",\"reason\":\"...\"}\n"
        "Prefer IGNORE unless strongly relevant.\n"
        f"Current rule-based class: {current_priority.value}\n"
        f"Text:\n{text[:6000]}"
    )
    try:
        with httpx.Client(timeout=LLM_TIMEOUT_SEC) as client:
            _gen = {"model": LLM_MODEL, "prompt": prompt, "stream": False, "format": "json"}
            ollama_apply_keep_alive(_gen)
            r = client.post(f"{_llm_base_url()}/api/generate", json=_gen)
            r.raise_for_status()
            payload = r.json()
        raw = (payload.get("response") or "").strip()
        data = json.loads(raw) if raw else {}
        p = str(data.get("priority", "")).strip().upper()
        why = str(data.get("reason", "")).strip()
        if p == "HIGH":
            return Priority.HIGH, current_reasons + ([f"LLM validate: {why}"] if why else ["LLM validate: HIGH"])
        if p in {"HIGH_DIGITAL", "HIGH DIGITAL"}:
            return Priority.HIGH_DIGITAL, current_reasons + ([f"LLM validate: {why}"] if why else ["LLM validate: HIGH DIGITAL"])
        if p == "MEDIUM":
            return Priority.MEDIUM, current_reasons + ([f"LLM validate: {why}"] if why else ["LLM validate: MEDIUM"])
        return Priority.IGNORE, current_reasons + ([f"LLM validate: {why}"] if why else [])
    except Exception as exc:
        logger.debug("llm_validate_failed: %s", exc)
        return current_priority, current_reasons


def _sort_jobs_by_rule_priority(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda j: _RULE_PRIO_RANK.get(j.get("priority", ""), 9))


def _job_mini_batch(batch: list[dict]) -> list[dict]:
    """Compact job rows for LLM (batch items must have _gidx)."""
    return [
        {
            "i": b["_gidx"],
            "title": (b.get("title") or "")[:200],
            "company": (b.get("company") or "")[:120],
            "location": (b.get("location") or "")[:120],
            "snippet": (b.get("description") or "")[:450],
        }
        for b in batch
    ]


def _parse_fit_industry_row(row: dict) -> tuple[int | None, str, str]:
    """Parse one LLM result row -> (index, fit, industry)."""
    try:
        i = int(row.get("i", -1))
    except (TypeError, ValueError):
        return None, "medium", ""
    if i < 0:
        return None, "medium", ""
    fit = str(row.get("fit", "medium")).strip().lower()
    if fit in ("low", "ignore", "none", "bad"):
        fit = "drop"
    if fit not in ("high", "medium", "drop"):
        fit = "medium"
    ind = str(row.get("industry", "")).strip()
    if len(ind) > 120:
        ind = ind[:120]
    return i, fit, ind


def _llm_cv_fit_and_industry_batch(
    batch: list[dict], cv_text: str, model: str
) -> tuple[dict[int, str], dict[int, str]]:
    """batch items must have _gidx. Returns (fit by index, industry by index)."""
    mini = _job_mini_batch(batch)
    prompt = (
        "You match job postings to a candidate profile.\n"
        'Return JSON only: {"results":[{"i":0,"fit":"high|medium|drop","industry":"..."},...]}\n'
        "Rules for fit:\n"
        "- high: strong match to target roles, seniority, industry, and regions implied by the profile.\n"
        "- medium: plausible but weaker (adjacent role, tangential sector, unclear fit).\n"
        "- drop: poor match — wrong specialty, junior IC vs leadership profile, unrelated sector, etc.\n"
        "For every job also set \"industry\": the employer's primary sector in at most 6 words "
        '(e.g. "Oil & Gas", "Semiconductors", "EPC", "Pharmaceuticals", "Broadcasting"). '
        "Use title, company name, and snippet only; do not invent facts. "
        'Use "Unknown" if the sector cannot be inferred.\n'
        "Include every index i from the jobs list exactly once.\n\n"
        f"CANDIDATE PROFILE:\n{cv_text[:8000]}\n\n"
        f"JOBS JSON:\n{json.dumps(mini, ensure_ascii=True)}"
    )
    fit_out: dict[int, str] = {}
    ind_out: dict[int, str] = {}
    try:
        with httpx.Client(timeout=CV_TIMEOUT_SEC) as client:
            _gen = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
            ollama_apply_keep_alive(_gen)
            r = client.post(f"{_llm_base_url()}/api/generate", json=_gen)
            r.raise_for_status()
            payload = r.json()
        raw = (payload.get("response") or "").strip()
        data = json.loads(raw) if raw else {}
        for row in data.get("results") or []:
            if not isinstance(row, dict):
                continue
            idx, fit, ind = _parse_fit_industry_row(row)
            if idx is None:
                continue
            fit_out[idx] = fit
            if ind:
                ind_out[idx] = ind
        return fit_out, ind_out
    except Exception as exc:
        logger.warning("llm_cv_fit_industry_batch_failed: %s", exc)
        return {}, {}


def _llm_industry_only_batch(batch: list[dict], model: str) -> dict[int, str]:
    """Infer sector only (no CV). batch items must have _gidx."""
    mini = _job_mini_batch(batch)
    prompt = (
        "For each job, infer the employer's primary industry/sector.\n"
        'Return JSON only: {"results":[{"i":0,"industry":"..."},...]}\n'
        "Rules: at most 6 words per industry; use title, company, location, snippet; "
        'do not invent; use "Unknown" if unclear. Include every index i exactly once.\n\n'
        f"JOBS JSON:\n{json.dumps(mini, ensure_ascii=True)}"
    )
    ind_out: dict[int, str] = {}
    try:
        with httpx.Client(timeout=CV_TIMEOUT_SEC) as client:
            _gen = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
            ollama_apply_keep_alive(_gen)
            r = client.post(f"{_llm_base_url()}/api/generate", json=_gen)
            r.raise_for_status()
            payload = r.json()
        raw = (payload.get("response") or "").strip()
        data = json.loads(raw) if raw else {}
        for row in data.get("results") or []:
            if not isinstance(row, dict):
                continue
            try:
                i = int(row.get("i", -1))
            except (TypeError, ValueError):
                continue
            if i < 0:
                continue
            ind = str(row.get("industry", "")).strip()
            if len(ind) > 120:
                ind = ind[:120]
            if ind:
                ind_out[i] = ind
        return ind_out
    except Exception as exc:
        logger.warning("llm_industry_only_batch_failed: %s", exc)
        return {}


def _cv_compute_fits(candidates: list[dict], state: dict) -> dict[int, str]:
    """Map candidate list index -> high|medium|drop; set each candidate['industry'] when LLM enabled."""
    n = len(candidates)
    for c in candidates:
        c["industry"] = ""
    model = (CV_MODEL or LLM_MODEL).strip()
    indexed: list[dict] = []
    for i, c in enumerate(candidates):
        d = dict(c)
        d["_gidx"] = i
        indexed.append(d)
    fit_map: dict[int, str] = {}
    industry_map: dict[int, str] = {}
    bs = max(1, min(CV_BATCH_SIZE, 40))
    use_cv = CV_ENABLED and bool((state.get("cv_profile") or "").strip())
    cv_text = str(state.get("cv_profile") or "").strip()

    if use_cv:
        for start in range(0, len(indexed), bs):
            batch = indexed[start : start + bs]
            fmap, imap = _llm_cv_fit_and_industry_batch(batch, cv_text, model)
            fit_map.update(fmap)
            industry_map.update(imap)
    else:
        fit_map = {i: "high" for i in range(n)}
        if INDUSTRY_LLM_ENABLED:
            for start in range(0, len(indexed), bs):
                batch = indexed[start : start + bs]
                industry_map.update(_llm_industry_only_batch(batch, model))

    out: dict[int, str] = {}
    for i in range(n):
        fit = fit_map.get(i, "medium" if use_cv else "high").lower()
        if fit in ("low", "ignore", "none", "bad"):
            fit = "drop"
        if fit not in ("high", "medium", "drop"):
            fit = "medium"
        out[i] = fit
        candidates[i]["industry"] = (industry_map.get(i, "") or "").strip()
    return out


def _strip_candidate_for_display(c: dict) -> dict:
    return {k: v for k, v in c.items() if k not in ("description", "date_str", "item_date", "registry_date")}


def _split_candidates_cv_tiers(
    candidates: list[dict], fit_by_idx: dict[int, str]
) -> tuple[list[dict], list[dict], int]:
    high: list[dict] = []
    med: list[dict] = []
    drop_n = 0
    for i, c in enumerate(candidates):
        f = fit_by_idx.get(i, "high")
        if f == "drop":
            drop_n += 1
            continue
        row = _strip_candidate_for_display(c)
        if f == "high":
            high.append(row)
        else:
            med.append(row)
    return _sort_jobs_by_rule_priority(high), _sort_jobs_by_rule_priority(med), drop_n


async def _cv_compute_fits_async(candidates: list[dict], state: dict) -> dict[int, str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _cv_compute_fits(candidates, state))


def _format_result(text: str) -> str:
    result = classify_job(text, _build_config())
    final_priority, final_score, final_reasons = _apply_inclusion_if_needed(text, result)
    salary_line = "not found"
    if result.salary_monthly_usd is not None:
        salary_line = f"${result.salary_monthly_usd:,.0f} USD/month"
    elif result.salary_annual_usd is not None:
        salary_line = f"${result.salary_annual_usd:,.0f} USD/year"

    reasons = "; ".join(final_reasons[:4]) if final_reasons else "-"
    return (
        f"{BOT_NAME}: {final_priority.value}\n"
        f"Score: {final_score}\n"
        f"Salary: {salary_line}\n"
        f"Roles: {', '.join(result.matched_roles[:5]) or '-'}\n"
        f"Domains: {', '.join(result.matched_domains[:5]) or '-'}\n"
        f"Technical: {', '.join(result.matched_technical[:5]) or '-'}\n"
        f"Digital: {', '.join(result.matched_digital[:5]) or '-'}\n"
        f"Reasons: {reasons}"
    )


async def _poll_mail_and_notify(application: Application, manual_chat_id: int | None = None) -> str:
    state = _load_state()
    if state.get("paused") and manual_chat_id is None:
        return f"{BOT_NAME}: paused."
    last_uid = int(state.get("last_uid", 0))
    loop = asyncio.get_event_loop()
    max_uid, items = await loop.run_in_executor(None, lambda: _fetch_email_candidates(last_uid))
    if max_uid > last_uid:
        state["last_uid"] = max_uid
    daily = state.setdefault("daily", {})
    known_hashes = set(state.get("sent_hashes", []))
    processed_uids = set(int(x) for x in state.get("processed_uids", []) if str(x).isdigit())
    # Cross-source dedup: skip vacancies already seen via web scraping
    known_urls_reg, known_sigs_reg = _build_dedup_set(state.get("registry", []), days=7)
    cfg = _build_config()

    # Collect all matching vacancies grouped by email date across all items
    all_sections: list[str] = []   # each section = date_line + vacancy lines for one email
    now_ts = datetime.now().isoformat(timespec="seconds")

    logger.info("poll_start last_uid=%d fetched=%d manual=%s", last_uid, len(items), manual_chat_id is not None)

    for item in items:
        uid_i = int(item.get("uid") or 0)
        if IMAP_MODE == "unread" and uid_i in processed_uids:
            continue

        # LLM extracts all vacancies from email text+html
        vacancies = await _llm_extract_vacancies(
            item.get("text", ""),
            item.get("html", ""),
        )
        if not vacancies:
            # Fallback: treat subject as single vacancy (no URL)
            vacancies = [{"title": item.get("subject", ""), "url": ""}]
            logger.info("llm_extract_fallback uid=%d subject=%r", uid_i, item.get("subject", "")[:60])

        matching: list[dict] = []
        for vac in vacancies:
            title = vac.get("title", "").strip()
            if not title:
                continue
            base = classify_job(title, cfg, title=title)
            prio, _score, reasons = _apply_inclusion_if_needed(title, base)
            prio, reasons = await asyncio.get_event_loop().run_in_executor(
                None, lambda p=prio, r=reasons: _llm_validate_priority(title, p, r)
            )
            logger.info("vacancy uid=%d prio=%s title=%r reason=%s", uid_i, prio.value, title[:80], (reasons or ["?"])[0][:60])
            _update_daily_counts(state, prio)
            if prio in {Priority.HIGH, Priority.HIGH_DIGITAL, Priority.MEDIUM}:
                vac_job = {"title": title, "url": vac.get("url", ""), "company": vac.get("company", ""), "location": vac.get("location", "")}
                if _is_duplicate(vac_job, known_urls_reg, known_sigs_reg):
                    logger.info("dedup_registry uid=%d title=%r — already in scrape registry, skipping", uid_i, title[:80])
                    continue
                matching.append({"title": title, "url": vac.get("url", ""), "priority": prio.value})

        if uid_i:
            processed_uids.add(uid_i)

        if not matching:
            continue

        h = _mail_item_hash(item)
        if h in known_hashes:
            continue

        date_line = _format_date_short(item.get("date", ""))
        section_lines = ([date_line] if date_line else []) + [
            f"- {v['title']}  {v['url']}" if v.get("url") else f"- {v['title']}"
            for v in matching
        ]
        all_sections.append("\n".join(section_lines))
        known_hashes.add(h)
        for v in matching:
            _registry_append(state, {
                "ts": now_ts, "registered_at": now_ts, "notified_at": now_ts,
                "uid": uid_i, "date": item.get("date", ""), "from": item.get("from", ""),
                "title": v["title"], "url": v.get("url", ""),
                "priority": v["priority"], "status": "sent",
            })

    state["sent_hashes"] = list(sorted(known_hashes))[-2000:]
    state["processed_uids"] = list(sorted(processed_uids))[-5000:]
    _save_state(state)

    if not all_sections:
        return ""

    if state.get("paused") and manual_chat_id is None:
        return ""

    target_chat = manual_chat_id or int(state.get("report_chat_id") or 0)
    if not target_chat:
        return ""

    d = daily
    stats_line = (
        f"Daily seen={d.get('seen', 0)} vacancies high={d.get('high', 0)} "
        f"digital={d.get('high_digital', 0)} medium={d.get('medium', 0)} ignore={d.get('ignore', 0)}."
    )
    full_msg = "\n\n".join(all_sections) + "\n\n" + stats_line
    try:
        await application.bot.send_message(chat_id=target_chat, text=full_msg)
    except Exception as exc:
        logger.warning("send_consolidated_failed: %s", exc)
    return ""


async def _scheduler_tick_app(app: Application) -> None:
    state = _load_state()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    daily = state.setdefault("daily", {})
    if daily.get("date") != today:
        state["daily"] = {
            "date": today,
            "seen": 0,
            "high": 0,
            "high_digital": 0,
            "medium": 0,
            "ignore": 0,
            "report_sent": False,
        }
        daily = state["daily"]
    if _firecrawl_healthcheck_due(now, state):
        await _run_firecrawl_healthcheck(app, state)
    # Один «батч» вакансий за сутки в выбранном окне (night / morning / night_and_morning), не спам каждые N минут.
    _poll_now = _should_auto_poll_now()
    _once_daily = (
        JOB_FILTER_VACANCY_BATCH_ONCE_PER_DAY
        and AUTO_POLL_MODE != "always"
        and state.get("vacancy_batch_date") == today
    )
    _skip_auto_batch = _poll_now and _once_daily
    if _skip_auto_batch:
        logger.debug("vacancy_batch_skip: already completed for %s (once per day)", today)
    if EMAIL_ENABLED and _poll_now and not _skip_auto_batch:
        await _poll_mail_and_notify(app)
    if SOURCES_ENABLED and _poll_now and not _skip_auto_batch:
        await _scan_sources_and_notify(app)
    # 7-week rotating schedule + random coefficient for Playwright browser scraper
    # В том же окне, что и почта/источники (см. JOB_FILTER_AUTO_POLL_MODE)
    if SCRAPER_EMAIL and SCRAPER_PASSWORD and _poll_now and not _skip_auto_batch:
        from job_scraper import should_scan_now, calculate_scan_time
        last_scan = state.get("scraper_last_scan_date")
        # Generate today's scan time once and cache it (so random value is stable all day)
        cached_time = state.get("scraper_scheduled_sec")
        cached_date = state.get("scraper_scheduled_date")
        if cached_date != today:
            cached_time = calculate_scan_time(SCRAPER_WEEK1_MONDAY)
            state["scraper_scheduled_sec"] = cached_time
            state["scraper_scheduled_date"] = today
            if cached_time is not None:
                h, m = cached_time // 3600, (cached_time % 3600) // 60
                logger.info("scraper_schedule: today's scan time = %02d:%02d", h, m)
            _save_state(state)
        run_now, _ = should_scan_now(SCRAPER_WEEK1_MONDAY, last_scan, cached_time)
        if run_now:
            chat_id = int(state.get("report_chat_id") or 0) or REPORT_CHAT_ID
            logger.info("scraper_schedule: launching scan")
            await _scraper_scan_and_notify(app, manual_chat_id=chat_id or None)
    # Morning report disabled — scan results already contain all stats in the message footer.
    # The separate "morning report" was redundant.
    if not daily.get("report_sent"):
        daily["report_sent"] = True
    if (
        JOB_FILTER_VACANCY_BATCH_ONCE_PER_DAY
        and AUTO_POLL_MODE != "always"
        and _poll_now
        and not _skip_auto_batch
        and (EMAIL_ENABLED or SOURCES_ENABLED or (SCRAPER_EMAIL and SCRAPER_PASSWORD))
    ):
        state["vacancy_batch_date"] = today
    _save_state(state)


async def _scheduler_loop(app: Application) -> None:
    interval_sec = max(CHECK_INTERVAL_MIN, 1) * 60
    while True:
        try:
            await _scheduler_tick_app(app)
        except Exception as exc:
            logger.warning("scheduler_tick_failed: %s", exc)
        await asyncio.sleep(interval_sec)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    if update.effective_chat:
        st = _load_state()
        st["report_chat_id"] = update.effective_chat.id
        _save_state(st)
    logger.info("cmd_start chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    await update.message.reply_text(
        f"{BOT_NAME}: send vacancy text and I will classify it.\n"
        "Commands:\n"
        "/classify <text>\n"
        "/inbox_now\n"
        "/pause\n"
        "/resume\n"
        "/rules\n"
        "/add_exclusion <term>\n"
        "/add_inclusion <term>\n"
        "/list_exclusions\n"
        "/email_config\n"
        "/registry [N]\n"
        "/registry_high [N]\n"
        "/clear_registry\n"
        "── CV / Мастер-профиль ──\n"
        "/cv_add [имя] — добавить CV-источник (ответь на сообщение или отправь файл PDF/DOCX)\n"
        "/cv_list — список добавленных источников\n"
        "/cv_del N — удалить источник #N\n"
        "/cv_master_build — собрать мастер-CV из всех источников + извлечь факторы\n"
        "/cv_master_show — показать текущий мастер-CV\n"
        "/cv_factors — показать ключевые факторы ATS\n"
        "/cv_factors refresh — переизвлечь факторы\n"
        "/cv <text> — задать CV-профиль вручную (без сборки мастера)\n"
        "/cv_show — показать текущий профиль\n"
        "/cv_clear — удалить все CV-данные"
    )


async def cmd_classify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("cmd_classify chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if await _deny_if_needed(update):
        return
    if update.effective_chat:
        st = _load_state()
        st["report_chat_id"] = update.effective_chat.id
        _save_state(st)
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(f"{BOT_NAME}: usage /classify <vacancy text>")
        return
    await update.message.reply_text(_format_result(text))


async def cmd_add_exclusion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("cmd_add_exclusion chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if await _deny_if_needed(update):
        return
    term = " ".join(context.args).strip().lower()
    if not term:
        await update.message.reply_text(f"{BOT_NAME}: usage /add_exclusion <term>")
        return
    data = _load_overrides()
    items = [str(x).strip().lower() for x in data.get("extra_exclusions", []) if str(x).strip()]
    if term in items:
        await update.message.reply_text(f"{BOT_NAME}: already exists: {term}")
        return
    items.append(term)
    data["extra_exclusions"] = sorted(set(items))
    _save_overrides(data)
    await update.message.reply_text(f"{BOT_NAME}: exclusion added: {term}")


async def cmd_add_inclusion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("cmd_add_inclusion chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if await _deny_if_needed(update):
        return
    term = " ".join(context.args).strip().lower()
    if not term:
        await update.message.reply_text(f"{BOT_NAME}: usage /add_inclusion <term>")
        return
    data = _load_overrides()
    items = [str(x).strip().lower() for x in data.get("extra_inclusions", []) if str(x).strip()]
    if term in items:
        await update.message.reply_text(f"{BOT_NAME}: already exists: {term}")
        return
    items.append(term)
    data["extra_inclusions"] = sorted(set(items))
    _save_overrides(data)
    await update.message.reply_text(f"{BOT_NAME}: inclusion added: {term}")


async def cmd_list_exclusions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("cmd_list_exclusions chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if await _deny_if_needed(update):
        return
    data = _load_overrides()
    items = [str(x).strip() for x in data.get("extra_exclusions", []) if str(x).strip()]
    if not items:
        await update.message.reply_text(f"{BOT_NAME}: no custom exclusions.")
        return
    await update.message.reply_text(
        f"{BOT_NAME}: custom exclusions ({len(items)}):\n- " + "\n- ".join(items[:50])
    )


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("cmd_rules chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if await _deny_if_needed(update):
        return
    data = _load_overrides()
    st = _load_state()
    ex = [str(x).strip() for x in data.get("extra_exclusions", []) if str(x).strip()]
    inc = [str(x).strip() for x in data.get("extra_inclusions", []) if str(x).strip()]
    await update.message.reply_text(
        f"{BOT_NAME}: rules\n"
        f"Custom exclusions: {len(ex)}\n"
        f"Custom inclusions: {len(inc)}\n"
        f"IMAP mode: {IMAP_MODE}\n"
        f"Auto poll mode: {AUTO_POLL_MODE}\n"
        f"Registry non-match logging: {'on' if REGISTRY_INCLUDE_NON_MATCH else 'off'}\n"
        f"Night window: {NIGHT_START_HOUR:02d}:00-{NIGHT_END_HOUR:02d}:00\n"
        f"Morning batch: {MORNING_START_HOUR:02d}:00-{MORNING_END_HOUR:02d}:00\n"
        f"Report: {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}\n"
        f"Local LLM validate: {'on' if LLM_ENABLED else 'off'} ({LLM_MODEL})\n"
        f"CV filter: {'on' if CV_ENABLED else 'off'} (model {CV_MODEL or LLM_MODEL})\n"
        f"CV profile: {'set (' + str(len((st.get('cv_profile') or ''))) + ' chars)' if (st.get('cv_profile') or '').strip() else 'not set — /cv'}\n"
        f"Top exclusions: {', '.join(ex[:8]) or '-'}\n"
        f"Top inclusions: {', '.join(inc[:8]) or '-'}"
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("cmd_pause chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if await _deny_if_needed(update):
        return
    st = _load_state()
    st["paused"] = True
    _save_state(st)
    await update.message.reply_text(f"{BOT_NAME}: paused.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("cmd_resume chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if await _deny_if_needed(update):
        return
    st = _load_state()
    st["paused"] = False
    if update.effective_chat:
        st["report_chat_id"] = update.effective_chat.id
    _save_state(st)
    await update.message.reply_text(f"{BOT_NAME}: resumed.")


async def cmd_cv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save candidate profile text for CV-based ranking (high / medium tiers; drop hidden)."""
    if await _deny_if_needed(update):
        return
    args_text = " ".join(context.args).strip() if context.args else ""
    reply = ""
    if update.message and update.message.reply_to_message and update.message.reply_to_message.text:
        reply = update.message.reply_to_message.text.strip()
    text = args_text or reply
    if not text:
        await update.message.reply_text(
            f"{BOT_NAME}: укажи текст после /cv или ответь /cv на сообщение с профилем/CV.\n"
            "Нужно: целевые роли, регионы, отрасль, уровень. В .env: JOB_FILTER_CV_ENABLED=1."
        )
        return
    st = _load_state()
    st["cv_profile"] = text
    st["cv_profile_updated"] = datetime.now().isoformat(timespec="seconds")
    if update.effective_chat:
        st["report_chat_id"] = update.effective_chat.id
    _save_state(st)
    await update.message.reply_text(
        f"{BOT_NAME}: профиль CV сохранён ({len(text)} симв.). "
        "В дайджесте: ⭐ высокое соответствие, затем ○ среднее; низкое не показывается."
    )


async def cmd_cv_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    st = _load_state()
    p = (st.get("cv_profile") or "").strip()
    if not p:
        await update.message.reply_text(f"{BOT_NAME}: профиль не задан. /cv <текст> или ответь /cv на сообщение.")
        return
    tail = "\n…" if len(p) > 3800 else ""
    await update.message.reply_text(f"{BOT_NAME}: CV profile:\n{p[:3800]}{tail}")


async def cmd_cv_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    st = _load_state()
    st.pop("cv_profile", None)
    st.pop("cv_profile_updated", None)
    st.pop("cv_master_built_at", None)
    st.pop("cv_key_factors", None)
    st.pop("cv_key_factors_updated", None)
    st.pop("cv_sources", None)
    _save_state(st)
    await update.message.reply_text(
        f"{BOT_NAME}: все CV-данные удалены (мастер-CV, источники, ключевые факторы). "
        "Дайджесты снова без разбиения по CV."
    )


async def cmd_cv_factors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extract and show CV key factors. Usage: /cv_factors (shows stored), or /cv_factors refresh."""
    if await _deny_if_needed(update):
        return
    st = _load_state()
    args = context.args or []
    refresh = args and args[0].lower() in ("refresh", "update", "обновить", "re")

    stored_raw = st.get("cv_key_factors")
    if stored_raw and not refresh:
        try:
            d = json.loads(stored_raw)
            kf = CvKeyFactors(**{k: v for k, v in d.items() if k in CvKeyFactors.__dataclass_fields__})
            updated = st.get("cv_key_factors_updated", "")
            await update.message.reply_text(
                kf.telegram_summary() + (f"\n\n<i>Обновлено: {updated}</i>" if updated else ""),
                parse_mode="HTML",
            )
            return
        except Exception:
            pass  # fall through to re-extract

    cv_text = (st.get("cv_profile") or "").strip()
    if not cv_text:
        await update.message.reply_text(
            f"{BOT_NAME}: сначала добавь CV (/cv_add или отправь файл PDF/DOCX) и собери мастер (/cv_master_build), "
            "или задай профиль вручную (/cv <текст>), затем /cv_factors."
        )
        return

    await update.message.reply_text(f"⏳ Извлекаю ключевые факторы из CV…")
    try:
        kf = await extract_key_factors_async(cv_text)
    except Exception as exc:
        await update.message.reply_text(f"{BOT_NAME}: ошибка извлечения: {exc!s}"[:300])
        return

    if not kf.extract_ok:
        await update.message.reply_text(f"{BOT_NAME}: не удалось извлечь факторы: {kf.error}")
        return

    st["cv_key_factors"] = json.dumps(kf.to_dict(), ensure_ascii=False)
    st["cv_key_factors_updated"] = datetime.now().isoformat(timespec="seconds")
    _save_state(st)

    await update.message.reply_text(kf.telegram_summary(), parse_mode="HTML")


def _load_cv_key_factors(state: dict) -> CvKeyFactors | None:
    """Load CvKeyFactors from state dict, or None if not present / invalid."""
    raw = state.get("cv_key_factors")
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return CvKeyFactors(**{k: v for k, v in d.items() if k in CvKeyFactors.__dataclass_fields__})
    except Exception:
        return None


# ── Multi-CV source management ───────────────────────────────────────────────

_CV_SOURCES_MAX = 10   # max stored CV source texts


def _cv_sources_load(state: dict) -> list[dict]:
    raw = state.get("cv_sources")
    if isinstance(raw, list):
        return raw
    return []


def _cv_sources_save(state: dict, sources: list[dict]) -> None:
    state["cv_sources"] = sources[-_CV_SOURCES_MAX:]


async def cmd_cv_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a CV text to the multi-source pool. Usage: /cv_add [name] — then reply to CV text, or pass text inline."""
    if await _deny_if_needed(update):
        return
    args = context.args or []
    name_arg = args[0].strip() if args else ""
    inline_text = " ".join(args[1:]).strip() if len(args) > 1 else (" ".join(args).strip() if not name_arg else "")
    # if first arg looks like a name (no spaces, <= 30 chars) treat it as label
    if name_arg and " " not in name_arg and len(name_arg) <= 30:
        text = inline_text
    else:
        text = " ".join(args).strip()
        name_arg = ""

    if not text and update.message and update.message.reply_to_message:
        text = (update.message.reply_to_message.text or "").strip()

    if not text:
        await update.message.reply_text(
            f"{BOT_NAME}: /cv_add [имя] — ответь командой на сообщение с CV или передай текст.\n"
            "Пример: /cv_add cv1 <текст> или ответь /cv_add cv1 на сообщение."
        )
        return

    st = _load_state()
    sources = _cv_sources_load(st)
    idx = len(sources) + 1
    label = name_arg or f"CV-{idx}"
    sources.append({"name": label, "text": text, "added_at": datetime.now().isoformat(timespec="seconds")})
    _cv_sources_save(st, sources)
    _save_state(st)
    await update.message.reply_text(
        f"{BOT_NAME}: источник «{label}» добавлен (#{len(st['cv_sources'])}, {len(text)} симв.). "
        f"Всего источников: {len(st['cv_sources'])}. Запусти /cv_master_build для сборки мастер-CV."
    )


async def cmd_cv_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all stored CV sources."""
    if await _deny_if_needed(update):
        return
    st = _load_state()
    sources = _cv_sources_load(st)
    if not sources:
        await update.message.reply_text(
            f"{BOT_NAME}: нет сохранённых CV-источников. Используй /cv_add или отправь файл PDF/DOCX/TXT."
        )
        return
    lines = [f"{BOT_NAME}: CV-источники ({len(sources)}):"]
    for i, s in enumerate(sources, 1):
        lines.append(f"  {i}. <b>{_html_escape(s['name'])}</b> — {len(s['text'])} симв., {s.get('added_at','?')}")
    master_at = st.get("cv_master_built_at", "")
    if master_at:
        lines.append(f"\n🏗 Мастер-CV собран: {master_at}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_cv_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a CV source by 1-based index. Usage: /cv_del N"""
    if await _deny_if_needed(update):
        return
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text(f"{BOT_NAME}: укажи номер источника: /cv_del N (см. /cv_list).")
        return
    n = int(args[0])
    st = _load_state()
    sources = _cv_sources_load(st)
    if n < 1 or n > len(sources):
        await update.message.reply_text(f"{BOT_NAME}: нет источника #{n}. Всего: {len(sources)}.")
        return
    removed = sources.pop(n - 1)
    _cv_sources_save(st, sources)
    _save_state(st)
    await update.message.reply_text(
        f"{BOT_NAME}: источник #{n} «{removed['name']}» удалён. Осталось: {len(sources)}."
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document uploads (PDF/DOCX/TXT) — parse and add as CV source."""
    if await _deny_if_needed(update):
        return
    doc = update.message.document
    if not doc:
        return
    fname = doc.file_name or "document"
    ext = Path(fname).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt", ".md"):
        await update.message.reply_text(
            f"{BOT_NAME}: поддерживаются PDF, DOCX, TXT, MD. Получен: {fname}"
        )
        return

    await update.message.reply_text(f"⏳ Скачиваю и парсю «{fname}»…")
    tg_file = await doc.get_file()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        await tg_file.download_to_drive(str(tmp_path))

        loop = asyncio.get_event_loop()
        try:
            from skill_cv_parser import parse_cv as _parse_cv_file, _extract_text as _cv_extract_text
            cv_text = await loop.run_in_executor(None, lambda: _cv_extract_text(tmp_path))
        except (ImportError, Exception):
            cv_text = ""

        if not cv_text.strip():
            await update.message.reply_text(f"{BOT_NAME}: не удалось извлечь текст из «{fname}».")
            return

        st = _load_state()
        sources = _cv_sources_load(st)
        label = Path(fname).stem
        sources.append({"name": label, "text": cv_text, "added_at": datetime.now().isoformat(timespec="seconds")})
        _cv_sources_save(st, sources)
        _save_state(st)
        await update.message.reply_text(
            f"{BOT_NAME}: «{fname}» добавлен как источник «{label}» ({len(cv_text)} симв.). "
            f"Всего источников: {len(st['cv_sources'])}. Запусти /cv_master_build."
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


async def cmd_cv_master_build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Build master CV from all stored sources via cv_merge pipeline, then auto-extract key factors."""
    if await _deny_if_needed(update):
        return
    st = _load_state()
    sources = _cv_sources_load(st)
    if not sources:
        await update.message.reply_text(
            f"{BOT_NAME}: нет источников. Добавь CV через /cv_add или отправь файл."
        )
        return

    await update.message.reply_text(
        f"⏳ Запускаю сборку мастер-CV из {len(sources)} источника(ов)… (может занять 1-5 мин)"
    )

    loop = asyncio.get_event_loop()
    try:
        out_text, err_msg = await loop.run_in_executor(None, lambda: _run_master_cv_build(sources))
    except Exception as exc:
        await update.message.reply_text(f"{BOT_NAME}: ошибка сборки мастер-CV: {exc!s}"[:400])
        return

    if err_msg:
        await update.message.reply_text(f"{BOT_NAME}: предупреждение при сборке: {err_msg}"[:400])
    if not out_text:
        await update.message.reply_text(f"{BOT_NAME}: пайплайн не вернул текст мастер-CV.")
        return

    st = _load_state()
    st["cv_profile"] = out_text
    st["cv_profile_updated"] = datetime.now().isoformat(timespec="seconds")
    st["cv_master_built_at"] = datetime.now().isoformat(timespec="seconds")
    st.pop("cv_key_factors", None)
    st.pop("cv_key_factors_updated", None)
    _save_state(st)

    await update.message.reply_text(
        f"{BOT_NAME}: мастер-CV собран ({len(out_text)} симв.). Извлекаю ключевые факторы…"
    )
    try:
        kf = await extract_key_factors_async(out_text)
    except Exception as exc:
        await update.message.reply_text(f"{BOT_NAME}: мастер-CV сохранён, но ошибка факторов: {exc!s}"[:300])
        return

    if not kf.extract_ok:
        await update.message.reply_text(f"{BOT_NAME}: мастер-CV сохранён, факторы не извлечены: {kf.error}")
        return

    st = _load_state()
    st["cv_key_factors"] = json.dumps(kf.to_dict(), ensure_ascii=False)
    st["cv_key_factors_updated"] = datetime.now().isoformat(timespec="seconds")
    _save_state(st)

    await update.message.reply_text(
        kf.telegram_summary() + "\n\n✅ Мастер-CV активен. Вакансии будут ранжироваться по этому профилю.",
        parse_mode="HTML",
    )


def _run_master_cv_build(sources: list[dict]) -> tuple[str, str]:
    """Sync: write sources to temp dir, run cv_merge pipeline, return (master_text, warn_msg)."""
    try:
        from cv_merge.cv_master_pipeline import run_pipeline as _cv_pipeline
    except ImportError as e:
        return "", f"cv_merge not available: {e}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        src_paths: list[Path] = []
        for i, s in enumerate(sources):
            p = tmp / f"source_{i+1}_{s['name'][:30]}.txt"
            p.write_text(s["text"], encoding="utf-8")
            src_paths.append(p)

        out_dir = tmp / "out"
        try:
            report = _cv_pipeline(src_paths, out_dir)
        except Exception as exc:
            return "", str(exc)

        master_path = out_dir / "master_cv.md"
        if not master_path.is_file():
            return "", "master_cv.md не создан пайплайном"

        master_text = master_path.read_text(encoding="utf-8")
        stages = report.get("stages", [])
        errs = [s.get("validation_errors") for s in stages if s.get("validation_errors")]
        warn = "; ".join(str(e) for e in errs if e) if errs else ""
        return master_text, warn


async def cmd_cv_master_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current master CV text (same as /cv_show but explicit label)."""
    if await _deny_if_needed(update):
        return
    st = _load_state()
    p = (st.get("cv_profile") or "").strip()
    if not p:
        await update.message.reply_text(
            f"{BOT_NAME}: мастер-CV не задан. Добавь источники (/cv_add) и запусти /cv_master_build."
        )
        return
    built_at = st.get("cv_master_built_at", st.get("cv_profile_updated", ""))
    tail = "\n…" if len(p) > 3800 else ""
    header = f"🏗 <b>Мастер-CV</b>" + (f" (собран: {built_at})" if built_at else "") + "\n\n"
    await update.message.reply_text(header + _html_escape(p[:3700]) + tail, parse_mode="HTML")


def _html_escape(text: str) -> str:
    """Minimal HTML escape for Telegram messages."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_scan_results_body(matching: list[dict]) -> str:
    """HTML body: jobs grouped by source and rule priority (no footer stats)."""
    if not matching:
        return ""
    _PRIO_ICONS = {
        "HIGH PRIORITY": "🔴",
        "HIGH PRIORITY (DIGITAL)": "🟣",
        "MEDIUM PRIORITY": "🟡",
    }
    _PRIO_ORDER = ["HIGH PRIORITY", "HIGH PRIORITY (DIGITAL)", "MEDIUM PRIORITY"]
    _SRC_NAMES = {
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "seek": "SEEK",
        "naukrigulf": "NaukriGulf",
        "mycareersfuture": "MyCareersFuture SG",
        "jobstreet": "JobStreet",
        "rigzone": "Rigzone",
    }
    _SRC_ORDER = ["linkedin", "indeed", "seek", "naukrigulf", "mycareersfuture", "jobstreet", "rigzone"]

    by_source: dict[str, dict[str, list[dict]]] = {}
    for v in matching:
        src = v.get("source", "other")
        prio = v.get("priority", "MEDIUM PRIORITY")
        by_source.setdefault(src, {}).setdefault(prio, []).append(v)

    lines: list[str] = []
    sources = [s for s in _SRC_ORDER if s in by_source]
    sources += [s for s in by_source if s not in _SRC_ORDER]

    for src in sources:
        prio_groups = by_source[src]
        src_name = _SRC_NAMES.get(src, src.capitalize())
        lines.append(f"\n<b>📡 {src_name}</b>")
        for prio_label in _PRIO_ORDER:
            items = prio_groups.get(prio_label, [])
            if not items:
                continue
            icon = _PRIO_ICONS.get(prio_label, "⚪")
            lines.append(f"{icon} <b>{prio_label}</b> ({len(items)})")
            for v in items:
                title = v.get("title", "")
                url = v.get("url", "")
                company = v.get("company", "")
                location = v.get("location", "")
                loc_tag = ""
                if location:
                    loc_short = location.split(" - ")[0].split(",")[0].strip()
                    if loc_short:
                        loc_tag = f" ({_html_escape(loc_short)})"
                if url:
                    line = f"  <a href=\"{url}\">{_html_escape(title)}</a>{loc_tag}"
                else:
                    line = f"  {_html_escape(title)}{loc_tag}"
                if company:
                    line += f"\n    🏢 {_html_escape(company)}"
                industry = (v.get("industry") or "").strip()
                if industry:
                    line += f"\n    🏭 {_html_escape(industry)}"
                lines.append(line)

    return "\n".join(lines).strip()


def _format_scan_results(
    matching: list[dict],
    seen: int,
    high: int,
    digital: int,
    medium: int,
    ignore: int,
    label: str = "Scan",
) -> str:
    """Format scan results grouped by source platform, then by priority, with location."""
    body = _format_scan_results_body(matching)
    stats = f"\n📊 {label}: новых={seen} 🔴{high} 🟣{digital} 🟡{medium} ⚪{ignore}"
    if body:
        return f"{body}{stats}"
    return stats.strip()


def _format_cv_tiered_scan_results(
    high_jobs: list[dict],
    med_jobs: list[dict],
    seen: int,
    high: int,
    digital: int,
    medium: int,
    ignore: int,
    label: str,
    cv_dropped: int,
) -> str:
    """Сначала блок с высоким соответствием CV, затем средний; низкий уже отброшен."""
    parts: list[str] = []
    if high_jobs:
        parts.append("<b>⭐ CV: высокое соответствие</b>" + _format_scan_results_body(high_jobs))
    if med_jobs:
        parts.append("<b>○ CV: среднее соответствие</b>" + _format_scan_results_body(med_jobs))
    if not parts:
        return ""
    body = "\n\n".join(parts)
    stats = f"\n📊 {label}: новых={seen} 🔴{high} 🟣{digital} 🟡{medium} ⚪{ignore} 🔻CV−={cv_dropped}"
    return f"{body}{stats}"


async def _scan_sources_and_notify(
    application: Application,
    manual_chat_id: int | None = None,
    days: int | None = None,
) -> str:
    """Fetch jobs from LinkedIn, Indeed (RSS + AU mobile), SEEK (AU), classify, save to registry, notify."""
    if not SOURCES_ENABLED and manual_chat_id is None:
        return ""
    from job_sources import fetch_all_sources
    state = _load_state()
    cfg = _build_config()
    now_ts = datetime.now().isoformat(timespec="seconds")
    target_chat = manual_chat_id or int(state.get("report_chat_id") or 0) or REPORT_CHAT_ID

    fetch_days = days if days is not None else SOURCE_DAYS
    logger.info(
        "scan_sources start queries=%d match_queries=%d visa_dama=%d locations=%d days=%d seek=%s",
        len(SOURCE_QUERIES),
        len(SOURCE_QUERIES_MATCH),
        len(SOURCE_VISA_DAMA_QUERIES),
        len(SOURCE_LOCATIONS),
        fetch_days,
        SOURCE_SEEK,
    )

    try:
        jobs = await fetch_all_sources(
            SOURCE_QUERIES,
            SOURCE_LOCATIONS,
            days=fetch_days,
            enable_indeed=SOURCE_INDEED,
            enable_linkedin=SOURCE_LINKEDIN,
            enable_seek=SOURCE_SEEK,
            visa_dama_queries=SOURCE_VISA_DAMA_QUERIES,
        )
    except Exception as exc:
        logger.exception("scan_sources_fetch_failed: %s", exc)
        return f"{BOT_NAME}: source fetch failed: {exc!s}"

    if not jobs:
        logger.info("scan_sources: no jobs returned")
        return ""

    registry = state.get("registry", [])
    known_urls, known_sigs = _build_dedup_set(registry, days=7)

    candidates: list[dict] = []
    seen_count = high_count = digital_count = medium_count = ignore_count = dup_count = 0

    for job in jobs:
        title = job.get("title", "").strip()
        url = job.get("url", "").strip()
        company = job.get("company", "").strip()
        location = job.get("location", "").strip()
        if not title:
            continue
        if _is_duplicate(job, known_urls, known_sigs):
            dup_count += 1
            continue

        seen_count += 1
        description = job.get("description", "").strip()
        classify_text = title + (f" {company}" if company else "") + (f" {description[:200]}" if description else "")
        base = classify_job(classify_text, cfg, title=title)
        prio, _score, reasons = _apply_inclusion_if_needed(classify_text, base)
        if prio == Priority.IGNORE:
            from job_filter import normalize_text
            title_norm = normalize_text(title)
            query_roles = {normalize_text(q) for q in SOURCE_QUERIES_MATCH}
            if any(title_norm == qr or title_norm.startswith(qr + " ") or title_norm.startswith("senior " + qr) or title_norm.startswith("lead " + qr) for qr in query_roles):
                prio = Priority.MEDIUM
                reasons = [f"Query-role match boost: title starts with search query"]
        logger.info(
            "source_vacancy prio=%s title=%r url=%s reason=%s",
            prio.value, title[:80], url[:80], (reasons or ["?"])[0][:60],
        )
        _update_daily_counts(state, prio)
        if prio == Priority.HIGH: high_count += 1
        elif prio == Priority.HIGH_DIGITAL: digital_count += 1
        elif prio == Priority.MEDIUM: medium_count += 1
        else: ignore_count += 1

        if prio in {Priority.HIGH, Priority.HIGH_DIGITAL, Priority.MEDIUM}:
            candidates.append(
                {
                    "title": title,
                    "url": url,
                    "priority": prio.value,
                    "source": job.get("source", ""),
                    "company": company,
                    "location": location,
                    "description": description[:800],
                    "date_str": job.get("date_str", ""),
                    "firecrawl_enriched": bool(job.get("firecrawl_enriched", False)),
                }
            )
            if url:
                known_urls.add(url)
            from job_filter import normalize_text as _nt
            known_sigs.add(f"{_nt(title)}|{_nt(company)}|{_nt(location)}")

    fit_by_idx = await _cv_compute_fits_async(candidates, state)

    # ── Enrich candidates with full job descriptions before scoring ───────────
    try:
        from job_scraper import enrich_jobs_with_descriptions as _enrich
        await _enrich(candidates, max_concurrent=4)
    except Exception as _enrich_err:
        logger.warning("description enrichment failed: %s", _enrich_err)

    # ── CV Key Factors scoring (percentage match + urgency routing) ──────────
    cv_kf = _load_cv_key_factors(state)
    urgent_matches: list[tuple[dict, MatchResult]] = []
    digest_matches: list[tuple[dict, MatchResult]] = []
    if cv_kf and cv_kf.extract_ok:
        scored = score_jobs_batch(cv_kf, candidates)
        for job, match in scored:
            if match.tier == "urgent":
                urgent_matches.append((job, match))
            elif match.tier == "digest":
                digest_matches.append((job, match))
        # Store match scores back into candidates for registry
        score_map = {job["url"]: match.score for job, match in scored}
    else:
        score_map = {}

    for i, c in enumerate(candidates):
        _registry_append(
            state,
            {
                "ts": now_ts,
                "registered_at": now_ts,
                "notified_at": now_ts,
                "uid": 0,
                "date": c.get("date_str", ""),
                "from": c.get("source", ""),
                "title": c["title"],
                "url": c.get("url", ""),
                "company": c.get("company", ""),
                "location": c.get("location", ""),
                "industry": (c.get("industry") or "").strip(),
                "priority": c["priority"],
                "status": "sent",
                "cv_fit": fit_by_idx.get(i, "high"),
                "cv_score": score_map.get(c.get("url", ""), 0),
                "firecrawl_enriched": bool(c.get("firecrawl_enriched", False)),
            },
        )

    # ── Send urgent CV matches immediately ───────────────────────────────────
    if urgent_matches and target_chat:
        lines = [f"🚨 <b>Срочно! {len(urgent_matches)} вакансии с высоким совпадением CV (≥{URGENT_THRESHOLD}%)</b>\n"]
        for job, match in urgent_matches[:10]:
            lines.append(match.telegram_line(job))
            lines.append("")
        urgent_msg = "\n".join(lines)
        try:
            await application.bot.send_message(
                chat_id=target_chat, text=urgent_msg[:4000],
                parse_mode="HTML", disable_web_page_preview=True,
            )
            logger.info("scan_sources: sent %d urgent CV matches", len(urgent_matches))
        except Exception as exc:
            logger.warning("scan_sources urgent send failed: %s", exc)

    high_j, med_j, cv_drop = _split_candidates_cv_tiers(candidates, fit_by_idx)

    # Deduplicate: remove jobs already sent as urgent ATS matches from digest tiers
    if urgent_matches:
        urgent_urls = {job.get("url", "") for job, _ in urgent_matches if job.get("url")}
        high_j = [j for j in high_j if j.get("url", "") not in urgent_urls]
        med_j = [j for j in med_j if j.get("url", "") not in urgent_urls]

    _save_state(state)

    if not candidates or not target_chat:
        logger.info(
            "scan_sources done: seen=%d candidates=%d dup=%d target_chat=%s",
            seen_count,
            len(candidates),
            dup_count,
            target_chat,
        )
        return ""

    use_cv_tiers = CV_ENABLED and bool((state.get("cv_profile") or "").strip())
    if use_cv_tiers and not high_j and not med_j:
        logger.info("scan_sources: all %d candidates dropped by CV filter", len(candidates))
        note = (
            f"{BOT_NAME}: RSS/Public — по профилю CV все {len(candidates)} вакансий с низким соответствием "
            f"(не показаны). 🔻CV−={cv_drop}"
        )
        if digest_matches:
            note += f"\n📊 CV Key Factors: {len(digest_matches)} в утренний дайджест ({DIGEST_THRESHOLD}-{URGENT_THRESHOLD}%)"
        try:
            await application.bot.send_message(chat_id=target_chat, text=note[:3500])
        except Exception as exc:
            logger.warning("scan_sources_cv_all_dropped_send_failed: %s", exc)
        return ""

    # ── Build digest message ─────────────────────────────────────────────────
    if use_cv_tiers:
        msg = _format_cv_tiered_scan_results(
            high_j,
            med_j,
            seen_count,
            high_count,
            digital_count,
            medium_count,
            ignore_count,
            "RSS/Public",
            cv_drop,
        )
        # Append CV Key Factors digest tier if available
        if digest_matches:
            kf_lines = [f"\n\n📊 <b>CV Key Factors ({DIGEST_THRESHOLD}-{URGENT_THRESHOLD}%):</b>"]
            for job, match in digest_matches[:8]:
                kf_lines.append(match.telegram_line(job))
            msg = msg + "\n".join(kf_lines)
    else:
        flat = [_strip_candidate_for_display(c) for c in candidates]
        flat = _sort_jobs_by_rule_priority(flat)
        msg = _format_scan_results(
            flat, seen_count, high_count, digital_count, medium_count, ignore_count, label="RSS/Public"
        )

    try:
        await application.bot.send_message(chat_id=target_chat, text=msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        try:
            await application.bot.send_message(chat_id=target_chat, text=msg, disable_web_page_preview=True)
        except Exception as exc:
            logger.warning("scan_sources_send_failed: %s", exc)
    return ""


async def _scraper_scan_and_notify(
    application: Application,
    manual_chat_id: int | None = None,
) -> None:
    """Run Playwright browser scraper across all sites, classify, save to registry, notify."""
    from job_scraper import scrape_all_sites
    state = _load_state()
    cfg = _build_config()
    now_ts = datetime.now().isoformat(timespec="seconds")
    target_chat = manual_chat_id or int(state.get("report_chat_id") or 0) or REPORT_CHAT_ID

    logger.info("scraper_scan start pages=%d", SCRAPER_PAGES)
    try:
        jobs = await scrape_all_sites(pages=SCRAPER_PAGES)
    except Exception as exc:
        logger.exception("scraper_scan_failed: %s", exc)
        if target_chat:
            await application.bot.send_message(chat_id=target_chat, text=f"JobLocator: browser scan failed: {exc!s}"[:300])
        return

    registry = state.get("registry", [])
    known_urls, known_sigs = _build_dedup_set(registry, days=7)
    candidates: list[dict] = []
    seen_count = high_count = digital_count = medium_count = ignore_count = dup_count = 0

    for job in jobs:
        title = job.get("title", "").strip()
        url = job.get("url", "").strip()
        company = job.get("company", "").strip()
        location = job.get("location", "").strip()
        if not title:
            continue
        if _is_duplicate(job, known_urls, known_sigs):
            dup_count += 1
            continue

        seen_count += 1
        description = job.get("description", "").strip()
        classify_text = title + (f" {company}" if company else "") + (f" {description[:200]}" if description else "")
        base = classify_job(classify_text, cfg, title=title)
        prio, _score, reasons = _apply_inclusion_if_needed(classify_text, base)
        if prio == Priority.IGNORE:
            from job_filter import normalize_text
            title_norm = normalize_text(title)
            query_roles = {normalize_text(q) for q in SOURCE_QUERIES_MATCH}
            if any(title_norm == qr or title_norm.startswith(qr + " ") or title_norm.startswith("senior " + qr) or title_norm.startswith("lead " + qr) for qr in query_roles):
                prio = Priority.MEDIUM
                reasons = ["Query-role match boost"]
        logger.info("scraper_vacancy prio=%s src=%s title=%r company=%r", prio.value, job.get("source",""), title[:80], company[:40])
        _update_daily_counts(state, prio)
        if prio == Priority.HIGH: high_count += 1
        elif prio == Priority.HIGH_DIGITAL: digital_count += 1
        elif prio == Priority.MEDIUM: medium_count += 1
        else: ignore_count += 1

        if prio in {Priority.HIGH, Priority.HIGH_DIGITAL, Priority.MEDIUM}:
            candidates.append(
                {
                    "title": title,
                    "url": url,
                    "priority": prio.value,
                    "source": job.get("source", ""),
                    "company": company,
                    "location": location,
                    "description": description[:800],
                    "registry_date": now_ts,
                }
            )
            if url:
                known_urls.add(url)
            from job_filter import normalize_text as _nt
            known_sigs.add(f"{_nt(title)}|{_nt(company)}|{_nt(location)}")

    fit_by_idx = await _cv_compute_fits_async(candidates, state)
    for i, c in enumerate(candidates):
        _registry_append(
            state,
            {
                "ts": now_ts,
                "registered_at": now_ts,
                "notified_at": now_ts,
                "uid": 0,
                "date": c.get("registry_date", now_ts),
                "from": c.get("source", ""),
                "title": c["title"],
                "url": c.get("url", ""),
                "company": c.get("company", ""),
                "location": c.get("location", ""),
                "industry": (c.get("industry") or "").strip(),
                "priority": c["priority"],
                "status": "sent",
                "cv_fit": fit_by_idx.get(i, "high"),
            },
        )

    high_j, med_j, cv_drop = _split_candidates_cv_tiers(candidates, fit_by_idx)

    # Mark today as scanned in the 7-week schedule
    from datetime import date
    state["scraper_last_scan_date"] = date.today().isoformat()
    _save_state(state)

    if not candidates or not target_chat:
        logger.info("scraper_scan done: seen=%d candidates=%d", seen_count, len(candidates))
        return

    use_cv_tiers = CV_ENABLED and bool((state.get("cv_profile") or "").strip())
    if use_cv_tiers and not high_j and not med_j:
        logger.info("scraper_scan: all %d candidates dropped by CV filter", len(candidates))
        note = (
            f"{BOT_NAME}: Browser — по профилю CV все {len(candidates)} вакансий с низким соответствием "
            f"(не показаны). 🔻CV−={cv_drop}"
        )
        try:
            await application.bot.send_message(chat_id=target_chat, text=note[:3500])
        except Exception as exc:
            logger.warning("scraper_cv_all_dropped_send_failed: %s", exc)
        return

    if use_cv_tiers:
        msg = _format_cv_tiered_scan_results(
            high_j,
            med_j,
            seen_count,
            high_count,
            digital_count,
            medium_count,
            ignore_count,
            "Browser",
            cv_drop,
        )
    else:
        flat = [_strip_candidate_for_display(c) for c in candidates]
        flat = _sort_jobs_by_rule_priority(flat)
        msg = _format_scan_results(
            flat, seen_count, high_count, digital_count, medium_count, ignore_count, label="Browser"
        )

    try:
        await application.bot.send_message(chat_id=target_chat, text=msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        try:
            await application.bot.send_message(chat_id=target_chat, text=msg, disable_web_page_preview=True)
        except Exception as exc:
            logger.warning("scraper_scan_send_failed: %s", exc)


# Global OTP queue — shared between cmd_otp and login_indeed
_OTP_QUEUE: asyncio.Queue[str] | None = None


async def cmd_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept OTP/passkey code from user and forward to waiting login process."""
    if await _deny_if_needed(update):
        return
    from job_scraper import set_otp_queue
    code = " ".join(context.args).strip() if context.args else ""
    if not code:
        await update.message.reply_text("Использование: /otp <код>")
        return
    global _OTP_QUEUE
    if _OTP_QUEUE is None:
        await update.message.reply_text("Нет активного ожидания кода. Сначала запусти /login_sites")
        return
    await _OTP_QUEUE.put(code)
    await update.message.reply_text(f"Код принят: {code}")


async def cmd_login_sites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Login to all job sites and save sessions for the week."""
    if await _deny_if_needed(update):
        return
    if not SCRAPER_EMAIL or not SCRAPER_PASSWORD:
        await update.message.reply_text("JobLocator: JOB_SCRAPER_EMAIL / JOB_SCRAPER_PASSWORD не задан в .env")
        return

    from job_scraper import (
        login_linkedin,
        login_indeed,
        login_naukrigulf,
        login_jobleads,
        set_otp_queue,
    )

    chat_id = update.effective_chat.id if update.effective_chat else None

    # Build notify callback — sends text + optional screenshot to Telegram
    async def notify_cb(text: str, screenshot: bytes | None) -> None:
        if not chat_id:
            return
        try:
            if screenshot:
                from telegram import InputFile
                import io
                await context.application.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(io.BytesIO(screenshot), filename="screen.png"),
                    caption=text[:1024],
                )
            else:
                await context.application.bot.send_message(chat_id=chat_id, text=text[:1024])
        except Exception as exc:
            logger.warning("login_notify_cb failed: %s", exc)

    await update.message.reply_text("JobLocator: начинаю вход на сайты...")

    # Set up OTP queue for this login session
    global _OTP_QUEUE
    _OTP_QUEUE = asyncio.Queue()
    set_otp_queue(_OTP_QUEUE)

    from job_scraper import session_exists

    # force=True to re-login all; by default skip sites with existing sessions
    force = context.args and context.args[0] == "force" if context.args else False

    results = []
    try:
        # LinkedIn
        if force or not session_exists("linkedin"):
            try:
                ok = await login_linkedin(SCRAPER_EMAIL, SCRAPER_PASSWORD)
                results.append(f"{'✓' if ok else '✗'} LinkedIn")
            except Exception as exc:
                results.append(f"✗ LinkedIn: {exc!s}"[:80])
        else:
            results.append("✓ LinkedIn (сессия)")

        # Indeed — with interactive OTP support
        if force or not session_exists("indeed"):
            try:
                ok = await login_indeed(SCRAPER_EMAIL, SCRAPER_PASSWORD, notify_cb=notify_cb)
                results.append(f"{'✓' if ok else '✗'} Indeed")
            except Exception as exc:
                results.append(f"✗ Indeed: {exc!s}"[:80])
        else:
            results.append("✓ Indeed (сессия)")

        # NaukriGulf — via FlareSolverr
        if force or not session_exists("naukrigulf"):
            try:
                ok = await login_naukrigulf(SCRAPER_EMAIL, SCRAPER_PASSWORD)
                results.append(f"{'✓' if ok else '✗'} NaukriGulf")
            except Exception as exc:
                results.append(f"✗ NaukriGulf: {exc!s}"[:80])
        else:
            results.append("✓ NaukriGulf (сессия)")

        # JobLeads — temporarily disabled
        # try:
        #     ok = await login_jobleads(SCRAPER_EMAIL, SCRAPER_PASSWORD)
        #     results.append(f"{'✓' if ok else '✗'} JobLeads")
        # except Exception as exc:
        #     results.append(f"✗ JobLeads: {exc!s}"[:80])

    finally:
        set_otp_queue(None)
        _OTP_QUEUE = None

    await update.message.reply_text("Результат входа:\n" + "\n".join(results))


async def cmd_scan_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger full scan: browser scrape (LinkedIn/Indeed/NaukriGulf/Rigzone) + RSS sources."""
    if await _deny_if_needed(update):
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        st = _load_state()
        st["report_chat_id"] = chat_id
        _save_state(st)
    await update.message.reply_text(f"{BOT_NAME}: полный скан — LinkedIn, Indeed, NaukriGulf, Rigzone...")
    try:
        # Browser scraper first (authenticated sessions)
        await _scraper_scan_and_notify(context.application, manual_chat_id=chat_id)
    except Exception as exc:
        logger.exception("cmd_scan_now_browser_failed: %s", exc)
        await update.message.reply_text(f"{BOT_NAME}: browser scan failed: {exc!s}"[:300])
    try:
        # RSS / public API sources (supplemental)
        await _scan_sources_and_notify(context.application, manual_chat_id=chat_id, days=1)
    except Exception as exc:
        logger.exception("cmd_scan_now_sources_failed: %s", exc)
        await update.message.reply_text(f"{BOT_NAME}: source scan failed: {exc!s}"[:300])


async def cmd_scan_browser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger browser scan across authenticated site sessions."""
    if await _deny_if_needed(update):
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        st = _load_state()
        st["report_chat_id"] = chat_id
        _save_state(st)
    await update.message.reply_text(f"{BOT_NAME}: browser scan started (LinkedIn/Indeed/NaukriGulf/JobLeads/Rigzone)...")
    try:
        await _scraper_scan_and_notify(context.application, manual_chat_id=chat_id)
    except Exception as exc:
        logger.exception("cmd_scan_browser_failed: %s", exc)
        await update.message.reply_text(f"{BOT_NAME}: browser scan failed: {exc!s}"[:500])


async def cmd_inbox_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    logger.info("cmd_inbox_now chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is not None:
        st = _load_state()
        st["report_chat_id"] = chat_id
        _save_state(st)
    try:
        status = await _poll_mail_and_notify(context.application, manual_chat_id=chat_id)
        await update.message.reply_text(status if status else "Checked, clear.")
    except imaplib.IMAP4.error:
        await update.message.reply_text(
            f"{BOT_NAME}: IMAP auth failed. Check JOB_FILTER_EMAIL_USER / JOB_FILTER_EMAIL_PASSWORD (Google App Password)."
        )
    except Exception as exc:
        logger.exception("cmd_inbox_now_failed: %s", exc)
        await update.message.reply_text(f"{BOT_NAME}: inbox check failed: {exc!s}"[:500])


async def cmd_email_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    logger.info("cmd_email_config chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    await update.message.reply_text(_email_config_text())


def _parse_limit(args: list[str], default: int = 20, max_limit: int = 100) -> int:
    if not args:
        return default
    try:
        n = int(args[0])
        if n < 1:
            return default
        return min(n, max_limit)
    except Exception:
        return default


async def cmd_registry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    st = _load_state()
    limit = _parse_limit(context.args, default=20, max_limit=100)
    reg = st.get("registry", [])
    await update.message.reply_text(f"{BOT_NAME}: registry\n" + _format_registry_lines(reg, limit=limit))


async def cmd_registry_high(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    st = _load_state()
    limit = _parse_limit(context.args, default=20, max_limit=100)
    reg = st.get("registry", [])
    high = [x for x in reg if str(x.get("priority", "")) in {Priority.HIGH.value, Priority.HIGH_DIGITAL.value}]
    await update.message.reply_text(f"{BOT_NAME}: registry_high\n" + _format_registry_lines(high, limit=limit))


async def cmd_clear_registry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    confirm = (context.args[0].strip().lower() if context.args else "")
    st = _load_state()
    pend = st.setdefault("pending_actions", {})
    key = "clear_registry_confirm"
    if confirm == "yes" and pend.get(key):
        st["registry"] = []
        st["sent_hashes"] = []
        st["processed_uids"] = []
        pend.pop(key, None)
        _save_state(st)
        await update.message.reply_text(f"{BOT_NAME}: registry cleared.")
        return
    pend[key] = True
    _save_state(st)
    await update.message.reply_text(
        f"{BOT_NAME}: confirm clear? Send `/clear_registry yes`",
        parse_mode="Markdown",
    )


async def cmd_test_uid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch one email by UID and show extracted vacancies + raw hrefs for debugging."""
    if await _deny_if_needed(update):
        return
    if not context.args:
        await update.message.reply_text(f"{BOT_NAME}: usage: /test_uid <UID>")
        return
    try:
        uid = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text(f"{BOT_NAME}: UID must be a number.")
        return

    def _fetch_single(uid: int):
        with imaplib.IMAP4_SSL(EMAIL_IMAP_HOST, EMAIL_IMAP_PORT) as m:
            m.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            for mailbox in (EMAIL_MAILBOX, "[Gmail]/Trash", "[Gmail]/All Mail"):
                try:
                    m.select(mailbox, readonly=True)
                except Exception:
                    continue
                typ, msg_data = m.uid("fetch", str(uid), "(RFC822)")
                if typ == "OK" and msg_data:
                    for row in msg_data:
                        if isinstance(row, tuple) and row[1]:
                            return row[1]
        return None

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _fetch_single(uid))
    if not raw:
        await update.message.reply_text(f"{BOT_NAME}: UID {uid} not found in INBOX.")
        return

    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = _decode_header(msg.get("Subject", ""))
    sender = _decode_header(msg.get("From", ""))

    # Extract all hrefs from HTML
    html_parts = []
    for part in msg.walk():
        if (part.get_content_type() or "").lower() == "text/html":
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            html_parts.append(payload.decode(charset, errors="ignore"))
    html = "\n".join(html_parts)

    anchor_re = re.compile(r'<a[^>]+href=(?:["\']([^"\']+)["\']|([^\s>]+))', re.IGNORECASE)
    all_hrefs = []
    for m2 in anchor_re.finditer(html):
        raw_url = _html_unescape((m2.group(1) or m2.group(2) or "").strip())
        if raw_url.startswith("http"):
            all_hrefs.append(raw_url)

    vacancies = _extract_vacancies_from_msg(msg)
    cfg = _build_config()

    lines = [
        f"{BOT_NAME}: test UID {uid}",
        f"From: {sender[:60]}",
        f"Subject: {subject[:80]}",
        f"HTML parts: {len(html_parts)} | Total hrefs: {len(all_hrefs)}",
        f"Job hrefs matched: {len(vacancies)}",
        "",
    ]
    if vacancies:
        lines.append("Vacancies extracted:")
        for v in vacancies[:10]:
            r = classify_job(v["title"], cfg, title=v["title"])
            lines.append(f"  [{r.priority.value}] {v['title'][:70]}")
            if v.get("url"):
                lines.append(f"    {v['url'][:100]}")
    else:
        lines.append("No vacancies extracted. Sample hrefs:")
        for h in all_hrefs[:8]:
            lines.append(f"  {h[:100]}")

    await update.message.reply_text("\n".join(lines))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_needed(update):
        return
    logger.info("on_text chat_id=%s user_id=%s", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None)
    if not update.message or not update.message.text:
        return
    await update.message.reply_text(_format_result(update.message.text))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("telegram_update_failed: %s", context.error)
    upd = update if isinstance(update, Update) else None
    if upd and upd.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=upd.effective_chat.id,
                text=f"{BOT_NAME}: internal error while processing command.",
            )
        except Exception:
            pass


async def _post_init(application: Application) -> None:
    asyncio.create_task(_scheduler_loop(application))


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("JOB_FILTER_BOT_TOKEN is not set")
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("classify", cmd_classify))
    app.add_handler(CommandHandler("inbox_now", cmd_inbox_now))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("cv", cmd_cv))
    app.add_handler(CommandHandler("cv_show", cmd_cv_show))
    app.add_handler(CommandHandler("cv_clear", cmd_cv_clear))
    app.add_handler(CommandHandler("cv_factors", cmd_cv_factors))
    app.add_handler(CommandHandler("cv_add", cmd_cv_add))
    app.add_handler(CommandHandler("cv_list", cmd_cv_list))
    app.add_handler(CommandHandler("cv_del", cmd_cv_del))
    app.add_handler(CommandHandler("cv_master_build", cmd_cv_master_build))
    app.add_handler(CommandHandler("cv_master_show", cmd_cv_master_show))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("add_exclusion", cmd_add_exclusion))
    app.add_handler(CommandHandler("add_inclusion", cmd_add_inclusion))
    app.add_handler(CommandHandler("list_exclusions", cmd_list_exclusions))
    app.add_handler(CommandHandler("email_config", cmd_email_config))
    app.add_handler(CommandHandler("registry", cmd_registry))
    app.add_handler(CommandHandler("registry_high", cmd_registry_high))
    app.add_handler(CommandHandler("clear_registry", cmd_clear_registry))
    app.add_handler(CommandHandler("test_uid", cmd_test_uid))
    app.add_handler(CommandHandler("scan_now", cmd_scan_now))
    app.add_handler(CommandHandler("scan_browser", cmd_scan_browser))
    app.add_handler(CommandHandler("login_sites", cmd_login_sites))
    app.add_handler(CommandHandler("otp", cmd_otp))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    logger.info(
        "job_filter_bot_started email_enabled=%s imap_host=%s mailbox=%s allowed_senders=%s allowed_users=%s "
        "check=%smin vacancy_once_per_day=%s auto_poll=%s cv_enabled=%s cv_model=%s",
        EMAIL_ENABLED,
        EMAIL_IMAP_HOST or "-",
        EMAIL_MAILBOX,
        len(SENDER_LIST),
        len(ALLOWED_USER_IDS),
        CHECK_INTERVAL_MIN,
        JOB_FILTER_VACANCY_BATCH_ONCE_PER_DAY,
        AUTO_POLL_MODE,
        CV_ENABLED,
        CV_MODEL or LLM_MODEL,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
