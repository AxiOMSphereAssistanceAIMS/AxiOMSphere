#!/usr/bin/env bash
set -euo pipefail

ROOT="${AIMS_ROOT:-$HOME/aims-workspace}"
OUTPUT_ROOT="aims_workspace/learning_capture"
AGENT_NAME=""
TARGET_SLOT=""
TASK_PROMPT=""
EXPECTED_DELIVERABLES=()

usage() {
    cat <<'EOF'
Usage:
  ops/scripts/run_agent_logged_and_captured.sh \
    --agent-name claude-code-local \
    --target-slot slot32 \
    --task-prompt /path/to/task.md \
    [--expected-deliverables path] \
    [--output-root aims_workspace/learning_capture] \
    -- command args...
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --agent-name)
            AGENT_NAME="${2:-}"
            shift 2
            ;;
        --target-slot)
            TARGET_SLOT="${2:-}"
            shift 2
            ;;
        --task-prompt)
            TASK_PROMPT="${2:-}"
            shift 2
            ;;
        --expected-deliverables)
            EXPECTED_DELIVERABLES+=("${2:-}")
            shift 2
            ;;
        --output-root)
            OUTPUT_ROOT="${2:-}"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ -z "$AGENT_NAME" ] || [ -z "$TARGET_SLOT" ] || [ -z "$TASK_PROMPT" ] || [ "$#" -eq 0 ]; then
    usage >&2
    exit 2
fi

cd "$ROOT"

SESSION_ID="$(date -u +%Y%m%dT%H%M%SZ)_${AGENT_NAME}_${TARGET_SLOT}_$$"
SESSION_DIR="$OUTPUT_ROOT/sessions/$SESSION_ID"
mkdir -p "$SESSION_DIR"

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
SESSION_LOG="$SESSION_DIR/session.log"
START_STATUS="$SESSION_DIR/git_status_start.txt"
END_STATUS="$SESSION_DIR/git_status_end.txt"
DIFF_PATH="$SESSION_DIR/git_diff.patch"
METADATA_PATH="$SESSION_DIR/wrapper_metadata.json"

git status --short > "$START_STATUS" 2>&1 || true

set +e
if command -v script >/dev/null 2>&1; then
    COMMAND_STRING="$(printf ' %q' "$@")"
    script -q -e -c "$COMMAND_STRING" "$SESSION_LOG"
    EXIT_CODE=$?
else
    "$@" > "$SESSION_LOG" 2>&1
    EXIT_CODE=$?
fi
set -e

FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git status --short > "$END_STATUS" 2>&1 || true
git diff > "$DIFF_PATH" 2>&1 || true

python3 - "$METADATA_PATH" "$AGENT_NAME" "$TARGET_SLOT" "$TASK_PROMPT" "$STARTED_AT" "$FINISHED_AT" "$EXIT_CODE" "$SESSION_LOG" "$START_STATUS" "$END_STATUS" "$DIFF_PATH" "$@" <<'PY'
import json
import sys
from pathlib import Path

metadata_path, agent, slot, prompt, started, finished, exit_code, log_path, start_status, end_status, diff_path, *command = sys.argv[1:]
data = {
    "schema_version": "learning_capture_wrapper_v1",
    "agent_name": agent,
    "target_slot": slot,
    "task_prompt": prompt,
    "command": command,
    "started_at_utc": started,
    "finished_at_utc": finished,
    "exit_code": int(exit_code),
    "session_log_path": log_path,
    "start_status_path": start_status,
    "end_status_path": end_status,
    "diff_path": diff_path,
}
Path(metadata_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
PY

CAPTURE_ARGS=(
    python3 ops/scripts/capture_agent_action_case.py
    --agent-name "$AGENT_NAME"
    --target-slot "$TARGET_SLOT"
    --task-prompt-file "$TASK_PROMPT"
    --terminal-log "$SESSION_LOG"
    --evidence-root "$SESSION_DIR"
    --output-root "$OUTPUT_ROOT"
)

for deliverable in "${EXPECTED_DELIVERABLES[@]}"; do
    CAPTURE_ARGS+=(--expected-deliverables "$deliverable")
done

"${CAPTURE_ARGS[@]}" > "$SESSION_DIR/capture_result.json" 2> "$SESSION_DIR/capture_result.stderr" || true

exit "$EXIT_CODE"
