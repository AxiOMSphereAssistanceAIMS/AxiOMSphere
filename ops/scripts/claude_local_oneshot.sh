#!/usr/bin/env bash
set -euo pipefail

ROOT="${AIMS_ROOT:-$HOME/aims-workspace}"
if [ $# -lt 1 ]; then
  echo "usage: $0 <prompt> [extra claude args...]" >&2
  exit 2
fi

cd "$ROOT"
exec ops/scripts/claude_local_slot32.sh --oneshot "$@" --dangerously-skip-permissions
