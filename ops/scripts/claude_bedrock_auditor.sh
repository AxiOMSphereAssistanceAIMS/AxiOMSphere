#!/usr/bin/env bash
# claude_bedrock_auditor.sh
# Claude Code CLI via AWS Bedrock fallback auditor.
#
# Interface: --preflight | --audit <prompt_file>
# Exit codes: 0/10/11/12/13/14/15/16 (same convention as Codex launchers)
#
# Never stores AWS secrets. Never hardcodes credentials.
# Never runs aws sso login. Never opens browser. Never waits for operator input.
# If AWS auth is expired, returns AUTH_REQUIRED (exit 10) immediately.

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

# Bedrock requires these env vars
_check_bedrock_env() {
    if [ "${CLAUDE_CODE_USE_BEDROCK:-}" != "1" ]; then
        echo '{"status":"NOT_CONFIGURED","reason":"CLAUDE_CODE_USE_BEDROCK not set to 1","auth_required":false}'
        return 1
    fi
    if [ -z "${AWS_PROFILE:-}${AWS_ACCESS_KEY_ID:-}" ]; then
        echo '{"status":"NOT_CONFIGURED","reason":"AWS_PROFILE or AWS_ACCESS_KEY_ID not set","auth_required":false}'
        return 1
    fi
    return 0
}

_check_aws_auth() {
    # Quick non-interactive identity check — 10s timeout, no login
    if command -v aws >/dev/null 2>&1; then
        _ident="$(timeout 10 aws sts get-caller-identity 2>&1 || true)"
        if echo "$_ident" | grep -qiE "(ExpiredToken|InvalidToken|SSOTokenExpired|UnauthorizedAccess|AuthFailure|NoCredentialProviders)"; then
            echo '{"status":"AUTH_REQUIRED","reason":"AWS credentials expired or invalid","auth_required":true}'
            return 1
        fi
        if echo "$_ident" | grep -q '"Account"'; then
            return 0  # Auth OK
        fi
    fi
    return 0  # AWS CLI not available — assume auth OK if Bedrock env is set
}

if [ "$_MODE" = "preflight" ]; then
    # Check claude binary
    _CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
    if [ -z "$_CLAUDE_BIN" ]; then
        echo '{"status":"NOT_CONFIGURED","reason":"claude binary not found","auth_required":false}'
        exit 13
    fi

    # Check Bedrock env
    if ! _check_bedrock_env; then
        exit 13
    fi

    # Check AWS auth
    if ! _check_aws_auth; then
        exit 10
    fi

    # Quick non-interactive probe
    _probe_output="$(CLAUDE_CODE_USE_BEDROCK=1 \
        timeout 15 "$_CLAUDE_BIN" \
        -p "Output only: {\"status\":\"PREFLIGHT_OK\"}" \
        --output-format json \
        2>&1 || true)"
    _probe_exit=$?

    if [ "$_probe_exit" -eq 124 ]; then
        echo '{"status":"TIMEOUT","reason":"bedrock preflight probe timed out","auth_required":false}'
        exit 14
    fi

    if echo "$_probe_output" | grep -qiE "(login|authenticate|sign.?in|token.*expired|unauthorized|401|403|ExpiredToken)"; then
        echo '{"status":"AUTH_REQUIRED","reason":"Bedrock auth required or expired","auth_required":true}'
        exit 10
    fi

    echo '{"status":"AVAILABLE","binary":"'"$_CLAUDE_BIN"'","provider":"bedrock","auth_required":false}'
    exit 0
fi

if [ "$_MODE" = "audit" ]; then
    if [ -z "$_PROMPT_FILE" ] || [ ! -f "$_PROMPT_FILE" ]; then
        echo '{"status":"AUDIT_FAILED","reason":"prompt file not found: '"$_PROMPT_FILE"'"}' >&2
        exit 15
    fi

    _CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
    if [ -z "$_CLAUDE_BIN" ]; then
        echo '{"status":"NOT_CONFIGURED","reason":"claude binary not found"}' >&2
        exit 13
    fi

    if ! _check_bedrock_env >/dev/null 2>&1; then
        echo '{"status":"NOT_CONFIGURED","reason":"CLAUDE_CODE_USE_BEDROCK env not configured"}' >&2
        exit 13
    fi

    if ! _check_aws_auth >/dev/null 2>&1; then
        echo '{"status":"AUTH_REQUIRED","reason":"AWS auth expired"}' >&2
        exit 10
    fi

    _PROMPT="$(cat "$_PROMPT_FILE")"
    _timeout="${AIMS_AUDITOR_TIMEOUT_SECONDS:-300}"
    _model="${ANTHROPIC_MODEL:-us.anthropic.claude-sonnet-4-6}"

    _output="$(CLAUDE_CODE_USE_BEDROCK=1 \
        ANTHROPIC_MODEL="$_model" \
        timeout "$_timeout" "$_CLAUDE_BIN" \
        -p "$_PROMPT" \
        --output-format text \
        2>&1)" || _exit=$?

    if [ "${_exit:-0}" -eq 124 ]; then
        echo '{"status":"TIMEOUT","reason":"bedrock audit timed out"}' >&2
        exit 14
    fi

    if echo "$_output" | grep -qiE "(login|authenticate|sign.?in|token.*expired|unauthorized|401|403|ExpiredToken)"; then
        echo '{"status":"AUTH_REQUIRED","reason":"Bedrock auth required or expired"}' >&2
        exit 10
    fi

    printf '%s' "$_output"
    exit 0
fi

echo "ERROR: no mode selected" >&2
exit 16
