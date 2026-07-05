#!/usr/bin/env bash
# auditor_session_status.sh
#
# Print human-readable auditor chain status.
# Reads aims_workspace/runtime_status/auditor_chain_status.json if fresh (<15 min).
# Otherwise runs a live preflight.
#
# Never performs interactive login.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ROOT="$(cd "$_SCRIPT_DIR/../.." && pwd)"
# shellcheck source=load_auditor_env.sh
source "$_SCRIPT_DIR/load_auditor_env.sh"

_STATUS_FILE="$_ROOT/aims_workspace/runtime_status/auditor_chain_status.json"
_STALE_SECONDS=900  # 15 minutes

_is_stale() {
    [ ! -f "$_STATUS_FILE" ] && return 0
    local mod_epoch now_epoch age
    mod_epoch="$(date -r "$_STATUS_FILE" +%s 2>/dev/null || echo 0)"
    now_epoch="$(date +%s)"
    age=$((now_epoch - mod_epoch))
    [ "$age" -gt "$_STALE_SECONDS" ]
}

if _is_stale; then
    echo "[auditor_session_status] Status file missing or stale — running live preflight..."
    bash "$_SCRIPT_DIR/auditor_session_preflight.sh" >/dev/null 2>&1 || true
fi

if [ ! -f "$_STATUS_FILE" ]; then
    echo "ERROR: Could not generate status file" >&2
    exit 1
fi

_ROOT_FOR_PY="$_ROOT"
python3 - "$_ROOT_FOR_PY" <<'PY'
import json, os, sys
from datetime import datetime, timezone

ROOT = sys.argv[1]
status_file = os.path.join(ROOT, "aims_workspace/runtime_status/auditor_chain_status.json")

try:
    with open(status_file) as f:
        s = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"ERROR reading status file: {e}", file=sys.stderr)
    sys.exit(1)

p  = s.get("primary_codex",   {})
sc = s.get("secondary_codex", {})
b  = s.get("claude_bedrock",  {})

print(f"PRIMARY_CODEX:    {p.get('status', 'UNKNOWN')}")
print(f"SECONDARY_CODEX:  {sc.get('status', 'UNKNOWN')}")
print(f"CLAUDE_BEDROCK:   {b.get('status', 'UNKNOWN')}")
print(f"ACTIVE_AUDITOR:   {s.get('active_auditor', 'none')}")
print(f"CHAIN_STATUS:     {s.get('chain_status', 'UNKNOWN')}")
print(f"UPDATED_AT:       {s.get('updated_at_utc', 'unknown')}")
print()

# Next required action
active = s.get("active_auditor", "none")
chain  = s.get("chain_status", "UNKNOWN")

if chain == "AVAILABLE":
    print(f"NEXT_REQUIRED_ACTION: None — {active} is available.")
elif chain == "DEGRADED":
    print(f"NEXT_REQUIRED_ACTION: {active} is active (degraded). "
          "Restore primary/secondary Codex when convenient.")
else:
    actions = []
    if p.get("status") in ("AUTH_REQUIRED", "AUTH_EXPIRED"):
        ph = os.environ.get("AIMS_CODEX_PRIMARY_HOME", "~/.codex-primary")
        actions.append(
            f"  Primary Codex login required (manual):\n"
            f"  HOME={ph} <real_codex_login_command>"
        )
    if sc.get("status") in ("AUTH_REQUIRED", "AUTH_EXPIRED"):
        sh = os.environ.get("AIMS_CODEX_SECONDARY_HOME", "~/.codex-secondary")
        actions.append(
            f"  Secondary Codex login required (manual):\n"
            f"  HOME={sh} <real_codex_login_command>"
        )
    if b.get("status") == "AUTH_REQUIRED":
        profile = os.environ.get("AIMS_CLAUDE_BEDROCK_AWS_PROFILE", "")
        region  = os.environ.get("AIMS_CLAUDE_BEDROCK_AWS_REGION", "us-west-2")
        actions.append(
            f"  AWS Bedrock login required (manual):\n"
            f"  AWS_PROFILE={profile} AWS_DEFAULT_REGION={region} aws sso login"
        )
    if not actions:
        actions.append(f"  Check auditor configuration. Chain status: {chain}")
    print("NEXT_REQUIRED_ACTION:")
    for a in actions:
        print(a)
PY
