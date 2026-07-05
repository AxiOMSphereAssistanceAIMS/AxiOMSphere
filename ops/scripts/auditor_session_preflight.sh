#!/usr/bin/env bash
# auditor_session_preflight.sh
#
# Run preflight on all three auditor routes and write the result to:
#   aims_workspace/runtime_status/auditor_chain_status.json
#
# Never performs interactive login. Never stores credentials.
# Returns 0 if at least one auditor is AVAILABLE, 1 otherwise.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ROOT="$(cd "$_SCRIPT_DIR/../.." && pwd)"
# shellcheck source=load_auditor_env.sh
source "$_SCRIPT_DIR/load_auditor_env.sh"

_STATUS_DIR="$_ROOT/aims_workspace/runtime_status"
_STATUS_FILE="$_STATUS_DIR/auditor_chain_status.json"
_PREFLIGHT_TIMEOUT="${AIMS_AUDITOR_PREFLIGHT_TIMEOUT_SECONDS:-30}"

mkdir -p "$_STATUS_DIR"

_now_utc() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

_run_preflight() {
    local launcher="$1"
    local output exit_code
    if [ ! -f "$launcher" ]; then
        printf '{"status":"NOT_CONFIGURED","reason":"launcher_not_found"}'
        return
    fi
    output="$(timeout "$_PREFLIGHT_TIMEOUT" bash "$launcher" --preflight 2>&1)" \
        && exit_code=0 || exit_code=$?
    case "$exit_code" in
        0)   printf '%s' "$output" ;;
        10)  printf '{"status":"AUTH_REQUIRED","exit":10}' ;;
        11)  printf '{"status":"WRONG_BINARY","exit":11}' ;;
        12)  printf '{"status":"RATE_LIMITED","exit":12}' ;;
        13)  printf '{"status":"NOT_CONFIGURED","exit":13}' ;;
        14)  printf '{"status":"TIMEOUT","exit":14}' ;;
        124) printf '{"status":"TIMEOUT","exit":124}' ;;
        *)   printf '{"status":"FAILED","exit":%d}' "$exit_code" ;;
    esac
}

_extract_status() {
    local json="$1"
    python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('status','FAILED'))" \
        <<< "$json" 2>/dev/null || echo "FAILED"
}

# Run all three preflights
_primary_json="$(_run_preflight "$AIMS_CODEX_AUDITOR_CMD")"
_secondary_json="$(_run_preflight "$AIMS_CODEX_AUDITOR_FALLBACK_CMD")"
_bedrock_json="$(_run_preflight "$AIMS_CLAUDE_BEDROCK_AUDITOR_CMD")"

_primary_status="$(_extract_status "$_primary_json")"
_secondary_status="$(_extract_status "$_secondary_json")"
_bedrock_status="$(_extract_status "$_bedrock_json")"

# Selection logic
_active_auditor="none"
_chain_status="FAILED"

if [ "$_primary_status" = "AVAILABLE" ]; then
    _active_auditor="primary_codex"
    _chain_status="AVAILABLE"
elif [ "$_secondary_status" = "AVAILABLE" ]; then
    _active_auditor="secondary_codex"
    _chain_status="DEGRADED"
elif [ "$_bedrock_status" = "AVAILABLE" ]; then
    _active_auditor="claude_bedrock"
    _chain_status="DEGRADED"
elif [ "$_primary_status" = "AUTH_REQUIRED" ] || \
     [ "$_secondary_status" = "AUTH_REQUIRED" ] || \
     [ "$_bedrock_status" = "AUTH_REQUIRED" ]; then
    _chain_status="AUTH_REQUIRED"
fi

# Write status JSON
python3 - <<PY
import json, os
from datetime import datetime, timezone

primary_json   = json.loads("""${_primary_json}""")
secondary_json = json.loads("""${_secondary_json}""")
bedrock_json   = json.loads("""${_bedrock_json}""")

status = {
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "primary_codex": {
        "status": primary_json.get("status", "FAILED"),
        "home": os.environ.get("AIMS_CODEX_PRIMARY_HOME", ""),
        "interactive_login_attempted": False,
        "preflight_detail": primary_json,
    },
    "secondary_codex": {
        "status": secondary_json.get("status", "FAILED"),
        "home": os.environ.get("AIMS_CODEX_SECONDARY_HOME", ""),
        "interactive_login_attempted": False,
        "preflight_detail": secondary_json,
    },
    "claude_bedrock": {
        "status": bedrock_json.get("status", "FAILED"),
        "aws_profile": os.environ.get("AIMS_CLAUDE_BEDROCK_AWS_PROFILE", ""),
        "region": os.environ.get("AIMS_CLAUDE_BEDROCK_AWS_REGION", ""),
        "interactive_login_attempted": False,
        "preflight_detail": bedrock_json,
    },
    "active_auditor": "${_active_auditor}",
    "chain_status": "${_chain_status}",
}

out = "${_STATUS_FILE}"
with open(out, "w") as f:
    json.dump(status, f, indent=2)
print(f"Written: {out}")
PY

echo "CHAIN_STATUS: $_chain_status  ACTIVE_AUDITOR: $_active_auditor"

# Return 0 if at least one auditor available, 1 otherwise
[ "$_active_auditor" != "none" ]
