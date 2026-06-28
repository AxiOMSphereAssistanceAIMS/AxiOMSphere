#!/usr/bin/env bash
set -euo pipefail

ROOT="${AIMS_ROOT:-$HOME/aims-workspace}"
LOCK_FILE="${SLOT32_CLAUDE_LOCK_FILE:-/tmp/claude_local_slot32.lock}"
PROXY_URL="${SLOT32_CLAUDE_PROXY_URL:-http://127.0.0.1:8084/v1/messages}"
HEALTH_URL="${SLOT32_CLAUDE_PROXY_HEALTH_URL:-http://127.0.0.1:8084/health}"
API_KEY="${SLOT32_CLAUDE_API_KEY:-aims-local-repair-token}"
MODEL="${SLOT32_CLAUDE_MODEL:-axi_omi_sphere:latest}"
MAX_TOKENS="${SLOT32_ONESHOT_MAX_TOKENS:-192}"
LOCK_WAIT_S="${SLOT32_ONESHOT_LOCK_WAIT_S:-180}"
RETRY_ATTEMPTS="${SLOT32_ONESHOT_RETRY_ATTEMPTS:-8}"
RETRY_BASE_SLEEP_S="${SLOT32_ONESHOT_RETRY_BASE_SLEEP_S:-5}"
HTTP_TIMEOUT_S="${SLOT32_ONESHOT_HTTP_TIMEOUT_S:-120}"

if [ $# -lt 1 ]; then
  echo "usage: $0 <prompt> [extra claude args...]" >&2
  exit 2
fi

PROMPT="${1:-}"
shift || true

cd "$ROOT"

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
if ! flock -w "$LOCK_WAIT_S" 9; then
  echo "ERROR: slot32 busy; timed out waiting for lock after ${LOCK_WAIT_S}s" >&2
  exit 75
fi

python3 - "$PROXY_URL" "$HEALTH_URL" "$API_KEY" "$MODEL" "$MAX_TOKENS" "$HTTP_TIMEOUT_S" "$PROMPT" "$@" <<'PY'
from __future__ import annotations

import json
import os
import socket
import time
import sys
import urllib.error
import urllib.request

proxy_url, health_url, api_key, model, max_tokens_s, http_timeout_s, prompt = sys.argv[1:8]
extra = sys.argv[8:]
max_tokens = int(max_tokens_s)
http_timeout = int(http_timeout_s)
retry_attempts = int(os.environ.get("SLOT32_ONESHOT_RETRY_ATTEMPTS", "8"))
retry_base_sleep_s = int(os.environ.get("SLOT32_ONESHOT_RETRY_BASE_SLEEP_S", "5"))

def health_check() -> None:
    req = urllib.request.Request(health_url, headers={"x-api-key": api_key}, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"health status {resp.status}")

def build_body() -> dict:
    system = (
        "You are local AIMS slot32. Keep context bounded. "
        "Split large tasks into phases. Do not paste large files or logs into chat. "
        "Write large outputs to files. Use claude-mem only through bounded summaries plus file paths. "
        "Never inject raw memory dumps or huge logs into the main request. "
        "Before context grows too large, write a checkpoint and continue from a clean session."
    )
    if extra:
        system += " Extra args: " + " ".join(extra)
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

try:
    health_check()
except Exception as exc:
    print(f"ERROR: proxy health check failed: {exc}", file=sys.stderr)
    raise SystemExit(76)

body = build_body()
raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
headers = {
    "Content-Type": "application/json",
    "x-api-key": api_key,
    "User-Agent": "aims-slot32-oneshot/1.0",
}

payload = ""
last_error = None
for attempt in range(1, retry_attempts + 1):
    req = urllib.request.Request(proxy_url, data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
        last_error = None
        break
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in {429, 502, 503, 504} and attempt < retry_attempts:
            sleep_s = retry_base_sleep_s * attempt
            print(
                f"WARN: HTTP {exc.code} on attempt {attempt}/{retry_attempts}; retrying in {sleep_s}s",
                file=sys.stderr,
            )
            if body:
                print(body, file=sys.stderr)
            time.sleep(sleep_s)
            last_error = exc
            continue
        print(f"ERROR: HTTP {exc.code}", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        raise SystemExit(77)
    except urllib.error.URLError as exc:
        if attempt < retry_attempts:
            sleep_s = retry_base_sleep_s * attempt
            print(
                f"WARN: request failed on attempt {attempt}/{retry_attempts}: {exc}; retrying in {sleep_s}s",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
            last_error = exc
            continue
        print(f"ERROR: request failed: {exc}", file=sys.stderr)
        raise SystemExit(78)
    except (TimeoutError, socket.timeout) as exc:
        if attempt < retry_attempts:
            sleep_s = retry_base_sleep_s * attempt
            print(
                f"WARN: timeout on attempt {attempt}/{retry_attempts}: {exc}; retrying in {sleep_s}s",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
            last_error = exc
            continue
        print(f"ERROR: timeout: {exc}", file=sys.stderr)
        raise SystemExit(78)

if not payload:
    if last_error is not None:
        print(f"ERROR: failed after {retry_attempts} attempts: {last_error}", file=sys.stderr)
    raise SystemExit(78)

try:
    data = json.loads(payload)
except Exception:
    print("ERROR: invalid JSON from proxy", file=sys.stderr)
    print(payload, file=sys.stderr)
    raise SystemExit(79)

content = ""
if isinstance(data, dict):
    for item in data.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            content = str(item.get("text", ""))
            break

if not content:
    content = payload

print(content.strip())
PY
