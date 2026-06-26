#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "DEPRECATED: use ops/scripts/run_docsreg_in_compose.sh" >&2
exec "$script_dir/run_docsreg_in_compose.sh" "$@"
