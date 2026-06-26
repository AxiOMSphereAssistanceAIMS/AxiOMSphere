#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/../.." && pwd)"

SERVICE="${DOCSREG_COMPOSE_SERVICE:-aims-worker}"

if ! docker compose config --services | grep -qx "$SERVICE"; then
  echo "DOCSREG_COMPOSE_SERVICE_NOT_FOUND: $SERVICE" >&2
  echo "Available services:" >&2
  docker compose config --services >&2
  exit 2
fi

export DOCSREG_RUNTIME_MODE="compose_network"
export DOCSREG_EXTRACTOR_BACKEND="markitdown"
export AIMS_STANDARDS_DB_PATH="/data/aims_registry.db"
export AIMS_REDIS_URL="redis://aims-redis:6379/0"
export REDIS_URL="redis://aims-redis:6379/0"
export DOCSREG_REDIS_URL="redis://aims-redis:6379/0"

compose_pythonpath="/home/axi_omi_sphere/aims-workspace:/ops:/data"
if [[ -n "${PYTHONPATH:-}" ]]; then
  compose_pythonpath="$compose_pythonpath:$PYTHONPATH"
fi

cd "$root"
exec docker compose run --rm -T \
  -w /home/axi_omi_sphere/aims-workspace \
  -e DOCSREG_RUNTIME_MODE="$DOCSREG_RUNTIME_MODE" \
  -e DOCSREG_EXTRACTOR_BACKEND="$DOCSREG_EXTRACTOR_BACKEND" \
  -e AIMS_REDIS_URL="$AIMS_REDIS_URL" \
  -e REDIS_URL="$REDIS_URL" \
  -e DOCSREG_REDIS_URL="$DOCSREG_REDIS_URL" \
  -e PYTHONPATH="$compose_pythonpath" \
  "$SERVICE" \
  "$@"
