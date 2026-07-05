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

ALLOWLISTED_ACTION_TYPES = {
    "healthcheck_service",
    "read_logs_allowlisted",
    "diagnose_service_allowlisted",
    "create_auditor_request",
    "create_skill_request",
    "register_learning_event",
    "queue_task_allowlisted",
}

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

# Matches diagnose intents. Group 1 = service alias.
# Supports: "диагностируй logi-bot", "диагностика logi-bot",
#           "Diagnose logi-bot", "Run diagnostics logi-bot"
_DIAGNOSE_RE = re.compile(
    r"""(?:
        диагностируй\w*
      | диагностик\w+
      | diagnose
      | run\s+diagnostics?
    )
    \s+
    ([a-zA-Z0-9\-_]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Log patterns that indicate problems — compiled once at module load.
_ERROR_PATTERNS = re.compile(
    r"ERROR|Traceback|Exception|failed|unavailable|timeout"
    r"|connection\s+refused|cannot\s+import|ModuleNotFoundError|AttributeError",
    re.IGNORECASE,
)

_DIAGNOSE_SCAN_LINES = 50  # default lines to scan for diagnose

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


# ─── Diagnose execution ──────────────────────────────────────────────────────

def _run_diagnose(container_name: str) -> dict:
    """
    Read-only diagnostic for an allowlisted container:
      1. Run healthcheck (self_process / HTTP / docker fallback).
      2. Read the last _DIAGNOSE_SCAN_LINES lines of the service log.
      3. Scan for error patterns and summarise findings.

    No docker CLI required for logi-bot. No shell=True.
    """
    # Step 1: healthcheck
    health_result = _run_healthcheck(container_name)

    # Step 2: read logs
    log_result = _run_read_logs(container_name, _DIAGNOSE_SCAN_LINES)
    log_available = log_result.get("status") == "PASSED"
    log_text = log_result.get("log_tail", "") if log_available else ""
    log_lines = log_text.splitlines() if log_text else []

    # Step 3: scan for error patterns
    findings: list[str] = []
    for i, line in enumerate(log_lines):
        if _ERROR_PATTERNS.search(line):
            # Truncate long lines to keep output Telegram-safe
            snippet = line.strip()[:120]
            findings.append(f"line {len(log_lines) - len(log_lines) + i + 1}: {snippet}")
        if len(findings) >= 5:
            break

    errors_found = len(findings)
    no_errors = errors_found == 0

    # Determine overall status
    health_ok = health_result.get("status") == "PASSED"
    if health_ok and no_errors:
        status = "PASSED"
    else:
        status = "DEGRADED"

    result: dict = {
        "status": status,
        "health": health_result.get("health", "unknown"),
        "health_method": health_result.get("method"),
        "log_lines_scanned": len(log_lines),
        "errors_found": errors_found,
        "top_findings": findings if findings else ["No critical patterns found in last 50 lines."],
        "log_available": log_available,
    }

    if no_errors and health_ok:
        result["recommended_next_action"] = "No action required."
    else:
        parts = []
        if not health_ok:
            parts.append(f"healthcheck failed: {health_result.get('health', 'unknown')}")
        if errors_found > 0:
            parts.append(f"{errors_found} error pattern(s) found — run read_logs_allowlisted for full view")
        result["recommended_next_action"] = "; ".join(parts) if parts else "Inspect service logs."

    return result


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


def parse_diagnose_intent(text: str) -> dict | None:
    """
    Return parsed intent dict if text is a diagnose request, else None.
    Result: {action_type, raw_service} or {"blocked": True, "reason": ...}.
    """
    ok, reason = _validate_message(text or "")
    if not ok:
        return {"blocked": True, "reason": reason}

    m = _DIAGNOSE_RE.search(text or "")
    if not m:
        return None

    return {"action_type": "diagnose_service_allowlisted", "raw_service": m.group(1)}


def request_diagnose(raw_service: str, requested_by: str, original_message: str) -> dict:
    """
    Step 1: Create a pending confirmation for a diagnose_service_allowlisted request.
    """
    container, err = _resolve_service(raw_service)
    if not container:
        return {
            "status": "BLOCKED",
            "action_type": "diagnose_service_allowlisted",
            "error_class": "UNKNOWN_SERVICE",
            "detail": err,
        }

    now = _now_utc()
    expires = (datetime.now(timezone.utc) + timedelta(seconds=_CONFIRMATION_TTL_SECONDS)).isoformat()
    action_id = _action_id("diagnose_service_allowlisted", container, now)

    pending = PendingConfirmation(
        action_id=action_id,
        action_type="diagnose_service_allowlisted",
        service=container,
        created_at=now,
        expires_at=expires,
        requested_by=requested_by,
        original_message=original_message,
        params={"lines": _DIAGNOSE_SCAN_LINES},
    )
    _write_json(_pending_path(action_id), pending.to_dict())

    return {
        "status": "REQUIRES_CONFIRMATION",
        "action_type": "diagnose_service_allowlisted",
        "service": container,
        "lines": _DIAGNOSE_SCAN_LINES,
        "action_id": action_id,
        "expires_at": expires,
        "reply_with": f"CONFIRM {action_id}",
    }


def request_write_action(
    action_type: str,
    params: dict,
    requested_by: str,
    original_message: str,
    service: str = "",
) -> dict:
    """
    Generic step-1 for write actions that need confirmation:
    create_auditor_request, create_skill_request, register_learning_event, queue_task_allowlisted.
    """
    now = _now_utc()
    expires = (datetime.now(timezone.utc) + timedelta(seconds=_CONFIRMATION_TTL_SECONDS)).isoformat()
    action_id = _action_id(action_type, params.get("title", "write"), now)

    pending = PendingConfirmation(
        action_id=action_id,
        action_type=action_type,
        service=service or action_type,
        created_at=now,
        expires_at=expires,
        requested_by=requested_by,
        original_message=original_message,
        params=params,
    )
    _write_json(_pending_path(action_id), pending.to_dict())

    return {
        "status": "REQUIRES_CONFIRMATION",
        "action_type": action_type,
        "action_id": action_id,
        "expires_at": expires,
        "reply_with": f"CONFIRM {action_id}",
        "params_summary": {k: str(v)[:100] for k, v in params.items()},
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
    elif pending.action_type == "diagnose_service_allowlisted":
        result = _run_diagnose(pending.service)
    elif pending.action_type == "create_auditor_request":
        from ops.agents.logi_auditor_request import write_auditor_request
        rec = write_auditor_request(
            problem_summary=(pending.params or {}).get("problem_summary", ""),
            original_message=pending.original_message,
            requested_by=pending.requested_by,
            failure_class=(pending.params or {}).get("failure_class", "CAPABILITY_GAP"),
        )
        result = {"status": "PASSED", "request_id": rec.request_id,
                  "path": str(_ROOT / "aims_workspace" / "logi_auditor_requests" / "pending" / f"{rec.request_id}.json")}
    elif pending.action_type == "create_skill_request":
        from ops.agents.logi_skill_request import write_skill_request
        rec = write_skill_request(
            skill_name=(pending.params or {}).get("skill_name", "unnamed_skill"),
            purpose=(pending.params or {}).get("purpose", ""),
            original_message=pending.original_message,
            requested_by=pending.requested_by,
            auditor_review_required=True,
        )
        result = {"status": "PASSED", "request_id": rec.request_id,
                  "path": str(_ROOT / "aims_workspace" / "logi_skill_requests" / "pending" / f"{rec.request_id}.json"),
                  "auditor_review_required": True}
    elif pending.action_type == "register_learning_event":
        from ops.agents.logi_learning_recorder import write_learning_event_candidate
        ev = write_learning_event_candidate(
            source_message=pending.original_message,
            user_intent=(pending.params or {}).get("user_intent", pending.original_message),
            expected_behavior=(pending.params or {}).get("expected_behavior", ""),
            actual_behavior=(pending.params or {}).get("actual_behavior", ""),
            failure_class=(pending.params or {}).get("failure_class", "CAPABILITY_GAP"),
            lesson=(pending.params or {}).get("lesson", ""),
            requested_by=pending.requested_by,
        )
        result = {"status": "PASSED", "event_id": ev.event_id,
                  "path": str(_ROOT / "aims_workspace" / "logi_learning_events" / "pending" / f"{ev.event_id}.json"),
                  "training_eligible": False}
    elif pending.action_type == "queue_task_allowlisted":
        from ops.agents.logi_task_queue import write_pending_task
        rec = write_pending_task(
            title=(pending.params or {}).get("title", "unnamed_task"),
            description=(pending.params or {}).get("description", pending.original_message),
            requested_by=pending.requested_by,
            schedule_hint=(pending.params or {}).get("schedule_hint", "asap"),
        )
        result = {"status": "PASSED", "task_id": rec.task_id,
                  "path": str(_ROOT / "aims_workspace" / "logi_tasks" / "pending" / f"{rec.task_id}.json")}
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
    elif pending.action_type == "diagnose_service_allowlisted":
        resp["health"] = result.get("health")
        resp["log_lines_scanned"] = result.get("log_lines_scanned", 0)
        resp["errors_found"] = result.get("errors_found", 0)
        resp["top_findings"] = result.get("top_findings", [])
        resp["recommended_next_action"] = result.get("recommended_next_action", "")
        if not result.get("log_available", True):
            resp["error_class"] = "LOG_BACKEND_UNAVAILABLE"
    elif pending.action_type in ("create_auditor_request", "create_skill_request",
                                  "register_learning_event", "queue_task_allowlisted"):
        if result.get("status") == "PASSED":
            resp["path"] = result.get("path", "")
            if "auditor_review_required" in result:
                resp["auditor_review_required"] = result["auditor_review_required"]
            if "training_eligible" in result:
                resp["training_eligible"] = result["training_eligible"]
        else:
            resp["error_class"] = result.get("error", "WRITE_FAILED")
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

    # diagnose_service_allowlisted fields
    log_lines_scanned = resp.get("log_lines_scanned")
    if log_lines_scanned is not None:
        lines.append(f"LOG_LINES_SCANNED: {log_lines_scanned}")
    errors_found = resp.get("errors_found")
    if errors_found is not None:
        lines.append(f"ERRORS_FOUND: {errors_found}")
    top_findings = resp.get("top_findings")
    if top_findings:
        lines.append("TOP_FINDINGS:")
        for finding in top_findings:
            lines.append(f"- {finding}")
    recommended = resp.get("recommended_next_action")
    if recommended:
        lines.append(f"RECOMMENDED_NEXT_ACTION: {recommended}")

    # Write-action result fields
    path = resp.get("path")
    if path and status == "PASSED":
        lines.append(f"PATH: {path}")
    if resp.get("auditor_review_required") is True:
        lines.append("AUDITOR_REVIEW_REQUIRED: true")
    if resp.get("training_eligible") is False and "training_eligible" in resp:
        lines.append("TRAINING_ELIGIBLE: false (requires verifier)")

    # Log tail — appended last to keep header fields readable
    log_tail = resp.get("log_tail")
    if log_tail and status == "PASSED":
        lines.append(f"LOG_TAIL:\n{log_tail}")

    return "\n".join(lines)
