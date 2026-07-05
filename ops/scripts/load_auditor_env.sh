#!/usr/bin/env bash
# load_auditor_env.sh
# Source auditor chain environment.
# Never prints secrets. Safe to source from any script.

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_ROOT="$(cd "$_SCRIPT_DIR/../.." && pwd)"

# Load local env file if it exists (not committed — contains no secrets)
if [ -f "$_ROOT/.env.auditors.local" ]; then
    # shellcheck disable=SC1091
    source "$_ROOT/.env.auditors.local"
fi

# Set default command paths if env vars are not already set
: "${AIMS_CODEX_AUDITOR_CMD:=$_SCRIPT_DIR/codex_auditor_primary.sh}"
: "${AIMS_CODEX_AUDITOR_FALLBACK_CMD:=$_SCRIPT_DIR/codex_auditor_secondary.sh}"
: "${AIMS_CLAUDE_BEDROCK_AUDITOR_CMD:=$_SCRIPT_DIR/claude_bedrock_auditor.sh}"
: "${AIMS_AUDITOR_TIMEOUT_SECONDS:=300}"

export AIMS_CODEX_AUDITOR_CMD
export AIMS_CODEX_AUDITOR_FALLBACK_CMD
export AIMS_CLAUDE_BEDROCK_AUDITOR_CMD
export AIMS_AUDITOR_TIMEOUT_SECONDS
