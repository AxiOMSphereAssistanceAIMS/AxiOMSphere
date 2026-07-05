#!/usr/bin/env bash
# verify_slot32_executor_contract.sh
# Smoke-test that local slot32 launcher enforces the executor-lite contract.
# Exit 0 = all checks pass. Exit 1 = one or more checks failed.

set -euo pipefail

ROOT="${AIMS_ROOT:-$HOME/aims-workspace}"
PROXY_HEALTH_URL="${SLOT32_PROXY_HEALTH_URL:-http://127.0.0.1:8084/health}"
LAUNCHER="$ROOT/ops/scripts/claude_local_slot32.sh"
SESSION_SETTINGS="$ROOT/aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_session_settings_latest.json"

PASS=0
FAIL=0

check() {
    local label="$1"
    local result="$2"    # "ok" or "fail"
    local detail="$3"
    if [ "$result" = "ok" ]; then
        echo "  ✅ $label"
        PASS=$((PASS + 1))
    else
        echo "  ❌ $label — $detail"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== slot32 executor-lite contract verification ==="
echo

# 1. Launcher explicitly unsets CLAUDE_CODE_USE_BEDROCK (checked in launcher source,
#    not in calling shell — the calling shell may have it set for other sessions).
if grep -q 'unset CLAUDE_CODE_USE_BEDROCK' "$LAUNCHER" 2>/dev/null; then
    check "Launcher explicitly unsets CLAUDE_CODE_USE_BEDROCK" "ok" ""
else
    check "Launcher explicitly unsets CLAUDE_CODE_USE_BEDROCK" "fail" "not found in $LAUNCHER"
fi

# 2. Launcher sets ANTHROPIC_BASE_URL to local proxy
if grep -q 'ANTHROPIC_BASE_URL.*127.0.0.1:8084' "$LAUNCHER" 2>/dev/null; then
    check "Launcher sets ANTHROPIC_BASE_URL=http://127.0.0.1:8084" "ok" ""
else
    check "Launcher sets ANTHROPIC_BASE_URL=http://127.0.0.1:8084" "fail" "not found in $LAUNCHER"
fi

# 3. Launcher sets ANTHROPIC_MODEL=slot32
if grep -q 'ANTHROPIC_MODEL.*slot32\|MODEL.*slot32' "$LAUNCHER" 2>/dev/null; then
    check "Launcher sets ANTHROPIC_MODEL=slot32" "ok" ""
else
    check "Launcher sets ANTHROPIC_MODEL=slot32" "fail" "not found in $LAUNCHER"
fi

# 4. Launcher unsets CLAUDE_CODE_USE_BEDROCK
if grep -q 'unset CLAUDE_CODE_USE_BEDROCK' "$LAUNCHER" 2>/dev/null; then
    check "Launcher unsets CLAUDE_CODE_USE_BEDROCK" "ok" ""
else
    check "Launcher unsets CLAUDE_CODE_USE_BEDROCK" "fail" "not found in $LAUNCHER"
fi

# 5. Proxy health check — model must be axi_omi_sphere:latest
proxy_response="$(curl -fsS --max-time 5 "$PROXY_HEALTH_URL" 2>/dev/null || echo '')"
if echo "$proxy_response" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('ok') is True, 'ok is not true'
assert 'axi_omi_sphere' in d.get('model', ''), f'unexpected model: {d.get(\"model\")}'
" 2>/dev/null; then
    proxy_model="$(echo "$proxy_response" | python3 -c "import json,sys; print(json.load(sys.stdin).get('model','?'))")"
    check "Proxy health returns ok=true, model=axi_omi_sphere:latest" "ok" ""
    echo "     proxy model: $proxy_model"
else
    if [ -z "$proxy_response" ]; then
        check "Proxy health returns ok=true, model=axi_omi_sphere:latest" "fail" "proxy unreachable at $PROXY_HEALTH_URL"
    else
        check "Proxy health returns ok=true, model=axi_omi_sphere:latest" "fail" "unexpected response: $proxy_response"
    fi
fi

# 6. Session settings file disables superpowers and desktop-commander
# (only valid after launcher has been run at least once)
if [ -f "$SESSION_SETTINGS" ]; then
    if python3 -c "
import json, sys
d = json.load(open('$SESSION_SETTINGS'))
plugins = d.get('enabledPlugins', {})
assert plugins.get('superpowers@claude-plugins-official') is False, 'superpowers not disabled'
assert plugins.get('desktop-commander@claude-plugins-official') is False, 'desktop-commander not disabled'
" 2>/dev/null; then
        check "Session settings disable superpowers and desktop-commander" "ok" ""
    else
        check "Session settings disable superpowers and desktop-commander" "fail" "check $SESSION_SETTINGS"
    fi
else
    echo "  ⚠️  Session settings file not yet generated (run launcher first): $SESSION_SETTINGS"
    echo "     Re-run this script after first launcher invocation."
fi

# 7. Launcher system prompt contains anti-fabrication contract
if grep -q 'EXECUTOR-LITE CONTRACT' "$LAUNCHER" 2>/dev/null && \
   grep -q 'NEED_EXECUTION' "$LAUNCHER" 2>/dev/null && \
   grep -q 'Never fabricate' "$LAUNCHER" 2>/dev/null; then
    check "Launcher system prompt contains executor-lite contract" "ok" ""
else
    check "Launcher system prompt contains executor-lite contract" "fail" "check --append-system-prompt in $LAUNCHER"
fi

# 8. Launcher system prompt contains FINAL response format
if grep -q 'FINAL:' "$LAUNCHER" 2>/dev/null; then
    check "Launcher system prompt contains FINAL response format" "ok" ""
else
    check "Launcher system prompt contains FINAL response format" "fail" "check --append-system-prompt in $LAUNCHER"
fi

echo
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
