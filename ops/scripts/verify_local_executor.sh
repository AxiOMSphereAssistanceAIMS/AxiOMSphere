#!/usr/bin/env bash
# verify_local_executor.sh
#
# Run executor_test_01 and independently verify the output.
# Returns 0 (PASSED) or 1 (FAILED). Never silently passes.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXECUTOR="$ROOT/ops/scripts/aims_local_executor.py"
TASK_FILE="$ROOT/aims_workspace/test_tasks/executor_test_01.json"
TARGET_FILE="/tmp/aims_executor_test_01.txt"
EXPECTED_CONTENT="AIMS_EXECUTOR_TEST_01_PASS"

PASS=0
FAIL=0

check() {
    local label="$1" result="$2" detail="$3"
    if [ "$result" = "ok" ]; then
        echo "  ✅ $label"
        PASS=$((PASS + 1))
    else
        echo "  ❌ $label — $detail"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== AIMS Local Executor Verification ==="
echo

# 1. Remove stale target file if present
rm -f "$TARGET_FILE"

# 2. Run the executor
echo "[1] Running executor..."
EXECUTOR_OUTPUT="$(python3 "$EXECUTOR" "$TASK_FILE" 2>&1)"
EXECUTOR_EXIT=$?

echo "$EXECUTOR_OUTPUT"
echo

# 3. Check executor exit code
if [ "$EXECUTOR_EXIT" -eq 0 ]; then
    check "Executor returned exit 0" "ok" ""
else
    check "Executor returned exit 0" "fail" "exit=$EXECUTOR_EXIT"
fi

# 4. Check executor reported PASSED
if echo "$EXECUTOR_OUTPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('status') == 'PASSED', f'status={d.get(\"status\")}'
" 2>/dev/null; then
    check "Executor status=PASSED in JSON" "ok" ""
else
    check "Executor status=PASSED in JSON" "fail" "status was not PASSED"
fi

# 5. Independent verification: file exists
if [ -f "$TARGET_FILE" ]; then
    check "File exists: $TARGET_FILE" "ok" ""
else
    check "File exists: $TARGET_FILE" "fail" "file not found after executor run"
fi

# 6. Independent verification: content matches
if [ -f "$TARGET_FILE" ]; then
    ACTUAL_CONTENT="$(cat "$TARGET_FILE" | tr -d '\n')"
    if [ "$ACTUAL_CONTENT" = "$EXPECTED_CONTENT" ]; then
        check "Content matches: $EXPECTED_CONTENT" "ok" ""
    else
        check "Content matches: $EXPECTED_CONTENT" "fail" "actual: $ACTUAL_CONTENT"
    fi
else
    check "Content matches" "fail" "file not found — skipping content check"
fi

# 7. Independent verification: sha256sum
if [ -f "$TARGET_FILE" ]; then
    SHA256="$(sha256sum "$TARGET_FILE" | awk '{print $1}')"
    echo "  sha256: $SHA256"
    check "sha256sum computed" "ok" ""
else
    check "sha256sum computed" "fail" "file not found"
fi

echo
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo "STATUS: FAILED"
    exit 1
fi
echo "STATUS: PASSED"
echo "FILE_CREATED: true"
echo "CONTENT_VERIFIED: true"
exit 0
