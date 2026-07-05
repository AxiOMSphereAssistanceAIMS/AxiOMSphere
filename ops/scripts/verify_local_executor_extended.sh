#!/usr/bin/env bash
# verify_local_executor_extended.sh
#
# Extended acceptance tests for the local executor.
# Tests: test_02 (read), test_03 (missing file failure),
#        test_04 (dangerous command rejection), test_05 (workspace artifact).
#
# Returns 0 (all passed) or 1 (any failed).
# Never silently passes. Never accepts expected_output as evidence.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXECUTOR="$ROOT/ops/scripts/aims_local_executor.py"
PASS=0
FAIL=0

_check() {
    local label="$1" result="$2" detail="${3:-}"
    if [ "$result" = "ok" ]; then
        echo "  ✅ $label"
        PASS=$((PASS + 1))
    else
        echo "  ❌ $label${detail:+ — $detail}"
        FAIL=$((FAIL + 1))
    fi
}

_run_task() {
    local task_file="$1"
    # `|| true` prevents set -e from aborting on executor FAILED exit (exit 1)
    python3 "$EXECUTOR" "$ROOT/$task_file" 2>&1 || true
}

_json_field() {
    local json="$1" field="$2"
    python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('$field',''))" <<< "$json" 2>/dev/null || echo ""
}

_json_error_class() {
    local json="$1"
    python3 -c "
import json,sys
d=json.loads(sys.stdin.read())
# Top-level error_class
ec = d.get('error_class','')
if not ec:
    # Check first failed action
    for a in d.get('actions_executed',[]):
        if a.get('status')=='FAILED' and a.get('error_class'):
            ec = a['error_class']
            break
print(ec)
" <<< "$json" 2>/dev/null || echo ""
}

echo "=== AIMS Local Executor Extended Acceptance Tests ==="
echo

# ─────────────────────────────────────────────────────────────────────────────
# Test 01 (baseline) — must pass as prerequisite
echo "[TEST_01] Baseline: create file + verify"
rm -f /tmp/aims_executor_test_01.txt
OUT="$(_run_task aims_workspace/test_tasks/executor_test_01.json)"
STATUS="$(_json_field "$OUT" status)"
[ "$STATUS" = "PASSED" ] && _check "test_01 baseline" "ok" "" || _check "test_01 baseline" "fail" "status=$STATUS"

# ─────────────────────────────────────────────────────────────────────────────
# Test 02 — read existing file
echo ""
echo "[TEST_02] Read existing file"
OUT="$(_run_task aims_workspace/test_tasks/executor_test_02_read_file.json)"
STATUS="$(_json_field "$OUT" status)"
_check "test_02 status=PASSED" "$([ "$STATUS" = "PASSED" ] && echo ok || echo fail)" "got: $STATUS"
FILE_CONTENT="$(cat /tmp/aims_executor_test_01.txt 2>/dev/null | tr -d '\n')"
_check "test_02 content independent verify" \
    "$([ "$FILE_CONTENT" = "AIMS_EXECUTOR_TEST_01_PASS" ] && echo ok || echo fail)" \
    "got: $FILE_CONTENT"

# ─────────────────────────────────────────────────────────────────────────────
# Test 03 — missing file must FAIL with FILE_NOT_FOUND
echo ""
echo "[TEST_03] Missing file must FAIL"
rm -f /tmp/aims_missing_executor_test.txt
OUT="$(_run_task aims_workspace/test_tasks/executor_test_03_missing_file_failure.json)"
STATUS="$(_json_field "$OUT" status)"
ERROR_CLASS="$(_json_error_class "$OUT")"
_check "test_03 status=FAILED" "$([ "$STATUS" = "FAILED" ] && echo ok || echo fail)" "got: $STATUS"
_check "test_03 error_class=FILE_NOT_FOUND" \
    "$([ "$ERROR_CLASS" = "FILE_NOT_FOUND" ] && echo ok || echo fail)" "got: $ERROR_CLASS"
_check "test_03 no false PASSED" "$([ "$STATUS" != "PASSED" ] && echo ok || echo fail)" ""

# ─────────────────────────────────────────────────────────────────────────────
# Test 04 — dangerous command must FAIL with COMMAND_BLOCKED
echo ""
echo "[TEST_04] Dangerous command (rm -rf) must be rejected"
BEFORE_EXISTS="$([ -f /tmp/aims_executor_test_01.txt ] && echo yes || echo no)"
OUT="$(_run_task aims_workspace/test_tasks/executor_test_04_reject_dangerous_command.json)"
STATUS="$(_json_field "$OUT" status)"
ERROR_CLASS="$(_json_error_class "$OUT")"
AFTER_EXISTS="$([ -f /tmp/aims_executor_test_01.txt ] && echo yes || echo no)"
_check "test_04 status=FAILED" "$([ "$STATUS" = "FAILED" ] && echo ok || echo fail)" "got: $STATUS"
_check "test_04 error_class=COMMAND_BLOCKED" \
    "$([ "$ERROR_CLASS" = "COMMAND_BLOCKED" ] && echo ok || echo fail)" "got: $ERROR_CLASS"
_check "test_04 file not deleted by rm" \
    "$([ "$AFTER_EXISTS" = "yes" ] && echo ok || echo fail)" \
    "file was ${BEFORE_EXISTS} before, ${AFTER_EXISTS} after"

# ─────────────────────────────────────────────────────────────────────────────
# Test 05 — workspace artifact
echo ""
echo "[TEST_05] Workspace artifact write"
TARGET="$ROOT/aims_workspace/runtime_status/executor_controlled_artifact.txt"
rm -f "$TARGET"
OUT="$(_run_task aims_workspace/test_tasks/executor_test_05_workspace_artifact.json)"
STATUS="$(_json_field "$OUT" status)"
_check "test_05 status=PASSED" "$([ "$STATUS" = "PASSED" ] && echo ok || echo fail)" "got: $STATUS"
_check "test_05 file created" "$([ -f "$TARGET" ] && echo ok || echo fail)" ""
if [ -f "$TARGET" ]; then
    ACTUAL="$(cat "$TARGET" | tr -d '\n')"
    _check "test_05 content matches" \
        "$([ "$ACTUAL" = "AIMS_EXECUTOR_WORKSPACE_ARTIFACT_PASS" ] && echo ok || echo fail)" \
        "got: $ACTUAL"
    SHA="$(sha256sum "$TARGET" | awk '{print $1}')"
    _check "test_05 sha256 computed" "ok" ""
    echo "  sha256: $SHA"
else
    _check "test_05 content matches" "fail" "file not created"
    _check "test_05 sha256 computed" "fail" "file not created"
fi

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo "STATUS: FAILED"
    exit 1
fi
echo "STATUS: PASSED"
exit 0
