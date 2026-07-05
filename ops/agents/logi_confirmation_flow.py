"""
logi_confirmation_flow.py

Two-step confirmation flow for protected allowlisted actions in Logi Telegram.

Supported action types:
  - healthcheck_service   (read-only, Phase 1)
  - read_logs_allowlisted (read-only, Phase 2)

Flow:
  Step 1: User sends intent → REQUIRES_CONFIRMATION + ACTION_ID
  Step 2: User sends "CONFIRM <ACTION_ID>" → execute + return result

Constraints:
  - Only known action types allowed (ALLOWLISTED_ACTION_TYPES).
  - Only known service aliases allowed (SERVICE_ALIASES).
  - Pending confirmation expires after 10 minutes.
  - No shell=True. No user-controlled args.
  - healthcheck_service uses self_process / HTTP / docker-inspect.
  - read_logs_allowlisted reads known local log files only — no docker CLI needed.
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

ALLOWLISTED_ACTION_TYPES = {"healthcheck_service", "read_logs_allowlisted"}

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

# Matches log-read intents. Groups: (1) optional line count, (2) service alias.
# Supports: "покажи последние 50 строк logi-bot", "show last 100 lines logi-bot",
#            "read logs logi-bot", "покажи логи logi-bot"
_READ_LOGS_RE = re.compile(
    r"""(?:
        покажи\s+(?:последние\s+)?(?:(\d+)\s+строк\w*\s+)?(?:лог\w*\s+)?
      | show\s+(?:last\s+)?(?:(\d+)\s+lines?\s+)?(?:logs?\s+)?
      | read\s+logs?\s+
    )
    ([a-zA-Z0-9\-_]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_READ_LOGS_DEFAULT_LINES = 50
_READ_LOGS_MIN_LINES = 10
_READ_LOGS_MAX_LINES = 200

# Known log file paths for each allowlisted container.
# Paths are tried in order; the first readable file is used.
# Paths are absolute inside the container (/workspace mount) and also
# accessible from the host as aims_workspace/logs/v2/<name>.
_LOG_FILE_CANDIDATES: dict[str, list[Path]] = {
    "axiomsphere-logi-bot": [
        _ROOT / "aims_workspace" / "logs" / "v2" / "logi_bot.log",
        Path("/workspace/aims_workspace/logs/v2/logi_bot.log"),
    ],
    "axiomsphere-logi-cc-bridge": [
        _ROOT / "aims_workspace" / "logs" / "v2" / "anthropic_gateway.log",
        Path("/workspace/aims_workspace/logs/v2/anthropic_gateway.log"),
    ],
    "axiomsphere-logi-cc-slot32-proxy": [
        _ROOT / "aims_workspace" / "logs" / "v2" / "anthropic_gateway.log",
        Path("/workspace/aims_workspace/logs/v2/anthropic_gateway.log"),
    ],
}

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
    params: dict = None      # type: ignore  # action-specific parameters

    def __post_init__(self):
        if self.params is None:
            self.params = {}

    def is_expired(self) -> bool:
        exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > exp

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PendingConfirmation":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: d[k] for k in known if k in d})


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

# HTTP health endpoints for services reachable from inside the container network.
# Both logi-cc-bridge and logi-cc-slot32-proxy run on the host network, so
# 127.0.0.1 works both from the host and from host-networked containers.
_HTTP_HEALTH_ENDPOINTS: dict[str, str] = {
    "axiomsphere-logi-cc-slot32-proxy": os.environ.get(
        "SLOT32_PROXY_HEALTH_URL", "http://127.0.0.1:8084/health"
    ),
    "axiomsphere-logi-cc-bridge": os.environ.get(
        "LOGI_BRIDGE_HEALTH_URL", "http://127.0.0.1:8086/health"
    ),
}


def _healthcheck_self_process() -> dict:
    """Self-process healthcheck for axiomsphere-logi-bot.

    If this code is executing, the Logi process is alive and handling the request.
    No docker CLI or socket required.
    """
    import os as _os
    return {
        "status": "PASSED",
        "health": "running",
        "method": "self_process",
        "pid": _os.getpid(),
    }


def _healthcheck_http(container_name: str) -> dict:
    """HTTP GET healthcheck for services with known health endpoints.

    No docker CLI. No shell=True. Endpoint is hardcoded from _HTTP_HEALTH_ENDPOINTS.
    """
    url = _HTTP_HEALTH_ENDPOINTS.get(container_name)
    if not url:
        return {
            "status": "FAILED",
            "health": "unknown",
            "error_class": "HEALTHCHECK_BACKEND_UNAVAILABLE",
            "detail": f"no health URL configured for {container_name}",
        }

    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return {
                    "status": "PASSED",
                    "health": "running",
                    "method": "http_health",
                    "url": url,
                }
            return {
                "status": "FAILED",
                "health": "http_error",
                "method": "http_health",
                "detail": f"HTTP {resp.status}",
            }
    except urllib.error.URLError as exc:
        return {
            "status": "FAILED",
            "health": "unknown",
            "error_class": "HEALTHCHECK_BACKEND_UNAVAILABLE",
            "method": "http_health",
            "detail": str(exc.reason),
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "health": "unknown",
            "error_class": "HEALTHCHECK_BACKEND_UNAVAILABLE",
            "method": "http_health",
            "detail": str(exc),
        }


def _healthcheck_docker(container_name: str) -> dict:
    """Docker CLI healthcheck — last-resort fallback when no other method works.

    No shell=True. container_name is resolved from allowlist only.
    """
    try:
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
            return {"status": "PASSED", "health": "running", "method": "docker_inspect",
                    "container": container_name}
        return {"status": "FAILED", "health": "not_running", "method": "docker_inspect",
                "container": container_name}

    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "health": "timeout", "detail": "docker inspect timed out"}
    except FileNotFoundError:
        return {
            "status": "FAILED",
            "health": "unknown",
            "error_class": "HEALTHCHECK_BACKEND_UNAVAILABLE",
            "detail": "docker CLI not available",
        }
    except Exception as exc:
        return {"status": "FAILED", "health": "error", "detail": str(exc)}


def _run_healthcheck(container_name: str) -> dict:
    """
    Select the best healthcheck backend for a known allowlisted container.

    Priority order (no docker CLI required for logi-bot):
      1. axiomsphere-logi-bot   → self_process (if we're running, bot is running)
      2. axiomsphere-logi-cc-slot32-proxy / logi-cc-bridge → HTTP health endpoint
      3. Other allowlisted containers → docker inspect fallback
    """
    allowed_containers = set(SERVICE_ALIASES.values())
    if container_name not in allowed_containers:
        return {
            "status": "FAILED",
            "health": "unknown",
            "error_class": "UNKNOWN_SERVICE",
            "detail": f"container {container_name!r} not in allowed set",
        }

    if container_name == "axiomsphere-logi-bot":
        return _healthcheck_self_process()

    if container_name in _HTTP_HEALTH_ENDPOINTS:
        return _healthcheck_http(container_name)

    # Last-resort: docker CLI (may not be available inside containers)
    return _healthcheck_docker(container_name)


# ─── Read-logs execution ─────────────────────────────────────────────────────

def _run_read_logs(container_name: str, lines: int) -> dict:
    """
    Read the last `lines` lines from the known local log file for `container_name`.

    No docker CLI. No shell=True. No user-controlled path components.
    Log file path is resolved from the hardcoded _LOG_FILE_CANDIDATES map only.
    """
    candidates = _LOG_FILE_CANDIDATES.get(container_name, [])
    log_path: Path | None = None
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            log_path = candidate
            break

    if log_path is None:
        return {
            "status": "FAILED",
            "health": "unknown",
            "error_class": "LOG_BACKEND_UNAVAILABLE",
            "detail": f"no readable log file found for {container_name}",
            "method": "local_file",
        }

    try:
        # Read the file and return the last `lines` lines without subprocess.
        text_content = log_path.read_text(encoding="utf-8", errors="replace")
        all_lines = text_content.splitlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return {
            "status": "PASSED",
            "log_tail": "\n".join(tail),
            "lines_returned": len(tail),
            "total_lines": len(all_lines),
            "method": "local_file",
            "log_file": str(log_path),
        }
    except PermissionError as exc:
        return {
            "status": "FAILED",
            "error_class": "LOG_BACKEND_UNAVAILABLE",
            "detail": f"permission denied: {exc}",
            "method": "local_file",
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "error_class": "LOG_BACKEND_UNAVAILABLE",
            "detail": str(exc),
            "method": "local_file",
        }


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


def parse_read_logs_intent(text: str) -> dict | None:
    """
    Return parsed intent dict if text is a read-logs request, else None.

    Returns dict with:
      action_type, raw_service, lines, lines_clamped (bool)
    Or {"blocked": True, "reason": ...} if message fails validation.
    """
    ok, reason = _validate_message(text or "")
    if not ok:
        return {"blocked": True, "reason": reason}

    m = _READ_LOGS_RE.search(text or "")
    if not m:
        return None

    # Group layout: Russian match puts count in group(1), English in group(2), service in group(3)
    count_str = m.group(1) or m.group(2) or ""
    raw_service = m.group(3)

    try:
        requested_lines = int(count_str) if count_str.strip() else _READ_LOGS_DEFAULT_LINES
    except ValueError:
        requested_lines = _READ_LOGS_DEFAULT_LINES

    clamped = False
    if requested_lines < _READ_LOGS_MIN_LINES:
        requested_lines = _READ_LOGS_MIN_LINES
        clamped = True
    elif requested_lines > _READ_LOGS_MAX_LINES:
        requested_lines = _READ_LOGS_MAX_LINES
        clamped = True

    return {
        "action_type": "read_logs_allowlisted",
        "raw_service": raw_service,
        "lines": requested_lines,
        "lines_clamped": clamped,
    }


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


def request_read_logs(
    raw_service: str,
    lines: int,
    lines_clamped: bool,
    requested_by: str,
    original_message: str,
) -> dict:
    """
    Step 1: Create a pending confirmation for a read_logs_allowlisted request.
    """
    container, err = _resolve_service(raw_service)
    if not container:
        return {
            "status": "BLOCKED",
            "action_type": "read_logs_allowlisted",
            "error_class": "UNKNOWN_SERVICE",
            "detail": err,
        }

    now = _now_utc()
    expires = (datetime.now(timezone.utc) + timedelta(seconds=_CONFIRMATION_TTL_SECONDS)).isoformat()
    action_id = _action_id("read_logs_allowlisted", container, now)

    pending = PendingConfirmation(
        action_id=action_id,
        action_type="read_logs_allowlisted",
        service=container,
        created_at=now,
        expires_at=expires,
        requested_by=requested_by,
        original_message=original_message,
        params={"lines": lines, "lines_clamped": lines_clamped},
    )
    _write_json(_pending_path(action_id), pending.to_dict())

    resp: dict = {
        "status": "REQUIRES_CONFIRMATION",
        "action_type": "read_logs_allowlisted",
        "service": container,
        "lines": lines,
        "action_id": action_id,
        "expires_at": expires,
        "reply_with": f"CONFIRM {action_id}",
    }
    if lines_clamped:
        resp["lines_clamped"] = True
    return resp


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
    elif pending.action_type == "read_logs_allowlisted":
        lines = int((pending.params or {}).get("lines", _READ_LOGS_DEFAULT_LINES))
        result = _run_read_logs(pending.service, lines)
    else:
        result = {"status": "FAILED", "error": "unhandled action type"}

    completed = {
        "action_id": action_id,
        "action_type": pending.action_type,
        "service": pending.service,
        "params": pending.params or {},
        "executed_at": _now_utc(),
        "result": result,
    }
    _write_json(_completed_path(action_id), completed)
    # Remove from pending
    _pending_path(action_id).unlink(missing_ok=True)

    resp: dict = {
        "status": result.get("status", "FAILED"),
        "action_type": pending.action_type,
        "service": pending.service,
        "action_id": action_id,
    }
    if pending.action_type == "healthcheck_service":
        resp["health"] = result.get("health")
        if result.get("detail"):
            resp["detail"] = result["detail"]
    elif pending.action_type == "read_logs_allowlisted":
        resp["lines"] = (pending.params or {}).get("lines", _READ_LOGS_DEFAULT_LINES)
        if result.get("status") == "PASSED":
            resp["log_tail"] = result.get("log_tail", "")
            resp["lines_returned"] = result.get("lines_returned")
        else:
            resp["error_class"] = result.get("error_class", "LOG_BACKEND_UNAVAILABLE")
            if result.get("detail"):
                resp["detail"] = result["detail"]
    return resp


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

    # read_logs_allowlisted fields
    line_count = resp.get("lines")
    if line_count is not None:
        lines.append(f"LINES: {line_count}")
    if resp.get("lines_clamped"):
        lines.append("LINES_CLAMPED: true")
    lines_returned = resp.get("lines_returned")
    if lines_returned is not None:
        lines.append(f"LINES_RETURNED: {lines_returned}")

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

    # Log tail — appended last to keep header fields readable
    log_tail = resp.get("log_tail")
    if log_tail and status == "PASSED":
        lines.append(f"LOG_TAIL:\n{log_tail}")

    return "\n".join(lines)
