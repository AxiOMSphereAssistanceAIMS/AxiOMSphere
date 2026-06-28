#!/usr/bin/env bash
set -euo pipefail

ROOT="${AIMS_ROOT:-$HOME/aims-workspace}"
PROXY_CONTAINER="${SLOT32_PROXY_CONTAINER:-axiomsphere-logi-cc-slot32-proxy}"
PROXY_HEALTH_URL="${SLOT32_PROXY_HEALTH_URL:-http://127.0.0.1:8084/health}"
LOCK_FILE="${SLOT32_CLAUDE_LOCK_FILE:-/tmp/claude_local_slot32.lock}"
TRANSCRIPT_ARCHIVE_ROOT="${SLOT32_TRANSCRIPT_ARCHIVE_ROOT:-$HOME/claude_transcript_archive}"

MODEL="${SLOT32_CLAUDE_MODEL:-axi_omi_sphere:latest}"
API_KEY="${SLOT32_CLAUDE_API_KEY:-aims-local-repair-token}"
BASE_URL="${SLOT32_CLAUDE_BASE_URL:-http://127.0.0.1:8084}"

CHECKPOINT_DIR="$ROOT/aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints"
CHECKPOINT_FILE="$CHECKPOINT_DIR/slot32_auto_checkpoint_latest.md"
DEBUG_FILE="$CHECKPOINT_DIR/slot32_claude_debug_latest.log"
CONTEXT_BUDGET_FILE="$CHECKPOINT_DIR/slot32_context_budget_latest.json"
LAUNCHER_HEALTH_FILE="$CHECKPOINT_DIR/slot32_launcher_health_latest.json"
SESSION_SETTINGS_FILE="$CHECKPOINT_DIR/slot32_session_settings_latest.json"
SESSION_SETTINGS_FILE_ONESHOT="$CHECKPOINT_DIR/slot32_session_settings_oneshot_latest.json"
LOCK_STATUS_FILE="$CHECKPOINT_DIR/slot32_lock_status.json"
TRANSCRIPT_GUARD_FILE="$CHECKPOINT_DIR/transcript_guard_report.json"
LAUNCHER_HEALTH_ALIAS_FILE="$CHECKPOINT_DIR/launcher_health.json"
CONTEXT_BUDGET_ALIAS_FILE="$CHECKPOINT_DIR/context_budget.json"
COMPACT_INTERVAL="${SLOT32_COMPACT_INTERVAL_S:-60}"
PROJECT_TRANSCRIPTS_DIR="$HOME/.claude/projects/-home-axi-omi-sphere-aims-workspace"
USER_MEMORY_FILE="$HOME/.claude/projects/-home-axi-omi-sphere-aims-workspace/memory/MEMORY.md"
PROJECT_CLAUDE_MD="$ROOT/CLAUDE.md"
PROJECT_SETTINGS_FILE="$ROOT/.claude/settings.local.json"
USER_SETTINGS_FILE="$HOME/.claude/settings.json"

archive_large_transcripts() {
    mkdir -p "$CHECKPOINT_DIR" "$TRANSCRIPT_ARCHIVE_ROOT"
    python3 - <<'PY'
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

project_root = Path("/home/axi_omi_sphere/.claude/projects/-home-axi-omi-sphere-aims-workspace")
archive_root = Path(os.environ.get("SLOT32_TRANSCRIPT_ARCHIVE_ROOT", "/home/axi_omi_sphere/claude_transcript_archive"))
archive_root.mkdir(parents=True, exist_ok=True)

archived = []
warned = []
for path in sorted(project_root.glob("*.jsonl")):
    size = path.stat().st_size
    if size > 30_000_000:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest_dir = archive_root / stamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest_dir / path.name))
        archived.append({"path": str(path), "size_bytes": size, "archive_dir": str(dest_dir)})
    elif size >= 24_000_000:
        warned.append({"path": str(path), "size_bytes": size, "action": "force_checkpoint_new_session"})

payload = {"archived": archived, "warned": warned}
out = Path("/home/axi_omi_sphere/aims-workspace/aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/transcript_guard_report.json")
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

write_session_settings() {
    mkdir -p "$CHECKPOINT_DIR"
    cat > "$SESSION_SETTINGS_FILE" <<'JSON'
{
  "autoMemoryEnabled": false,
  "autoCompactEnabled": false,
  "awaySummaryEnabled": false,
  "showThinkingSummaries": false,
  "outputStyle": "default",
  "prefersReducedMotion": true
}
JSON
    cat > "$SESSION_SETTINGS_FILE_ONESHOT" <<'JSON'
{
  "autoMemoryEnabled": false,
  "autoCompactEnabled": false,
  "awaySummaryEnabled": false,
  "showThinkingSummaries": false,
  "outputStyle": "default",
  "prefersReducedMotion": true,
  "enabledPlugins": {
    "claude-mem@thedotmack": true
  }
}
JSON
}

write_context_budget() {
    mkdir -p "$CHECKPOINT_DIR"
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

root = Path("/home/axi_omi_sphere/aims-workspace")
project_claude = root / "CLAUDE.md"
project_settings = root / ".claude/settings.local.json"
user_settings = Path.home() / ".claude/settings.json"
memory_md = Path.home() / ".claude/projects/-home-axi-omi-sphere-aims-workspace/memory/MEMORY.md"
history = Path.home() / ".claude/history.jsonl"
debug = root / "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_claude_debug_latest.log"
checkpoint = root / "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_auto_checkpoint_latest.md"
transcripts_dir = Path.home() / ".claude/projects/-home-axi-omi-sphere-aims-workspace"
archive_root = Path(os.environ.get("SLOT32_TRANSCRIPT_ARCHIVE_ROOT", "/home/axi_omi_sphere/claude_transcript_archive"))

def size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0

transcripts = []
for path in sorted(transcripts_dir.glob("*.jsonl")):
    transcripts.append({"path": str(path), "size_bytes": size_of(path)})

budget = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "project_claude_md": {"path": str(project_claude), "size_bytes": size_of(project_claude)},
    "project_settings": {"path": str(project_settings), "size_bytes": size_of(project_settings)},
    "user_settings": {"path": str(user_settings), "size_bytes": size_of(user_settings)},
    "memory_md": {"path": str(memory_md), "size_bytes": size_of(memory_md)},
    "history_jsonl": {"path": str(history), "size_bytes": size_of(history)},
    "checkpoint": {"path": str(checkpoint), "size_bytes": size_of(checkpoint)},
    "debug_file": {"path": str(debug), "size_bytes": size_of(debug)},
    "project_transcripts": transcripts,
    "archive_root": str(archive_root),
    "request_risk": "bounded" if sum(item["size_bytes"] for item in transcripts) < 24_000_000 else "elevated",
}

out = root / "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_context_budget_latest.json"
out.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
alias = root / "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/context_budget.json"
alias.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

write_launcher_health() {
    mkdir -p "$CHECKPOINT_DIR"
    python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

health = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "launcher": "claude_local_slot32.sh",
    "model": "axi_omi_sphere:latest",
    "proxy_health_url": "http://127.0.0.1:8084/health",
    "context_budget_file": "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_context_budget_latest.json",
    "checkpoint_file": "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_auto_checkpoint_latest.md",
    "session_settings_file": "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_session_settings_latest.json",
    "lock_status_file": "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_lock_status.json",
    "transcript_guard_file": "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/transcript_guard_report.json",
    "disable_compact": True,
}
out = Path("/home/axi_omi_sphere/aims-workspace/aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_launcher_health_latest.json")
out.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
alias = Path("/home/axi_omi_sphere/aims-workspace/aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/launcher_health.json")
alias.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

write_lock_status() {
    reason="${1:-preflight}"
    mkdir -p "$CHECKPOINT_DIR"
    python3 - "$reason" <<'PY'
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

reason = sys.argv[1]
lock_path = Path(os.environ.get("SLOT32_CLAUDE_LOCK_FILE", "/tmp/claude_local_slot32.lock"))
status = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "reason": reason,
    "lock_file": str(lock_path),
    "pid": os.getpid(),
    "ppid": os.getppid(),
    "busy": None,
    "compact_skipped_reason": None,
}
try:
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status["busy"] = False
        status["compact_skipped_reason"] = "none"
        fcntl.flock(fd, fcntl.LOCK_UN)
    except BlockingIOError:
        status["busy"] = True
        status["compact_skipped_reason"] = "slot32_busy"
    finally:
        os.close(fd)
except Exception as exc:
    status["busy"] = True
    status["compact_skipped_reason"] = f"lock_probe_error:{type(exc).__name__}"
    status["error"] = repr(exc)

out = Path("/home/axi_omi_sphere/aims-workspace/aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_lock_status.json")
out.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

write_checkpoint() {
    reason="${1:-periodic}"
    mkdir -p "$CHECKPOINT_DIR"

    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git_branch="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
    git_status="$(git -C "$ROOT" status --short 2>/dev/null | head -40 || true)"
    git_status_count="$(git -C "$ROOT" status --short 2>/dev/null | wc -l | tr -d ' ' || true)"
    changed_files="$(git -C "$ROOT" diff --name-only 2>/dev/null | head -60 || true)"
    changed_files_count="$(git -C "$ROOT" diff --name-only 2>/dev/null | wc -l | tr -d ' ' || true)"
    proxy_health="$(curl -sS --max-time 5 "$PROXY_HEALTH_URL" 2>/dev/null || true)"
    claude_processes="$(ps -ef | grep -E 'claude|claude_local_slot32' | grep -v grep | head -20 || true)"

    debug_signals=""
    if [ -f "$DEBUG_FILE" ]; then
        debug_signals="$(tail -120 "$DEBUG_FILE" | grep -E 'API error|Slow first byte|Request too large|502|504|413|429|compact' || true)"
    fi

    {
        echo "# Slot32 Claude Code Auto Checkpoint"
        echo
        echo "Time UTC: $now"
        echo "Reason: $reason"
        echo
        echo "Route: Claude Code CLI -> 127.0.0.1:8084 -> slot32 -> axi_omi_sphere:latest"
        echo
        echo "Rules:"
        echo "- Do not resume oversized old sessions."
        echo "- Do not paste full files or long logs into Claude Code UI."
        echo "- Use file paths and short excerpts."
        echo "- Do not fan out Claude Code internal subagents through slot32."
        echo "- Continue in micro-steps."
        echo
        echo "Git branch:"
        echo "${git_branch:-unknown}"
        echo
        echo "Git status:"
        echo "${git_status:-clean}"
        echo "Git status count:"
        echo "${git_status_count:-0}"
        echo
        echo "Changed files:"
        echo "${changed_files:-none}"
        echo "Changed files count:"
        echo "${changed_files_count:-0}"
        echo
        echo "Proxy health:"
        echo "${proxy_health:-unknown}"
        echo
        echo "Claude processes:"
        echo "${claude_processes:-none}"
        echo
        echo "Recent debug signals:"
        echo "${debug_signals:-none}"
        echo
        echo "Continuation instruction:"
        echo "Read this checkpoint and continue from it:"
        echo "aims_workspace/agent_architecture_status/claude_code_slot32_session_checkpoints/slot32_auto_checkpoint_latest.md"
        echo
    } > "$CHECKPOINT_FILE"
}

auto_compact_loop() {
    while true; do
        write_lock_status "background_compacter"
        write_checkpoint "periodic"
        sleep "$COMPACT_INTERVAL"
    done
}

if [ "${1:-}" = "--auto-compact-loop" ]; then
    cd "$ROOT"
    auto_compact_loop
    exit 0
fi

if [ "${1:-}" = "--oneshot" ]; then
    ONESHOT_MODE=1
    shift
    ONE_SHOT_PROMPT="${1:-}"
    shift || true
else
    ONESHOT_MODE=0
    ONE_SHOT_PROMPT=""
fi

cd "$ROOT"

archive_large_transcripts
write_session_settings
write_lock_status "preflight"
write_checkpoint "preflight"
write_context_budget
write_launcher_health

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "ERROR: another Claude local slot32 session is already running." >&2
    echo "Check: ps -ef | grep -E 'claude|claude_local_slot32' | grep -v grep" >&2
    exit 75
fi
write_lock_status "foreground_acquired"

echo "[slot32-wrapper] checking proxy: $PROXY_CONTAINER"

if command -v docker >/dev/null 2>&1; then
    if docker ps -a --format '{{.Names}}' | grep -qx "$PROXY_CONTAINER"; then
        if ! docker ps --format '{{.Names}}' | grep -qx "$PROXY_CONTAINER"; then
            echo "[slot32-wrapper] starting stopped proxy container: $PROXY_CONTAINER"
            docker start "$PROXY_CONTAINER" >/dev/null
        fi
    else
        echo "[slot32-wrapper] WARN: proxy container not found: $PROXY_CONTAINER" >&2
    fi
fi

echo "[slot32-wrapper] waiting for 8084 health..."

ok=0
for i in $(seq 1 20); do
    if curl -fsS --max-time 3 "$PROXY_HEALTH_URL" >/tmp/slot32_proxy_health.json 2>/dev/null; then
        ok=1
        break
    fi
    sleep 1
done

if [ "$ok" != "1" ]; then
    echo "ERROR: slot32 proxy is not healthy at $PROXY_HEALTH_URL" >&2
    echo "--- docker status ---" >&2
    docker ps --filter "name=$PROXY_CONTAINER" 2>/dev/null >&2 || true
    echo "--- last proxy logs ---" >&2
    docker logs --tail=80 "$PROXY_CONTAINER" 2>&1 >&2 || true
    exit 76
fi

echo "[slot32-wrapper] proxy health OK:"
cat /tmp/slot32_proxy_health.json
echo

mkdir -p "$CHECKPOINT_DIR"

write_checkpoint "before_start"

"$0" --auto-compact-loop >/tmp/slot32_auto_compacter.log 2>&1 &
COMPACT_PID="$!"

cleanup() {
    kill "$COMPACT_PID" 2>/dev/null || true
    write_checkpoint "on_exit"
}
trap cleanup EXIT INT TERM

SESSION_SETTINGS_IN_USE="$SESSION_SETTINGS_FILE"
if [ "$ONESHOT_MODE" = "1" ]; then
    SESSION_SETTINGS_IN_USE="$SESSION_SETTINGS_FILE_ONESHOT"
fi

claude_cmd=(
    claude
    --model "$MODEL"
    --settings "$SESSION_SETTINGS_IN_USE"
    --exclude-dynamic-system-prompt-sections
    --debug api
    --debug-file "$DEBUG_FILE"
    --append-system-prompt "You are local AIMS slot32. Keep context bounded. Split large tasks into phases. Do not paste large files or logs into chat. Write large outputs to files. Use claude-mem only through bounded summaries plus file paths. Never inject raw memory dumps or huge logs into the main request. Before context grows too large, write a checkpoint and continue from a clean session."
)
if [ "$ONESHOT_MODE" = "1" ]; then
    claude_cmd+=(-p "$ONE_SHOT_PROMPT")
fi

env_cmd=(
    env
    -u ANTHROPIC_CUSTOM_HEADERS
    -u ANTHROPIC_AUTH_TOKEN
    -u CLAUDE_CODE_OAUTH_TOKEN
    ANTHROPIC_BASE_URL="$BASE_URL"
    ANTHROPIC_API_KEY="$API_KEY"
    ANTHROPIC_MODEL="$MODEL"
    CLAUDE_CODE_ENABLE_TELEMETRY=0
    DISABLE_AUTOUPDATER=1
    DISABLE_UPDATES=1
    DISABLE_COMPACT=1
    CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=0
    CLAUDE_MEM_CONTEXT_OBSERVATIONS=10
    CLAUDE_MEM_CONTEXT_SESSION_COUNT=3
    CLAUDE_MEM_CONTEXT_FULL_COUNT=1
)

if [ "$ONESHOT_MODE" = "1" ]; then
    env_cmd+=(
        CLAUDE_CODE_SIMPLE=1
        CLAUDE_CODE_DISABLE_CLAUDE_MDS=1
    )
fi

exec "${env_cmd[@]}" \
    "${claude_cmd[@]}" \
    "$@"
