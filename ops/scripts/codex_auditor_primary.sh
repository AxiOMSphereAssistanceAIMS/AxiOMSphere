#!/usr/bin/env bash
# codex_auditor_primary.sh
# Primary Codex LLM auditor launcher.
#
# Interface:
#   --preflight        Exit 0 if auditor is available and authenticated.
#   --audit <file>     Run audit with prompt from <file>, print JSON to stdout.
#
# Exit codes:
#   0  AVAILABLE / audit success
#   10 AUTH_REQUIRED
#   11 WRONG_BINARY (static site generator, wrong codex)
#   12 RATE_LIMITED
#   13 NOT_CONFIGURED
#   14 TIMEOUT
#   15 AUDIT_FAILED
#   16 INVALID_USAGE
#
# Never initiates login. Never opens browser. Never asks for password.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=load_auditor_env.sh
source "$_SCRIPT_DIR/load_auditor_env.sh"

_MODE=""
_PROMPT_FILE=""

if [ $# -eq 0 ]; then
    echo "Usage: $0 --preflight | --audit <prompt_file>" >&2
    exit 16
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --preflight) _MODE="preflight" ;;
        --audit)
            _MODE="audit"
            _PROMPT_FILE="${2:-}"
            if [ -z "$_PROMPT_FILE" ]; then
                echo "ERROR: --audit requires a prompt file argument" >&2
                exit 16
            fi
            shift
            ;;
        *) echo "ERROR: unknown argument: $1" >&2; exit 16 ;;
    esac
    shift
done

# Resolve binary
_CODEX_BIN="${AIMS_CODEX_PRIMARY_BIN:-}"
if [ -z "$_CODEX_BIN" ]; then
    _CODEX_BIN="$(command -v codex 2>/dev/null || true)"
fi

# Validate binary is an LLM auditor, not the static site generator
_validate_binary() {
    local bin="$1"
    [ -z "$bin" ] && return 1
    [ -x "$bin" ] || return 1
    # Run --version or --help; reject if output mentions static site / template
    local info
    info="$("$bin" --version 2>/dev/null || "$bin" --help 2>/dev/null || true)"
    if echo "$info" | grep -qiE "static site|template|render your codex|build.*outDir|skeleton site"; then
        return 1  # Wrong binary — static site generator
    fi
    # Must mention some LLM / AI / code review capability
    if echo "$info" | grep -qiE "openai|model|llm|ai|code\s*review|agent|gpt|claude"; then
        return 0
    fi
    # If neither pattern matches, reject (unknown binary)
    return 1
}

if [ "$_MODE" = "preflight" ]; then
    # Check binary exists
    if [ -z "$_CODEX_BIN" ]; then
        echo '{"status":"NOT_CONFIGURED","reason":"codex binary not found","auth_required":false}'
        exit 13
    fi

    # Check it is the right binary
    if ! _validate_binary "$_CODEX_BIN"; then
        echo '{"status":"WRONG_BINARY","reason":"binary is not an LLM auditor (static site generator or unknown)","binary":"'"$_CODEX_BIN"'","auth_required":false}'
        exit 11
    fi

    # Check auth — run a trivial non-interactive probe with very short timeout
    # Do NOT run any login command
    _probe_output="$(timeout 15 "$_CODEX_BIN" \
        ${AIMS_CODEX_PRIMARY_EXTRA_ARGS:-} \
        --no-interactive \
        "Output only: {\"status\":\"PREFLIGHT_OK\"}" 2>&1 || true)"
    _probe_exit=$?

    if [ "$_probe_exit" -eq 124 ]; then
        echo '{"status":"TIMEOUT","reason":"preflight probe timed out after 15s","auth_required":false}'
        exit 14
    fi

    if echo "$_probe_output" | grep -qiE "(login|authenticate|sign.?in|auth.*required|token.*expired|unauthorized|401|403)"; then
        echo '{"status":"AUTH_REQUIRED","reason":"auditor requires authentication","auth_required":true}'
        exit 10
    fi

    echo '{"status":"AVAILABLE","binary":"'"$_CODEX_BIN"'","auth_required":false}'
    exit 0
fi

if [ "$_MODE" = "audit" ]; then
    if [ -z "$_PROMPT_FILE" ] || [ ! -f "$_PROMPT_FILE" ]; then
        echo '{"status":"AUDIT_FAILED","reason":"prompt file not found: '"$_PROMPT_FILE"'"}' >&2
        exit 15
    fi

    if [ -z "$_CODEX_BIN" ]; then
        echo '{"status":"NOT_CONFIGURED","reason":"codex binary not found"}' >&2
        exit 13
    fi

    if ! _validate_binary "$_CODEX_BIN"; then
        echo '{"status":"WRONG_BINARY","reason":"binary is not an LLM auditor"}' >&2
        exit 11
    fi

    _PROMPT="$(cat "$_PROMPT_FILE")"
    _timeout="${AIMS_AUDITOR_TIMEOUT_SECONDS:-300}"

    _output="$(timeout "$_timeout" "$_CODEX_BIN" \
        ${AIMS_CODEX_PRIMARY_EXTRA_ARGS:-} \
        --no-interactive \
        "$_PROMPT" 2>&1)" || _exit=$?

    if [ "${_exit:-0}" -eq 124 ]; then
        echo '{"status":"TIMEOUT","reason":"audit timed out"}' >&2
        exit 14
    fi

    if echo "$_output" | grep -qiE "(login|authenticate|sign.?in|auth.*required|token.*expired|unauthorized|401|403)"; then
        echo '{"status":"AUTH_REQUIRED","reason":"auditor requires authentication"}' >&2
        exit 10
    fi

    printf '%s' "$_output"
    exit 0
fi

echo "ERROR: no mode selected" >&2
exit 16
