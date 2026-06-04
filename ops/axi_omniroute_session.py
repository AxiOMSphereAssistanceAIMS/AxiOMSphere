"""
axi_omniroute_session.py
────────────────────────
OmniRoute session management for the Axi bot.
Extracted from axi_bot.py (Phase C Task 2 refactor).

Provides:
  _omniroute_base_urls, _omniroute_get_active_sessions_sync
  _omniroute_close_session_sync, _omniroute_debug_session_tables_sync
  _omniroute_preflight_free_one_slot_sync
  _track_omniroute_session, _cleanup_omniroute_sessions_from_state
  _extract_omniroute_content_from_body
  _call_doctuning_openai_omniroute_sync
  _extract_doc_context_sync
"""

from __future__ import annotations

import json
import logging
import os
import time as _time
from pathlib import Path

log = logging.getLogger("axi")

# ── Context extraction system prompt (used by _extract_doc_context_sync) ──────

_DOCFILL_CONTEXT_SYSTEM = (
    "You are a technical document classifier. Analyze the given blank form and filled example. "
    "Select standards DIRECTLY relevant to what this document IS — its type and purpose. "
    "For document templates, abstract forms, or reporting documents: prefer ISO 55001 (asset management), "
    "ISO 9001 (quality), or records/lifecycle standards. "
    "Do NOT suggest equipment inspection, hot work permit, confined space entry, or HSE procedure standards "
    "unless the document explicitly covers those operations. "
    "Respond ONLY with valid JSON — no markdown fences, no extra text:\n"
    '{"doc_type": "<type>", "equipment_type": "<equipment or process>", '
    '"industry": "<sector>", "key_terms": ["<term>", ...], "standards": ["<standard>", ...]}'
)


# ── Base URL resolution ────────────────────────────────────────────────────────

def _omniroute_base_urls() -> tuple[str, str]:
    """Return (base_without_v1, base_with_v1) for the configured OmniRoute endpoint.

    Canonical endpoint: 127.0.0.1:20129 (per AIMS project spec)
    """
    raw = (
        os.environ.get("AIMS_OMNIROUTE_BASE_URL")
        or os.environ.get("OMNIROUTE_BASE_URL")
        or os.environ.get("AIMS_OMNIROUTER_URL")
        or "http://127.0.0.1:20129/v1"
    ).rstrip("/")
    if raw.endswith("/v1"):
        return raw[:-3], raw
    return raw, raw + "/v1"


# ── Session management ─────────────────────────────────────────────────────────

def _omniroute_get_active_sessions_sync() -> list[dict]:
    """Query known OmniRoute session endpoints. Returns [] on total failure."""
    try:
        import httpx
    except ImportError:
        return []

    base_without, base_with = _omniroute_base_urls()
    auth_token = (
        os.environ.get("OMNIROUTE_API_KEY")
        or os.environ.get("AIMS_CLAUDE_PROXY_TOKEN")
        or "aims-local-repair-token"
    )
    headers = {"Authorization": f"Bearer {auth_token}"}

    candidate_urls = [
        f"{base_without}/sessions",
        f"{base_without}/api/sessions",
        f"{base_without}/v1/sessions",
        f"{base_with}/sessions",
    ]

    for url in candidate_urls:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if isinstance(data, list):
                raw_sessions = data
            elif isinstance(data, dict):
                raw_sessions = (
                    data.get("sessions")
                    or data.get("data")
                    or data.get("items")
                    or []
                )
            else:
                continue

            result = []
            for s in raw_sessions:
                if not isinstance(s, dict):
                    continue
                result.append({
                    "id": s.get("id") or s.get("session_id") or s.get("sessionId", ""),
                    "created_at": s.get("created_at") or s.get("createdAt") or s.get("created") or "",
                    "updated_at": s.get("updated_at") or s.get("updatedAt") or s.get("updated") or "",
                    "status": (s.get("status") or "active"),
                    "raw": s,
                })
            log.info("omniroute sessions: found %d via %s", len(result), url)
            return result
        except Exception:
            continue

    log.info("omniroute sessions: no sessions endpoint responded")
    return []


def _omniroute_close_session_sync(session_id: str) -> bool:
    """Try all known patterns to close one OmniRoute session. Returns True on 2xx or 404."""
    if not session_id:
        return False
    try:
        import httpx
    except ImportError:
        return False

    base_without, base_with = _omniroute_base_urls()
    auth_token = (
        os.environ.get("OMNIROUTE_API_KEY")
        or os.environ.get("AIMS_CLAUDE_PROXY_TOKEN")
        or "aims-local-repair-token"
    )
    headers = {"Authorization": f"Bearer {auth_token}"}

    candidate_actions = [
        ("DELETE", f"{base_without}/sessions/{session_id}"),
        ("POST",   f"{base_without}/sessions/{session_id}/close"),
        ("DELETE", f"{base_without}/api/sessions/{session_id}"),
        ("POST",   f"{base_without}/api/sessions/{session_id}/close"),
        ("DELETE", f"{base_with}/sessions/{session_id}"),
        ("POST",   f"{base_with}/sessions/{session_id}/close"),
    ]

    for method, url in candidate_actions:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.request(method, url, headers=headers)
            if resp.status_code in (200, 201, 202, 204, 404):
                log.info("omniroute close session: %s %s → %d", method, url, resp.status_code)
                return True
        except Exception:
            continue

    log.warning("omniroute close session: all endpoints failed for session_id=%s", session_id)
    return False


def _omniroute_debug_session_tables_sync() -> None:
    """Read-only discovery of OmniRoute SQLite session table names. Logs only, no writes."""
    db_path = Path.home() / ".omniroute" / "storage.sqlite"
    if not db_path.exists():
        log.info("omniroute db discovery: %s not found", db_path)
        return
    try:
        import sqlite3
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND lower(name) LIKE '%session%'"
            ).fetchall()
            log.info("omniroute db discovery: session tables=%s in %s",
                     [r[0] for r in rows], db_path)
    except Exception as exc:
        log.info("omniroute db discovery: could not read %s: %s", db_path, exc)


def _omniroute_preflight_free_one_slot_sync(reason: str = "") -> bool:
    """
    Pre-task preflight: if OmniRoute has >= 2 active sessions, close only the oldest one.
    Never closes the newest session. Closes at most one session per call.
    Returns True if a slot is available (or was freed).
    """
    sessions = _omniroute_get_active_sessions_sync()
    active = [
        s for s in sessions
        if (s.get("status") or "").lower() in ("active", "running", "open", "", "unknown")
    ] or sessions

    if len(active) < 2:
        return True

    def _ts(s: dict) -> str:
        return str(s.get("created_at") or s.get("updated_at") or "")

    sorted_sessions = sorted(active, key=_ts)
    oldest = sorted_sessions[0]
    newest = sorted_sessions[-1]

    log.info(
        "omniroute preflight: active_sessions=%d, closing oldest session=%s,"
        " keeping newest session=%s (reason=%s)",
        len(active),
        oldest.get("id", "?"),
        newest.get("id", "?"),
        reason,
    )
    return _omniroute_close_session_sync(oldest.get("id", ""))


def _track_omniroute_session(state: dict, session_id: str) -> None:
    """Record a session ID owned by this task into the task state dict."""
    if not session_id:
        return
    state.setdefault("omniroute_sessions", [])
    if session_id not in state["omniroute_sessions"]:
        state["omniroute_sessions"].append(session_id)


def _cleanup_omniroute_sessions_from_state(state: dict) -> None:
    """Close all OmniRoute sessions recorded by _track_omniroute_session."""
    for sid in state.get("omniroute_sessions", []):
        _omniroute_close_session_sync(sid)
    state["omniroute_sessions"] = []


# ── Response body extraction ───────────────────────────────────────────────────

def _extract_omniroute_content_from_body(body_text: str) -> str:
    """Extract assistant content string from any OmniRoute response body.

    Handles:
    - Normal OpenAI JSON: {"choices":[{"message":{"content":"..."}}]}
    - SSE/streaming: lines with "data: " prefix — concatenates delta.content chunks
    - Anthropic-like: {"content":[{"type":"text","text":"..."}]}
    - Direct fields: text, response, output
    Falls back to body_text unchanged if nothing extracts. Never raises.
    """
    if not body_text:
        return body_text

    # SSE / streaming path
    if "data:" in body_text and "chat.completion.chunk" in body_text:
        parts: list[str] = []
        for line in body_text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]" or not payload:
                continue
            try:
                chunk = json.loads(payload)
            except Exception:
                log.debug("omniroute sse chunk skip: %r", payload[:120])
                continue
            choices = chunk.get("choices")
            if not choices:
                continue
            choice = choices[0] if isinstance(choices, list) else choices
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or choice.get("message") or {}
            content = delta.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
        if parts:
            return "".join(parts)
        log.warning("omniroute sse detected but no content chunks extracted; body_start=%s", body_text[:300])

    # Normal JSON path
    try:
        data = json.loads(body_text)
    except Exception:
        return body_text

    if "choices" in data:
        choice = (data.get("choices") or [{}])[0]
        if isinstance(choice, dict):
            msg = choice.get("message") or choice.get("delta") or {}
            content = msg.get("content", "")
            if isinstance(content, str):
                return content.strip()

    if "content" in data:
        blocks = data.get("content") or []
        if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict):
            text = blocks[0].get("text", "")
            if isinstance(text, str):
                return text.strip()

    for _k in ("text", "response", "output"):
        val = data.get(_k)
        if isinstance(val, str):
            return val.strip()

    return body_text


# ── Synchronous OmniRoute chat call ───────────────────────────────────────────

def _call_doctuning_openai_omniroute_sync(
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> tuple[int, str]:
    """POST to OmniRoute /v1/chat/completions. Returns (status_code, raw_text)."""
    try:
        import httpx
    except ImportError:
        return 503, "httpx not installed"

    _, base_with = _omniroute_base_urls()
    url = base_with + "/chat/completions"

    auth_token = (
        os.environ.get("OMNIROUTE_API_KEY")
        or os.environ.get("AIMS_CLAUDE_PROXY_TOKEN")
        or "aims-local-repair-token"
    )

    log.info("doctuning omniroute chat: url=%s model=%s", url, model)

    # Preflight: free a slot if already at the 2-session limit
    _omniroute_preflight_free_one_slot_sync(reason=f"model={model}")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }

    def _do_request() -> tuple[int, str]:
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
        except Exception as net_exc:
            return 503, str(net_exc)

        status_code = resp.status_code
        body_text = resp.text

        session_id = (
            resp.headers.get("x-omniroute-session-id")
            or resp.headers.get("x-session-id")
            or ""
        )
        if session_id:
            log.info("doctuning omniroute session-id: %s", session_id)

        if status_code == 429:
            log.warning("doctuning omniroute rate limited: model=%s", model)
            return 429, body_text

        raw = _extract_omniroute_content_from_body(body_text)
        if raw is body_text and raw != body_text:
            log.warning(
                "doctuning omniroute parse fallback: status=%s model=%s body_start=%s",
                status_code, model, body_text[:500],
            )

        return status_code, raw

    status, raw = _do_request()
    if status == 429:
        if "maximum number of active sessions" in raw:
            _omniroute_preflight_free_one_slot_sync(reason="429_retry")
            _time.sleep(5)
        else:
            _time.sleep(20)
        status, raw = _do_request()
    return status, raw


def _extract_doc_context_sync(blank_text: str, filled_text: str) -> dict:
    """Classify document and extract context via OmniRoute /v1/chat/completions."""
    model = (
        os.environ.get("AIMS_DOCTUNING_EXTRACT_MODEL")
        or os.environ.get("OMNIROUTE_EXTRACT_MODEL")
        or os.environ.get("AIMS_DOCTUNING_MODEL")
        or "doc-extract-combo"
    )

    prompt = (
        f"BLANK TEMPLATE (first 2000 chars):\n{blank_text[:2000]}\n\n"
        f"FILLED EXAMPLE (first 2000 chars):\n{filled_text[:2000]}\n\n"
        "Select standards that match the TYPE of this document, not incidental keywords. "
        "Respond with JSON only."
    )

    status, raw = _call_doctuning_openai_omniroute_sync(
        model=model,
        system=_DOCFILL_CONTEXT_SYSTEM,
        prompt=prompt,
        max_tokens=512,
        temperature=0.0,
        timeout=120.0,
    )
    log.info("doctuning context extract: model=%s status=%d", model, status)

    if status == 429:
        if "maximum number of active sessions" in raw:
            return {"error": "omniroute_session_limit", "raw": raw[:500]}
        return {"error": "omniroute_rate_limited", "raw": raw[:500]}

    if status != 200:
        return {"error": f"omniroute_status_{status}", "raw": raw[:500]}

    # SSE guard — extract content if helper was bypassed
    if raw.lstrip().startswith("data:") and "chat.completion.chunk" in raw:
        raw = _extract_omniroute_content_from_body(raw)

    # strip markdown fences and leading "json" token
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.lstrip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    cleaned = cleaned.strip("`").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except Exception:
        return {"error": "json_parse_failed", "raw": cleaned[:500]}
