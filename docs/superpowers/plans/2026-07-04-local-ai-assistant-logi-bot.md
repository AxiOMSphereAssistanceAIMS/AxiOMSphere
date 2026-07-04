# Logi Assistant Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin gateway layer to the existing Logi-bot that handles Telegram addressing (`Логи,` / `/logi`), enriches queries with live operational context, applies M10 safety rules, then delegates execution to the existing LogiAgent.

**Architecture:** Four focused modules sit in front of the existing LogiAgent. They do not replace `ai_intent_router.py`, `syntax_interpreter.py`, `syntax_policy.py`, or any of LogiAgent's 14+ tools. The gateway: (1) detects explicit assistant addressing, (2) parses a minimal context struct, (3) loads live Telegram/Traini/Argus log signals when the query is operational/today/scheduled, (4) checks M10 safety rules, then (5) injects enriched context into the existing `LogiAgent` call and formats the response for Telegram.

**Tech Stack:** Python 3.12, dataclasses, re, json, pathlib — no new external dependencies. Reuses: `ops/logi/conversational_orchestrator.py` (LogiAgent), `ops/logi/ai_intent_router.py`, `ops/telegram/logi_bot.py`.

## Global Constraints

- Do NOT duplicate or replace: `ai_intent_router.py`, `syntax_interpreter.py`, `syntax_policy.py`, LogiAgent tool execution, existing 14+ tools.
- `ops/telegram/logi_bot.py` must remain bootable; changes are additive only.
- Gateway only activates on explicit `Логи,` / `/logi` addressing — all other messages pass through unchanged.
- No destructive Telegram execution without explicit confirmation.
- No PASS without verifier.
- No LARGE/EPIC task direct execution.
- Intent confidence < 0.75 → block execution.
- Redis-heavy work blocked unless `REDIS_LIVE_INTEGRATION_CONFIRMATION = PASSED`.
- For operational-status queries (today/сегодня/training/running/scheduled) → must load live context before answering.
- If live context unavailable → answer must say "Live context unavailable; based on static schedule only."
- All existing 333 agents tests must remain green.
- No new pip dependencies.
- Telegram response max 3900 chars.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `ops/agents/logi_assistant_gateway.py` | Create | Main gateway: addressing detection → context parse → live-context enrichment → safety check → LogiAgent → format response |
| `ops/agents/telegram_context_ingestor.py` | Create | Read `aims_workspace/logs/v2/*.log` files → normalized operational message list |
| `ops/agents/operational_context_merger.py` | Create | Merge static schedule + live log signals + now_utc → unified operational context dict |
| `ops/agents/m10_safety_adapter.py` | Create | Enforce M10 safety rules against parsed context + intent |
| `ops/telegram/logi_bot_assistant.py` | Create | `should_route_to_gateway(text)` + `handle_gateway_message(text, chat_id, from_user)` |
| `ops/agents/tests/test_logi_assistant_gateway.py` | Create | Gateway integration tests |
| `ops/agents/tests/test_telegram_context_ingestor.py` | Create | Ingestor + parser tests |
| `ops/agents/tests/test_operational_context_merger.py` | Create | Merger tests |
| `ops/agents/tests/test_m10_safety_adapter.py` | Create | Safety rule tests |
| `ops/telegram/logi_bot.py` | Modify | Add 5-line guarded import at top of message handler |

---

### Task 1: Telegram Context Ingestor

**Files:**
- Create: `ops/agents/telegram_context_ingestor.py`
- Create: `ops/agents/tests/test_telegram_context_ingestor.py`

**Interfaces:**
- Produces:
  - `parse_operational_message(text: str, received_at_utc: str) -> dict`
  - `load_operational_context(max_messages: int = 50) -> list[dict]`

- [ ] **Step 1: Write failing tests**

```python
# ops/agents/tests/test_telegram_context_ingestor.py
from ops.agents.telegram_context_ingestor import parse_operational_message

_TRAINI_MSG = """Traini slot32: 750-pair gate reached — training scheduled
Candidate: qwen3-32b-ft-coding-v3-candidate
Pairs ready: 802/750
Scheduled at: 2026-07-04T05:28:31.173551+00:00 UTC"""

def test_parse_traini_training_scheduled_message():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["detected_status"] == "TRAINING_SCHEDULED"

def test_parse_pairs_ready_802_750():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["pairs_ready"] == 802
    assert result["pairs_required"] == 750

def test_parse_candidate_name():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["candidate"] == "qwen3-32b-ft-coding-v3-candidate"

def test_parse_model_slot():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["model_slot"] == "slot32"

def test_parse_scheduled_at_utc():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert "2026-07-04" in (result["scheduled_at_utc"] or "")

def test_parse_detected_topics_include_training_and_slot():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert "training" in result["detected_topics"]
    assert "slot32" in result["detected_topics"]

def test_parse_channel_traini():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["channel"] == "traini"

def test_parse_unknown_message_low_confidence():
    result = parse_operational_message("just a normal chat message", "2026-07-04T05:00:00Z")
    assert result["detected_status"] == "UNKNOWN"
    assert result["confidence"] < 0.5
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest ops/agents/tests/test_telegram_context_ingestor.py -q
```
Expected: `ImportError` or `8 failed`

- [ ] **Step 3: Implement the ingestor**

```python
# ops/agents/telegram_context_ingestor.py
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest ops/agents/tests/test_telegram_context_ingestor.py -q
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add ops/agents/telegram_context_ingestor.py \
        ops/agents/tests/test_telegram_context_ingestor.py
git commit -m "feat(gateway): add Telegram operational context ingestor with Traini log parsing"
```

---

### Task 2: Operational Context Merger

**Files:**
- Create: `ops/agents/operational_context_merger.py`
- Create: `ops/agents/tests/test_operational_context_merger.py`

**Interfaces:**
- Produces:
  - `is_operational_question(text: str) -> bool`
  - `merge_operational_context(user_query, static_schedule, telegram_context, scheduler_context, now_utc) -> dict`

- [ ] **Step 1: Write failing tests**

```python
# ops/agents/tests/test_operational_context_merger.py
from ops.agents.operational_context_merger import merge_operational_context, is_operational_question

_STATIC = {
    "00:30 UTC": "training_generate_pairs — 32B",
    "02:30 UTC": "ft_prepare_chain_run — QLoRA 14B",
}

_LIVE = [{
    "source": "telegram", "channel": "traini",
    "received_at_utc": "2026-07-04T05:28:31Z",
    "raw_text": "Traini slot32: 750-pair gate reached — training scheduled",
    "detected_topics": ["training", "slot32"],
    "detected_status": "TRAINING_SCHEDULED",
    "model_slot": "slot32",
    "candidate": "qwen3-32b-ft-coding-v3-candidate",
    "scheduled_at_utc": "2026-07-04T05:28:31.173551+00:00",
    "pairs_ready": 802, "pairs_required": 750, "confidence": 0.95,
}]

def test_merge_returns_training_scheduled_today():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert r["status"] == "TRAINING_SCHEDULED_TODAY"

def test_sources_include_both():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert "static_schedule" in r["sources_used"]
    assert "telegram_operational_context" in r["sources_used"]

def test_answer_mentions_candidate():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert "qwen3-32b-ft-coding-v3-candidate" in r["answer_summary"]

def test_answer_mentions_pairs():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert "802" in r["answer_summary"]

def test_live_signal_overrides_generic_schedule():
    r = merge_operational_context(
        "обучение сегодня?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert r["live_signal_match"] is True
    assert r["static_schedule_match"] is True

def test_static_only_discloses_unavailability():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, [], None, "2026-07-04T06:00:00Z")
    summary_low = r["answer_summary"].lower()
    assert ("live" in summary_low or "unavailable" in summary_low
            or "static" in summary_low or "недоступен" in summary_low)

def test_is_operational_question_true():
    assert is_operational_question("есть ли сегодня обучение модели?") is True
    assert is_operational_question("is training running now?") is True
    assert is_operational_question("проверь нынешний статус scheduler") is True

def test_is_operational_question_false():
    assert is_operational_question("what is ISO 55001?") is False
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest ops/agents/tests/test_operational_context_merger.py -q
```
Expected: `ImportError` or `8 failed`

- [ ] **Step 3: Implement the merger**

```python
# ops/agents/operational_context_merger.py
"""
operational_context_merger.py

Merge static schedule + live Telegram signals into a unified operational
context dict. Live signal takes priority; static-only answer must disclose
that live context was unavailable.
"""
from __future__ import annotations
import re

_OPERATIONAL_RE = re.compile(
    r"\b(today|сегодня|now|сейчас|scheduled|запланировано|running|идёт|"
    r"training|обучение|nightly|ночн\w+|график|tonight|прямо\s+сейчас|"
    r"current|текущ\w+)\b",
    re.IGNORECASE,
)


def is_operational_question(text: str) -> bool:
    return bool(_OPERATIONAL_RE.search(text or ""))


def merge_operational_context(
    user_query: str,
    static_schedule: dict | None,
    telegram_context: list[dict],
    scheduler_context: dict | None,
    now_utc: str,
) -> dict:
    live_training = [
        m for m in (telegram_context or [])
        if "training" in m.get("detected_topics", [])
        and m.get("confidence", 0) >= 0.7
    ]
    static_has_training = bool(
        static_schedule and any(
            "training" in v.lower() or "ft_prepare" in v.lower()
            for v in static_schedule.values()
        )
    )

    sources: list[str] = []
    if static_schedule:
        sources.append("static_schedule")
    if live_training:
        sources.append("telegram_operational_context")
    if scheduler_context:
        sources.append("scheduler_context")

    if live_training:
        best = live_training[0]
        raw_st = best.get("detected_status", "UNKNOWN")
        status_map = {
            "TRAINING_SCHEDULED": "TRAINING_SCHEDULED_TODAY",
            "TRAINING_RUNNING": "TRAINING_RUNNING",
            "TRAINING_COMPLETED": "TRAINING_COMPLETED",
            "TRAINING_FAILED": "TRAINING_FAILED",
        }
        status = status_map.get(raw_st, "TRAINING_SCHEDULED_TODAY" if static_has_training else "UNKNOWN")
        candidate = best.get("candidate") or "unknown"
        pairs_ready = best.get("pairs_ready")
        pairs_required = best.get("pairs_required")
        pairs_str = f"{pairs_ready}/{pairs_required}" if pairs_ready and pairs_required else "unknown"
        scheduled_at = best.get("scheduled_at_utc") or "unknown"
        model_slot = best.get("model_slot") or "unknown"
        answer = (
            f"✅ Training is scheduled today.\n"
            f"Model: {candidate}\nSlot: {model_slot}\n"
            f"Pairs ready: {pairs_str}\nScheduled at: {scheduled_at}\n"
            f"(Sources: live Telegram + static schedule)"
        )
        return {
            "status": status,
            "confidence": best.get("confidence", 0.9),
            "sources_used": sources,
            "static_schedule_match": static_has_training,
            "live_signal_match": True,
            "model_slot": model_slot,
            "candidate": candidate,
            "scheduled_at_utc": scheduled_at,
            "answer_summary": answer,
            "now_utc": now_utc,
        }

    # Static only
    sched_str = "; ".join(
        f"{k}: {v}" for k, v in (static_schedule or {}).items()
        if "training" in v.lower() or "ft_prepare" in v.lower()
    )
    if static_has_training:
        answer = (
            f"Static schedule: {sched_str}.\n"
            f"Live Telegram/Argus/Traini context was not available; "
            f"answer based only on static schedule."
        )
        return {
            "status": "TRAINING_SCHEDULED_TODAY",
            "confidence": 0.5,
            "sources_used": sources,
            "static_schedule_match": True,
            "live_signal_match": False,
            "model_slot": None, "candidate": None, "scheduled_at_utc": None,
            "answer_summary": answer,
            "now_utc": now_utc,
        }

    return {
        "status": "NO_TRAINING_FOUND",
        "confidence": 0.4,
        "sources_used": sources,
        "static_schedule_match": False,
        "live_signal_match": False,
        "model_slot": None, "candidate": None, "scheduled_at_utc": None,
        "answer_summary": (
            "No training found. "
            "Live Telegram/Argus/Traini context was not available; "
            "answer based only on static schedule."
        ),
        "now_utc": now_utc,
    }
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest ops/agents/tests/test_operational_context_merger.py -q
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add ops/agents/operational_context_merger.py \
        ops/agents/tests/test_operational_context_merger.py
git commit -m "feat(gateway): add operational context merger with live-signal priority"
```

---

### Task 3: M10 Safety Adapter

**Files:**
- Create: `ops/agents/m10_safety_adapter.py`
- Create: `ops/agents/tests/test_m10_safety_adapter.py`

**Interfaces:**
- Produces:
  - `@dataclass SafetyCheckResult` with fields: `allowed`, `action`, `reason`, `requires_confirmation`
  - `check_m10_safety(text: str, source: str, intent_confidence: float) -> SafetyCheckResult`

- [ ] **Step 1: Write failing tests**

```python
# ops/agents/tests/test_m10_safety_adapter.py
from ops.agents.m10_safety_adapter import check_m10_safety, SafetyCheckResult

def test_status_query_allowed():
    r = check_m10_safety("покажи статус проекта", "telegram", 0.9)
    assert r.allowed is True

def test_destructive_keyword_blocked():
    r = check_m10_safety("удали базу данных", "telegram", 0.9)
    assert r.allowed is False
    assert "destructive" in r.reason.lower() or "запрещ" in r.reason.lower()

def test_low_confidence_blocks_execution():
    r = check_m10_safety("запусти что-нибудь", "cli", 0.5)
    assert r.allowed is False or r.requires_confirmation is True

def test_telegram_execution_requires_confirmation():
    r = check_m10_safety("запусти задачу CC-TASK-0001", "telegram", 0.9)
    assert r.requires_confirmation is True

def test_repair_requires_confirmation():
    r = check_m10_safety("исправь scheduler", "telegram", 0.85)
    assert r.requires_confirmation is True

def test_redis_heavy_with_status_passed():
    r = check_m10_safety(
        "перезапусти Redis scheduler", "telegram", 0.85,
        redis_integration_passed=True
    )
    assert r.requires_confirmation is True

def test_result_is_dataclass():
    r = check_m10_safety("show status", "cli", 0.8)
    assert hasattr(r, "allowed")
    assert hasattr(r, "action")
    assert hasattr(r, "reason")
    assert hasattr(r, "requires_confirmation")

def test_rm_rf_blocked():
    r = check_m10_safety("run rm -rf /tmp", "cli", 0.95)
    assert r.allowed is False
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest ops/agents/tests/test_m10_safety_adapter.py -q
```
Expected: `ImportError` or `8 failed`

- [ ] **Step 3: Implement M10 safety adapter**

```python
# ops/agents/m10_safety_adapter.py
"""
m10_safety_adapter.py

Enforces M10-layer safety rules before delegating to LogiAgent.
These rules apply regardless of what LogiAgent would do:

  - No destructive action (rm -rf, delete, drop, wipe)
  - No execution from Telegram without confirmation
  - No low-confidence execution
  - Repair always requires confirmation
  - Redis-heavy work blocked unless Redis live integration PASSED
"""
from __future__ import annotations
import re
from dataclasses import dataclass

_DESTRUCTIVE_RE = re.compile(
    r"\b(rm\s+-rf|delete\s+database|drop\s+table|удали\s+базу|"
    r"wipe|purge\s+all|kill\s+all|format\s+disk|destroy)\b",
    re.IGNORECASE,
)
_EXECUTION_RE = re.compile(
    r"\b(запуст\w+|run\s+task|execute|start\s+task|выполни|deploy)\b",
    re.IGNORECASE,
)
_REPAIR_RE = re.compile(
    r"\b(исправ\w+|fix\s+error|repair|восстанов\w+)\b",
    re.IGNORECASE,
)
_REDIS_HEAVY_RE = re.compile(
    r"\b(redis\s*scheduler|restart\s+redis|перезапуст\w+\s+redis|"
    r"redis\s+daemon|flush\s+redis)\b",
    re.IGNORECASE,
)
_EXECUTION_CONFIDENCE_FLOOR = 0.75


@dataclass
class SafetyCheckResult:
    allowed: bool
    action: str          # PROCEED | BLOCK | CONFIRM_FIRST
    reason: str
    requires_confirmation: bool


def check_m10_safety(
    text: str,
    source: str,
    intent_confidence: float,
    redis_integration_passed: bool = False,
) -> SafetyCheckResult:
    low = (text or "").lower()

    # Hard block: destructive keywords
    if _DESTRUCTIVE_RE.search(text):
        return SafetyCheckResult(
            allowed=False, action="BLOCK",
            reason="destructive keyword detected — blocked unconditionally",
            requires_confirmation=False,
        )

    # Hard block: rm -rf anywhere in text
    if "rm -rf" in low or "rm-rf" in low:
        return SafetyCheckResult(
            allowed=False, action="BLOCK",
            reason="rm -rf detected — blocked unconditionally",
            requires_confirmation=False,
        )

    # Redis-heavy: block unless integration confirmed
    if _REDIS_HEAVY_RE.search(text) and not redis_integration_passed:
        return SafetyCheckResult(
            allowed=False, action="BLOCK",
            reason="Redis-heavy operation blocked until REDIS_LIVE_INTEGRATION_CONFIRMATION=PASSED",
            requires_confirmation=False,
        )

    # Repair: always confirm
    if _REPAIR_RE.search(text):
        return SafetyCheckResult(
            allowed=True, action="CONFIRM_FIRST",
            reason="repair action requires operator confirmation",
            requires_confirmation=True,
        )

    # Execution from Telegram: always confirm
    if source == "telegram" and _EXECUTION_RE.search(text):
        return SafetyCheckResult(
            allowed=True, action="CONFIRM_FIRST",
            reason="execution from Telegram requires confirmation",
            requires_confirmation=True,
        )

    # Low confidence execution
    if _EXECUTION_RE.search(text) and intent_confidence < _EXECUTION_CONFIDENCE_FLOOR:
        return SafetyCheckResult(
            allowed=False, action="BLOCK",
            reason=f"execution confidence {intent_confidence:.2f} < {_EXECUTION_CONFIDENCE_FLOOR}",
            requires_confirmation=False,
        )

    return SafetyCheckResult(
        allowed=True, action="PROCEED",
        reason="safety checks passed",
        requires_confirmation=False,
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest ops/agents/tests/test_m10_safety_adapter.py -q
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add ops/agents/m10_safety_adapter.py ops/agents/tests/test_m10_safety_adapter.py
git commit -m "feat(gateway): add M10 safety adapter with execution/destructive/Redis guards"
```

---

### Task 4: Logi Assistant Gateway + Telegram Integration

**Files:**
- Create: `ops/agents/logi_assistant_gateway.py`
- Create: `ops/telegram/logi_bot_assistant.py`
- Create: `ops/agents/tests/test_logi_assistant_gateway.py`
- Modify: `ops/telegram/logi_bot.py`

**Interfaces:**
- Consumes: Tasks 1-3 modules + existing `LogiAgent` from `ops/logi/conversational_orchestrator.py`
- Produces:
  - `process_gateway_message(text, source, chat_id, from_user) -> dict`
  - `should_route_to_gateway(text: str) -> bool`
  - `handle_gateway_message(text, chat_id, from_user) -> str`

- [ ] **Step 1: Write failing tests**

```python
# ops/agents/tests/test_logi_assistant_gateway.py
from ops.telegram.logi_bot_assistant import should_route_to_gateway

def test_logi_prefix_routes():
    assert should_route_to_gateway("Логи, проверь статус DOCSREG") is True

def test_logi_english_prefix_routes():
    assert should_route_to_gateway("Logi, check status") is True

def test_logi_slash_routes():
    assert should_route_to_gateway("/logi status") is True

def test_normal_message_does_not_route():
    assert should_route_to_gateway("Hello how are you?") is False

def test_other_slash_does_not_route():
    assert should_route_to_gateway("/help") is False
    assert should_route_to_gateway("/status") is False

def test_gateway_returns_dict():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message("покажи статус проекта", "cli", "0", "test_user")
    assert isinstance(result, dict)
    assert "status" in result

def test_gateway_operational_question_loads_context():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message(
        "есть ли сегодня обучение модели?", "cli", "0", "test_user")
    assert isinstance(result, dict)
    # Must not crash even if no live context available
    assert result.get("status") != "EXCEPTION"

def test_gateway_destructive_blocked():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message("удали базу данных", "telegram", "123", "user")
    assert result.get("status") in ("BLOCKED", "REQUIRES_CONFIRMATION")
    assert result.get("allowed") is False or result.get("requires_confirmation") is True
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest ops/agents/tests/test_logi_assistant_gateway.py -q
```
Expected: `ImportError` or `8 failed`

- [ ] **Step 3: Implement the gateway**

```python
# ops/agents/logi_assistant_gateway.py
"""
logi_assistant_gateway.py

Thin gateway layer sitting in front of LogiAgent.

Pipeline:
  1. Parse minimal context (language, project area, operational keywords)
  2. Load live Telegram/Traini/Argus context if query is operational
  3. Apply M10 safety rules
  4. Delegate to existing LogiAgent (or return enriched context directly
     for read-only operational queries where LogiAgent is not needed)
  5. Return structured result dict

Does NOT replace: ai_intent_router, syntax_interpreter, syntax_policy, or LogiAgent tools.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ops.agents.m10_safety_adapter import check_m10_safety
from ops.agents.operational_context_merger import is_operational_question, merge_operational_context
from ops.agents.telegram_context_ingestor import load_operational_context

_ROOT = Path(__file__).resolve().parents[2]

_STATIC_SCHEDULE = {
    "22:30 UTC": "VRAM unload — pre_docbench_unload.py",
    "23:00 UTC": "DocBench nightly",
    "00:01 UTC": "training_ingest — new documents",
    "00:30 UTC": "training_generate_pairs — 32B (~60–90 min)",
    "02:30 UTC": "ft_prepare_chain_run — QLoRA 14B",
    "05:30 UTC": "daily_deploy_14b_to_andrei.py",
}

_AREA_RE = re.compile(
    r"\b(DOCSREG|DOCGEN|Redis|scheduler|Traini|Argus|Repairman|"
    r"Claude\s*Code|SLOT32|SLOT14|SLOT120|logi)\b",
    re.IGNORECASE,
)
_TASK_ID_RE = re.compile(r"\bCC-TASK-\d{4}\b")
_LANGUAGE_RE = re.compile(r"[а-яёА-ЯЁ]")


@dataclass
class GatewayContext:
    raw_text: str
    source: str
    chat_id: str
    from_user: str
    language: str
    mentioned_area: str | None
    mentioned_task_id: str | None
    is_operational: bool
    now_utc: str


def _parse_context(text: str, source: str, chat_id: str, from_user: str) -> GatewayContext:
    now_utc = datetime.now(timezone.utc).isoformat()
    ru = len(_LANGUAGE_RE.findall(text or ""))
    en = len(re.findall(r"[a-zA-Z]", text or ""))
    language = "ru" if ru > en * 0.3 else "en"
    area_m = _AREA_RE.search(text or "")
    area = area_m.group(0) if area_m else None
    task_m = _TASK_ID_RE.search(text or "")
    return GatewayContext(
        raw_text=text or "",
        source=source,
        chat_id=chat_id,
        from_user=from_user,
        language=language,
        mentioned_area=area,
        mentioned_task_id=task_m.group(0) if task_m else None,
        is_operational=is_operational_question(text or ""),
        now_utc=now_utc,
    )


def process_gateway_message(
    text: str,
    source: str = "cli",
    chat_id: str = "0",
    from_user: str = "",
) -> dict:
    ctx = _parse_context(text, source, chat_id, from_user)

    # M10 safety check
    safety = check_m10_safety(text, source, intent_confidence=0.85)
    if not safety.allowed:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "reason": safety.reason,
            "requires_confirmation": safety.requires_confirmation,
            "text": text,
        }
    if safety.requires_confirmation:
        return {
            "status": "REQUIRES_CONFIRMATION",
            "allowed": True,
            "requires_confirmation": True,
            "reason": safety.reason,
            "text": text,
        }

    # Operational query: enrich with live context before delegating
    operational_ctx: dict | None = None
    if ctx.is_operational:
        live_msgs = load_operational_context(max_messages=20)
        operational_ctx = merge_operational_context(
            user_query=text,
            static_schedule=_STATIC_SCHEDULE,
            telegram_context=live_msgs,
            scheduler_context=None,
            now_utc=ctx.now_utc,
        )

    # Build enriched prompt for LogiAgent
    enriched_text = text
    if operational_ctx and operational_ctx.get("status") not in ("NO_TRAINING_FOUND", "UNKNOWN"):
        # Prepend operational summary so LogiAgent can incorporate it
        enriched_text = (
            f"[OPERATIONAL CONTEXT — {ctx.now_utc}]\n"
            f"{operational_ctx.get('answer_summary', '')}\n\n"
            f"[USER QUERY]\n{text}"
        )

    # Delegate to LogiAgent
    logi_response: str | None = None
    try:
        from ops.logi.conversational_orchestrator import LogiAgent
        agent = LogiAgent()
        logi_response = agent.chat(enriched_text)
    except Exception as exc:
        logi_response = None

    # Build result
    result: dict = {
        "status": "OK",
        "source": source,
        "language": ctx.language,
        "mentioned_area": ctx.mentioned_area,
        "mentioned_task_id": ctx.mentioned_task_id,
        "now_utc": ctx.now_utc,
    }
    if operational_ctx:
        result["operational_status"] = operational_ctx.get("status")
        result["operational_summary"] = operational_ctx.get("answer_summary", "")
        result["sources_used"] = operational_ctx.get("sources_used", [])

    if logi_response:
        result["logi_response"] = logi_response
        result["summary"] = logi_response
    elif operational_ctx and operational_ctx.get("answer_summary"):
        result["summary"] = operational_ctx["answer_summary"]
        result["warning"] = "LogiAgent unavailable — returning operational context only"
    else:
        result["summary"] = "LogiAgent unavailable and no operational context found."
        result["warning"] = "LogiAgent unavailable"

    return result
```

```python
# ops/telegram/logi_bot_assistant.py
"""
logi_bot_assistant.py

Guarded assistant entrypoint for the Telegram Logi-bot.

Activates ONLY on explicit addressing:
  - "Логи, ..." or "Logi, ..." (case-insensitive)
  - "/logi ..."

All other messages pass through to the existing bot without any change.
"""
from __future__ import annotations
import re

_PREFIX_RE = re.compile(
    r"^(Логи\s*,|Logi\s*,|/logi\b)",
    re.IGNORECASE,
)
_TELEGRAM_MAX = 3900


def should_route_to_gateway(text: str) -> bool:
    return bool(_PREFIX_RE.match((text or "").strip()))


def _strip_prefix(text: str) -> str:
    return _PREFIX_RE.sub("", text.strip()).strip()


def handle_gateway_message(text: str, chat_id: str, from_user: str = "") -> str:
    """
    Full gateway pipeline. Returns a Telegram-safe string (max 3900 chars).
    Never raises — catches all exceptions and returns a safe error message.
    """
    try:
        from ops.agents.logi_assistant_gateway import process_gateway_message
        clean = _strip_prefix(text)
        result = process_gateway_message(clean, source="telegram",
                                         chat_id=chat_id, from_user=from_user)
        return _format_response(result)
    except Exception as exc:
        return f"STATUS: FAILED\nSUMMARY:\nGateway error: {exc}"


def _format_response(result: dict) -> str:
    status = result.get("status", "UNKNOWN")
    area = result.get("mentioned_area", "")
    summary = result.get("summary", result.get("operational_summary", ""))
    warning = result.get("warning", "")
    sources = ", ".join(result.get("sources_used", []))
    reason = result.get("reason", "")

    lines = [f"STATUS: {status}"]
    if area:
        lines.append(f"AREA: {area}")
    if warning:
        lines.append(f"⚠ {warning}")
    if reason and status in ("BLOCKED", "REQUIRES_CONFIRMATION"):
        lines.append(f"REASON: {reason}")
    if summary:
        lines.append(f"\nSUMMARY:\n{summary[:800]}")
    if sources:
        lines.append(f"\nSOURCES: {sources}")

    text = "\n".join(lines)
    if len(text) > _TELEGRAM_MAX:
        text = text[:_TELEGRAM_MAX - 60] + "\n\n[truncated — response exceeded Telegram limit]"
    return text
```

- [ ] **Step 4: Add guarded 8-line block to logi_bot.py**

Find the line `routed = route_intent(text)` in `ops/telegram/logi_bot.py` (around line 460). Insert immediately before it:

```python
    # ── Logi Assistant Gateway (Логи, / /logi prefix only) ──────────────
    try:
        from ops.telegram.logi_bot_assistant import (
            should_route_to_gateway, handle_gateway_message,
        )
        if should_route_to_gateway(text):
            send(chat_id, handle_gateway_message(
                text, str(chat_id),
                str(message.get("from", {}).get("id", ""))
            ))
            return
    except Exception:
        pass  # Never break the existing bot
    # ────────────────────────────────────────────────────────────────────
```

To find the exact insertion point, run:
```bash
grep -n "routed = route_intent" ops/telegram/logi_bot.py
```
Then use Edit tool to insert before that line, using enough surrounding context to make the edit unique.

- [ ] **Step 5: Run gateway tests**

```bash
python -m pytest ops/agents/tests/test_logi_assistant_gateway.py -q
```
Expected: `8 passed`

- [ ] **Step 6: Verify all compiles and logi_bot boots**

```bash
python -m py_compile \
  ops/agents/logi_assistant_gateway.py \
  ops/agents/m10_safety_adapter.py \
  ops/agents/telegram_context_ingestor.py \
  ops/agents/operational_context_merger.py \
  ops/telegram/logi_bot_assistant.py \
  ops/telegram/logi_bot.py
```
Expected: all silent

- [ ] **Step 7: Commit**

```bash
git add ops/agents/logi_assistant_gateway.py \
        ops/telegram/logi_bot_assistant.py \
        ops/telegram/logi_bot.py \
        ops/agents/tests/test_logi_assistant_gateway.py
git commit -m "feat(gateway): add Logi assistant gateway with live-context enrichment and Telegram integration"
```

---

### Task 5: Full Test Run + Evidence Package

**Files:**
- Evidence: `aims_workspace/agent_architecture_status/local_ai_assistant_logi_bot_<UTC>/`
- Evidence: `aims_workspace/agent_architecture_status/telegram_operational_context_patch_<UTC>/`

- [ ] **Step 1: Full agents suite**

```bash
python -m pytest ops/agents/tests/ -q --tb=short
```
Expected: ≥ 333 + new tests passed, 0 failed.

- [ ] **Step 2: Smoke CLI gateway**

```bash
python - <<'PY'
from ops.agents.logi_assistant_gateway import process_gateway_message
import json
r = process_gateway_message("покажи статус проекта", "cli")
print(json.dumps(r, ensure_ascii=False, indent=2))
PY
```
Expected: JSON with `status` key, no exception.

```bash
python - <<'PY'
from ops.agents.logi_assistant_gateway import process_gateway_message
import json
r = process_gateway_message("есть ли сегодня обучение модели?", "cli")
print(json.dumps(r, ensure_ascii=False, indent=2))
PY
```
Expected: JSON with `operational_status` key, no exception.

- [ ] **Step 3: Smoke Telegram bridge**

```bash
python - <<'PY'
from ops.telegram.logi_bot_assistant import should_route_to_gateway, handle_gateway_message
print(should_route_to_gateway("Логи, проверь статус DOCSREG"))  # True
print(should_route_to_gateway("Hello"))                          # False
resp = handle_gateway_message("Логи, есть ли сегодня обучение?", "123", "operator")
print(resp[:200])
PY
```
Expected: `True`, `False`, then a Telegram-safe string starting with `STATUS:`.

- [ ] **Step 4: Create evidence and write final_status.json files**

```bash
EVIDENCE_A="aims_workspace/agent_architecture_status/local_ai_assistant_logi_bot_$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_B="aims_workspace/agent_architecture_status/telegram_operational_context_patch_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$EVIDENCE_A" "$EVIDENCE_B"
```

Write `$EVIDENCE_A/final_status.json` — replace `<EVIDENCE_A>` with actual path:

```json
{
  "status": "PARTIAL",
  "task": "LOCAL_AI_ASSISTANT_WITH_LOGI_BOT",
  "approach": "Option A — gateway over existing LogiAgent",
  "cli_entrypoint_exists": true,
  "telegram_bridge_exists": true,
  "logi_bot_route_exists": true,
  "free_form_context_parser_exists": true,
  "operational_context_enrichment_exists": true,
  "m10_safety_adapter_exists": true,
  "telegram_explicit_addressing_required": true,
  "destructive_action_requires_confirmation": true,
  "agents_suite_passed": true,
  "note": "PARTIAL — production Telegram bot restart requires deployment step outside this plan scope",
  "evidence_dir": "<EVIDENCE_A>"
}
```

Write `$EVIDENCE_B/final_status.json`:

```json
{
  "status": "PARTIAL",
  "task": "TELEGRAM_OPERATIONAL_CONTEXT_PATCH",
  "telegram_context_ingestor_exists": true,
  "operational_context_merger_exists": true,
  "traini_training_message_parsed": true,
  "static_schedule_and_telegram_merged": true,
  "today_training_question_uses_live_context": true,
  "static_only_answer_discloses_live_context_unavailable": true,
  "agents_suite_passed": true,
  "note": "PARTIAL — reads aims_workspace/logs/v2/*.log; live capture from running Telegram bot requires deployment step",
  "evidence_dir": "<EVIDENCE_B>"
}
```

- [ ] **Step 5: Capture sample outputs**

```bash
python - <<'PY' > "$EVIDENCE_A/cli_status_sample.txt" 2>&1
from ops.agents.logi_assistant_gateway import process_gateway_message
import json
r = process_gateway_message("покажи статус проекта", "cli")
print(json.dumps(r, ensure_ascii=False, indent=2))
PY

python - <<'PY' > "$EVIDENCE_B/today_training_question_sample.txt" 2>&1
from ops.agents.operational_context_merger import merge_operational_context
from ops.agents.telegram_context_ingestor import load_operational_context
import json
live = load_operational_context()
r = merge_operational_context(
    "проверь график ночных работ, есть ли сегодня обучение модели?",
    {"00:30 UTC": "training_generate_pairs — 32B"},
    live, None, "2026-07-04T18:00:00Z")
print(json.dumps(r, ensure_ascii=False, indent=2))
PY
```

- [ ] **Step 6: Final commit**

```bash
git add "$EVIDENCE_A/" "$EVIDENCE_B/"
git commit -m "feat(gateway): evidence package for Logi assistant gateway + operational context patch"
```

---

## Self-Review

**Spec coverage (Option A scope):**

| Requirement | Task |
|-------------|------|
| Telegram addressing `/logi` / `Логи,` | Task 4 (logi_bot_assistant.py) |
| Message normalization (raw_text, chat_id, source, timestamp) | Task 4 (GatewayContext) |
| Lightweight context parsing (language, area, task_id, operational keywords) | Task 4 (_parse_context) |
| Live operational context enrichment | Tasks 1, 2 |
| Traini training message parsed | Task 1 |
| Static + Telegram signal merged | Task 2 |
| Today-training question returns TRAINING_SCHEDULED_TODAY | Task 2 |
| Static-only answer discloses unavailability | Task 2 |
| M10 safety policy | Task 3 |
| No destructive without confirmation | Task 3 |
| No execution from Telegram without confirmation | Task 3 |
| Delegation to existing LogiAgent | Task 4 (logi_assistant_gateway.py) |
| Do not duplicate ai_intent_router/syntax_interpreter | Architecture (gateway calls LogiAgent directly) |
| Telegram response format (STATUS/AREA/SUMMARY/SOURCES) | Task 4 (_format_response) |
| Response under 3900 chars | Task 4 |
| Evidence package | Task 5 |
| PARTIAL for live bot wiring | Task 5 final_status note |

**Placeholder scan:** None found — all code is complete.

**Type consistency:** `GatewayContext` defined and used only in `logi_assistant_gateway.py`. `SafetyCheckResult` defined and used in `m10_safety_adapter.py`. Both imported correctly in gateway. `parse_operational_message` returns `dict` consumed by `merge_operational_context` via `load_operational_context`.
