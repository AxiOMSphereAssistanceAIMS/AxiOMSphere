"""
logi_confirmation_flow.py

Two-step confirmation flow for protected allowlisted actions in Logi Telegram.

Phase 1 — healthcheck_service (read-only).

Flow:
  Step 1: User sends intent → REQUIRES_CONFIRMATION + ACTION_ID
  Step 2: User sends "CONFIRM <ACTION_ID>" → execute + return result

Constraints:
  - Only known action types allowed (ALLOWLISTED_ACTION_TYPES).
  - Only known service aliases allowed (SERVICE_ALIASES).
  - Pending confirmation expires after 10 minutes.
  - No shell=True. No user-controlled args.
  - healthcheck_service uses hardcoded subprocess invocation only.
  - Dangerous words/metacharacters blocked at intent parse time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PENDING_DIR = _ROOT / "aims_workspace" / "logi_confirmations" / "pending"
_COMPLETED_DIR = _ROOT / "aims_workspace" / "logi_confirmations" / "completed"

_CONFIRMATION_TTL_SECONDS = 600  # 10 minutes

# ─── Allowlists ──────────────────────────────────────────────────────────────

ALLOWLISTED_ACTION_TYPES = {"healthcheck_service"}

SERVICE_ALIASES: dict[str, str] = {
    "logi-bot":         "axiomsphere-logi-bot",
    "logi":             "axiomsphere-logi-bot",
    "logi-bridge":      "axiomsphere-logi-cc-bridge",
    "slot32-proxy":     "axiomsphere-logi-cc-slot32-proxy",
}

# ─── Blocklist ───────────────────────────────────────────────────────────────

_BLOCKED_CHARS_RE = re.compile(r"[;&|`$<>\r\n\\]")
_BLOCKED_WORDS_RE = re.compile(
    r"\b(?:rm|sudo|curl|wget|chmod|chown|dd|mkfs|systemctl|aws"
    r"|docker\s+restart|docker\s+exec)\b",
    re.IGNORECASE,
)

# ─── Intent patterns ─────────────────────────────────────────────────────────

# Matches healthcheck intents with a service alias at the end.
# Group 1 = service alias/name
_HEALTHCHECK_RE = re.compile(
    r"""(?:
        проверь\s+(?:здоровье|статус|health)
      | healthcheck
      | check\s+health
      | check\s+status
      | health\s+check
    )
    \s+
    ([a-zA-Z0-9\-_]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# CONFIRM flow — "CONFIRM <action_id>"
_CONFIRM_RE = re.compile(r"^\s*CONFIRM\s+([a-f0-9]{8,})\s*$", re.IGNORECASE)

# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class PendingConfirmation:
    action_id: str
    action_type: str
    service: str             # resolved container name
    created_at: str          # ISO UTC
    expires_at: str          # ISO UTC
    requested_by: str
    original_message: str

    def is_expired(self) -> bool:
        exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > exp

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PendingConfirmation":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _action_id(action_type: str, service: str, created_at: str) -> str:
    raw = f"{action_type}:{service}:{created_at}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _pending_path(action_id: str) -> Path:
    return _PENDING_DIR / f"{action_id}.json"


def _completed_path(action_id: str) -> Path:
    return _COMPLETED_DIR / f"{action_id}.json"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ─── Input validation ─────────────────────────────────────────────────────────

def _validate_message(text: str) -> tuple[bool, str]:
    if _BLOCKED_CHARS_RE.search(text):
        m = _BLOCKED_CHARS_RE.search(text)
        return False, f"blocked character in message: {m.group(0)!r}"
    if _BLOCKED_WORDS_RE.search(text):
        m = _BLOCKED_WORDS_RE.search(text)
        return False, f"blocked word in message: {m.group(0)!r}"
    return True, ""


def _resolve_service(raw_name: str) -> tuple[str | None, str]:
    """Resolve a raw service name/alias to a canonical container name."""
    name = raw_name.strip().lower()
    resolved = SERVICE_ALIASES.get(name)
    if not resolved:
        # Try case-insensitive match against values
        for alias, container in SERVICE_ALIASES.items():
            if alias.lower() == name or container.lower() == name:
                return container, ""
        return None, f"unknown service alias: {raw_name!r}. Allowed: {sorted(SERVICE_ALIASES)}"
    return resolved, ""


# ─── Healthcheck execution ────────────────────────────────────────────────────

def _run_healthcheck(container_name: str) -> dict:
    """
    Check container health using hardcoded docker inspect invocation.
    No shell=True. container_name is resolved from allowlist — never user-controlled.
    """
    # Verify the container name is in our allowlist values (double-check)
    allowed_containers = set(SERVICE_ALIASES.values())
    if container_name not in allowed_containers:
        return {
            "status": "FAILED",
            "error": f"container {container_name!r} not in allowed set",
            "health": "unknown",
        }

    try:
        # Hardcoded command — no shell=True, no user-controlled args
        result = subprocess.run(
            ["docker", "inspect", container_name, "--format", "{{.State.Running}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "No such object" in stderr or "No such container" in stderr:
                return {"status": "FAILED", "health": "not_found", "detail": stderr}
            return {"status": "FAILED", "health": "inspect_error", "detail": stderr}

        running = result.stdout.strip().lower()
        if running == "true":
            return {"status": "PASSED", "health": "running", "container": container_name}
        return {"status": "FAILED", "health": "not_running", "container": container_name}

    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "health": "timeout", "detail": "docker inspect timed out"}
    except FileNotFoundError:
        return {"status": "FAILED", "health": "docker_not_found",
                "detail": "docker CLI not available"}
    except Exception as exc:
        return {"status": "FAILED", "health": "error", "detail": str(exc)}


# ─── Public API ──────────────────────────────────────────────────────────────

def parse_healthcheck_intent(text: str) -> dict | None:
    """
    Return parsed intent dict if text is a healthcheck request, else None.
    Result includes: action_type, raw_service, validation status.
    """
    ok, reason = _validate_message(text)
    if not ok:
        return {"blocked": True, "reason": reason}

    m = _HEALTHCHECK_RE.search(text or "")
    if not m:
        return None

    return {"action_type": "healthcheck_service", "raw_service": m.group(1)}


def parse_confirm_intent(text: str) -> str | None:
    """Return action_id if text is a CONFIRM <id> message, else None."""
    m = _CONFIRM_RE.match(text or "")
    return m.group(1).lower() if m else None


def request_healthcheck(raw_service: str, requested_by: str, original_message: str) -> dict:
    """
    Step 1: Create a pending confirmation for a healthcheck request.
    Returns response dict suitable for Telegram formatting.
    """
    container, err = _resolve_service(raw_service)
    if not container:
        return {
            "status": "BLOCKED",
            "action_type": "healthcheck_service",
            "error_class": "UNKNOWN_SERVICE",
            "detail": err,
        }

    now = _now_utc()
    expires = (datetime.now(timezone.utc) + timedelta(seconds=_CONFIRMATION_TTL_SECONDS)).isoformat()
    action_id = _action_id("healthcheck_service", container, now)

    pending = PendingConfirmation(
        action_id=action_id,
        action_type="healthcheck_service",
        service=container,
        created_at=now,
        expires_at=expires,
        requested_by=requested_by,
        original_message=original_message,
    )
    _write_json(_pending_path(action_id), pending.to_dict())

    return {
        "status": "REQUIRES_CONFIRMATION",
        "action_type": "healthcheck_service",
        "service": container,
        "action_id": action_id,
        "expires_at": expires,
        "reply_with": f"CONFIRM {action_id}",
    }


def confirm_action(action_id: str) -> dict:
    """
    Step 2: Execute a confirmed pending action.
    Validates pending state, runs the action, writes completed record.
    """
    # Check completed (already done)
    if _completed_path(action_id).exists():
        return {
            "status": "FAILED",
            "error_class": "ALREADY_COMPLETED",
            "action_id": action_id,
        }

    # Load pending
    data = _read_json(_pending_path(action_id))
    if data is None:
        return {
            "status": "FAILED",
            "error_class": "UNKNOWN_CONFIRMATION",
            "action_id": action_id,
        }

    pending = PendingConfirmation.from_dict(data)

    # Check expiry
    if pending.is_expired():
        return {
            "status": "FAILED",
            "error_class": "EXPIRED_CONFIRMATION",
            "action_id": action_id,
            "expired_at": pending.expires_at,
        }

    # Check action type allowlist
    if pending.action_type not in ALLOWLISTED_ACTION_TYPES:
        return {
            "status": "FAILED",
            "error_class": "ACTION_TYPE_NOT_ALLOWED",
            "action_id": action_id,
            "action_type": pending.action_type,
        }

    # Execute
    if pending.action_type == "healthcheck_service":
        result = _run_healthcheck(pending.service)
    else:
        result = {"status": "FAILED", "error": "unhandled action type"}

    completed = {
        "action_id": action_id,
        "action_type": pending.action_type,
        "service": pending.service,
        "executed_at": _now_utc(),
        "result": result,
    }
    _write_json(_completed_path(action_id), completed)
    # Remove from pending
    _pending_path(action_id).unlink(missing_ok=True)

    return {
        "status": result.get("status", "FAILED"),
        "action_type": pending.action_type,
        "service": pending.service,
        "action_id": action_id,
        "health": result.get("health"),
        "detail": result.get("detail"),
    }


def format_confirmation_response(resp: dict) -> str:
    """Format a confirmation flow response as a Telegram-safe string."""
    status = resp.get("status", "UNKNOWN")
    lines = [f"STATUS: {status}"]

    action_type = resp.get("action_type")
    if action_type:
        lines.append(f"ACTION_TYPE: {action_type}")

    service = resp.get("service")
    if service:
        lines.append(f"SERVICE: {service}")

    action_id = resp.get("action_id")
    if action_id:
        lines.append(f"ACTION_ID: {action_id}")

    health = resp.get("health")
    if health:
        lines.append(f"HEALTH: {health}")

    reply_with = resp.get("reply_with")
    if reply_with:
        lines.append(f"REPLY_WITH: {reply_with}")

    error_class = resp.get("error_class")
    if error_class:
        lines.append(f"ERROR_CLASS: {error_class}")

    detail = resp.get("detail")
    if detail and status == "FAILED":
        lines.append(f"DETAIL: {str(detail)[:200]}")

    expired_at = resp.get("expired_at")
    if expired_at:
        lines.append(f"EXPIRED_AT: {expired_at}")

    return "\n".join(lines)
