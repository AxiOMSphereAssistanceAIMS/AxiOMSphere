#!/usr/bin/env bash
# auditor_session_watcher.sh
#
# Called by the systemd timer. Runs preflight and logs the result.
# Intended to run every 10 minutes to keep auditor status fresh.
#
# Never performs interactive login. Never stores credentials.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ROOT="$(cd "$_SCRIPT_DIR/../.." && pwd)"
_LOG_DIR="$_ROOT/aims_workspace/runtime_status"
_LOG_FILE="$_LOG_DIR/auditor_watcher.log"

mkdir -p "$_LOG_DIR"

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

{
    echo "[$(_ts)] auditor_session_watcher starting"
    bash "$_SCRIPT_DIR/auditor_session_preflight.sh" && \
        echo "[$(_ts)] preflight OK" || \
        echo "[$(_ts)] preflight completed (no AVAILABLE auditor)"
} >> "$_LOG_FILE" 2>&1

# Keep log bounded to last 500 lines
tail -500 "$_LOG_FILE" > "$_LOG_FILE.tmp" && mv "$_LOG_FILE.tmp" "$_LOG_FILE"
