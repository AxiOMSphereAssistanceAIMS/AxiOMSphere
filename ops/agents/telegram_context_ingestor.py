"""
telegram_context_ingestor.py

Read operational log files and normalize messages into structured dicts.

Primary sources (checked in order):
  1. aims_workspace/logs/v2/traini_agent.log
  2. aims_workspace/logs/v2/argus_agent.log
  3. aims_workspace/logs/v2/logi_bot.log
  4. aims_workspace/operational_context/telegram_operational_messages.jsonl

Returns empty list — never raises — if logs are absent or unreadable.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG_PATHS = [
    _ROOT / "aims_workspace" / "logs" / "v2" / "traini_agent.log",
    _ROOT / "aims_workspace" / "logs" / "v2" / "argus_agent.log",
    _ROOT / "aims_workspace" / "logs" / "v2" / "logi_bot.log",
    _ROOT / "aims_workspace" / "operational_context" / "telegram_operational_messages.jsonl",
]

_PAIRS_RE = re.compile(r"Pairs\s+ready:\s*(\d+)/(\d+)", re.IGNORECASE)
_CANDIDATE_RE = re.compile(r"Candidate:\s*([\w\-\.]+)", re.IGNORECASE)
_SLOT_RE = re.compile(r"\bslot\s*(\d+)\b", re.IGNORECASE)
_SCHEDULED_AT_RE = re.compile(r"Scheduled\s+at:\s*([\d\-T:+.]+(?:\s*UTC|Z)?)", re.IGNORECASE)
_CHANNEL_KEYWORDS = {
    "traini": re.compile(r"\btraini\b", re.IGNORECASE),
    "argus": re.compile(r"\bargus\b", re.IGNORECASE),
    "logi": re.compile(r"\blogi\b", re.IGNORECASE),
}
_STATUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("TRAINING_SCHEDULED", re.compile(
        r"training\s+scheduled|gate\s+reached.*training|обучение\s+запланировано", re.IGNORECASE)),
    ("TRAINING_RUNNING", re.compile(
        r"training\s+(started|running|in\s+progress)|обучение\s+(запущено|идёт)", re.IGNORECASE)),
    ("TRAINING_COMPLETED", re.compile(
        r"training\s+completed|обучение\s+завершено", re.IGNORECASE)),
    ("TRAINING_FAILED", re.compile(
        r"training\s+failed|обучение\s+(провалилось|ошибка)", re.IGNORECASE)),
    ("HEALTH_OK", re.compile(r"health_score=100|all\s+systems\s+ok", re.IGNORECASE)),
    ("HEALTH_DEGRADED", re.compile(
        r"health_score=[0-9]{1,2}\b|degraded|недоступен", re.IGNORECASE)),
]


def parse_operational_message(text: str, received_at_utc: str) -> dict:
    if not text or not text.strip():
        return _empty(received_at_utc)

    channel = "unknown"
    for ch, pat in _CHANNEL_KEYWORDS.items():
        if pat.search(text):
            channel = ch
            break

    detected_status = "UNKNOWN"
    for status_name, pat in _STATUS_PATTERNS:
        if pat.search(text):
            detected_status = status_name
            break

    topics: list[str] = []
    if re.search(r"\btraining\b|\bобучение\b", text, re.IGNORECASE):
        topics.append("training")
    slot_m = _SLOT_RE.search(text)
    if slot_m:
        topics.append(f"slot{slot_m.group(1)}")
    if re.search(r"\bscheduler\b|\bschedule\b", text, re.IGNORECASE):
        topics.append("scheduler")

    model_slot = f"slot{slot_m.group(1)}" if slot_m else None
    pairs_m = _PAIRS_RE.search(text)
    pairs_ready = int(pairs_m.group(1)) if pairs_m else None
    pairs_required = int(pairs_m.group(2)) if pairs_m else None
    cand_m = _CANDIDATE_RE.search(text)
    candidate = cand_m.group(1) if cand_m else None
    sched_m = _SCHEDULED_AT_RE.search(text)
    scheduled_at_utc = (
        sched_m.group(1).strip().replace(" UTC", "Z").replace(" ", "")
        if sched_m else None
    )

    return {
        "source": "telegram",
        "channel": channel,
        "received_at_utc": received_at_utc,
        "raw_text": text,
        "detected_topics": topics,
        "detected_status": detected_status,
        "model_slot": model_slot,
        "candidate": candidate,
        "scheduled_at_utc": scheduled_at_utc,
        "pairs_ready": pairs_ready,
        "pairs_required": pairs_required,
        "confidence": 0.9 if detected_status != "UNKNOWN" else 0.3,
    }


def ingest_log_file(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return []

    if p.suffix == ".jsonl":
        results = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    results.append(obj)
            except json.JSONDecodeError:
                pass
        return results

    _TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
    results: list[dict] = []
    current_block: list[str] = []
    current_ts = "1970-01-01T00:00:00Z"

    def _flush(block: list[str], ts: str) -> None:
        text = "\n".join(block).strip()
        if len(text) > 20:
            msg = parse_operational_message(text, ts)
            if msg["detected_status"] != "UNKNOWN":
                results.append(msg)

    for line in lines:
        if _TS_RE.match(line):
            if current_block:
                _flush(current_block, current_ts)
            parts = line.split()
            current_ts = parts[0] + "T" + (parts[1] if len(parts) > 1 else "00:00:00")
            current_block = [line]
        else:
            current_block.append(line)

    if current_block:
        _flush(current_block, current_ts)
    return results


def load_operational_context(max_messages: int = 50) -> list[dict]:
    results: list[dict] = []
    for path in _DEFAULT_LOG_PATHS:
        try:
            results.extend(ingest_log_file(path))
        except Exception:
            continue
    results.sort(key=lambda m: m.get("received_at_utc", ""), reverse=True)
    return results[:max_messages]


def _empty(ts: str) -> dict:
    return {
        "source": "telegram", "channel": "unknown", "received_at_utc": ts,
        "raw_text": "", "detected_topics": [], "detected_status": "UNKNOWN",
        "model_slot": None, "candidate": None, "scheduled_at_utc": None,
        "pairs_ready": None, "pairs_required": None, "confidence": 0.0,
    }
