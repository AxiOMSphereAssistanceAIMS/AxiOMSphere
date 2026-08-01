#!/usr/bin/env bash
set -u

ROOT="${AIMS_PROJECT_ROOT:-/home/axi_omi_sphere/aims-workspace}"
cd "$ROOT" || exit 2

export AIMS_PROJECT_ROOT="$ROOT"
export PYTHONPATH="${PYTHONPATH:-ops}"
export REPAIRMAN_PATCH_PHASE2=true
export REPAIRMAN_AUTONOMY_LEVEL=3
export REPAIRMAN_APPLY_MODE=auto_safe
export REPAIRMAN_AUDITOR_BACKEND=bedrock_claude
export REPAIRMAN_AUDITOR_REQUIRED=true
export REPAIRMAN_AUDITOR_REAL_BEDROCK=1
export REPAIRMAN_LEARNING_REGISTRATION=true
export REPAIRMAN_REGISTER_FAILED_CASES=true
export REPAIRMAN_REGISTER_AUDITOR_FEEDBACK=true

# Autonomous mutation is fail-closed when governance is required.  The
# preflight runs before any Logi/Repairman child process is started.
if [ "${AIMS_REQUIRE_GOVERNED_MUTATION:-0}" = "1" ] || [ -f "/tmp/aims-governance-mandatory" ]; then
  python3 - "$ROOT" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ops.self_learning.governed_mutation_preflight import mutation_preflight
root = Path(sys.argv[1]).resolve()
result = mutation_preflight(
    root,
    task_id=os.environ.get("REPAIRMAN_GOVERNANCE_TASK_ID", "missing-task-id"),
    target_branch=os.environ.get("REPAIRMAN_GOVERNANCE_BRANCH", "main"),
    worktree_path=Path(os.environ.get("REPAIRMAN_GOVERNANCE_WORKTREE", str(root))),
    lease_path=Path(os.environ.get("REPAIRMAN_GOVERNANCE_LEASE", str(root / "aims_workspace/agent_architecture_status/component_lease_registry.jsonl"))),
    owned_files=[item for item in os.environ.get("REPAIRMAN_GOVERNANCE_FILES", "").split(":") if item],
)
print(result)
raise SystemExit(0 if result["allowed"] else 78)
PY
  [ "$?" -eq 0 ] || exit 78
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="$ROOT/aims_workspace/agent_architecture_status/repairman_audit_window_autonomy"
mkdir -p "$REPORT_DIR"

LOGI_OUT="$(mktemp)"
LOGI_ERR="$(mktemp)"
BEDROCK_OUT="$(mktemp)"
BEDROCK_ERR="$(mktemp)"
SMOKE_OUT="$(mktemp)"
SMOKE_ERR="$(mktemp)"

logi_rc=0
timeout 300 bash ops/scripts/Logi_CC_start.sh --json >"$LOGI_OUT" 2>"$LOGI_ERR" || logi_rc=$?

bedrock_rc=0
if [ "${REPAIRMAN_AUDITOR_REAL_BEDROCK:-}" = "1" ] && [ -f "ops/evals/bedrock_auditor_smoke_gate.py" ]; then
  timeout "${REPAIRMAN_AUDITOR_TIMEOUT_S:-220}" env PYTHONPATH=ops python3 ops/evals/bedrock_auditor_smoke_gate.py >"$BEDROCK_OUT" 2>"$BEDROCK_ERR" || bedrock_rc=$?
else
  bedrock_rc=99
fi

smoke_rc=0
timeout 180 env PYTHONPATH=ops python3 ops/evals/repairman_audit_window_autonomy_smoke.py >"$SMOKE_OUT" 2>"$SMOKE_ERR" || smoke_rc=$?

python3 - "$STAMP" "$REPORT_DIR" "$logi_rc" "$bedrock_rc" "$smoke_rc" "$LOGI_OUT" "$BEDROCK_OUT" "$SMOKE_OUT" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

stamp, report_dir, logi_rc, bedrock_rc, smoke_rc, logi_out, bedrock_out, smoke_out = sys.argv[1:9]
logi_text = Path(logi_out).read_text(encoding='utf-8', errors='replace')
bedrock_text = Path(bedrock_out).read_text(encoding='utf-8', errors='replace')
smoke_text = Path(smoke_out).read_text(encoding='utf-8', errors='replace')

logi_payload = {}
try:
    logi_payload = json.loads(logi_text.strip()) if logi_text.strip().startswith('{') else {}
except Exception:
    logi_payload = {}

logi_ok = int(logi_rc) == 0 and bool(logi_payload.get('ok', False))
bedrock_payload = {}
try:
    bedrock_payload = json.loads(bedrock_text.strip()) if bedrock_text.strip().startswith('{') else {}
except Exception:
    bedrock_payload = {}
bedrock_ok = int(bedrock_rc) == 0 and (
    'BEDROCK_AUDITOR_SMOKE_PASS' in bedrock_text
    or bedrock_payload.get('status') == 'PASS'
)
smoke_ok = int(smoke_rc) == 0 and 'REPAIRMAN_AUDIT_WINDOW_AUTONOMY_SMOKE_PASS' in smoke_text
payload = {
    'ok': logi_ok and bedrock_ok and smoke_ok,
    'audit_window_mode': True,
    'created_at_utc': stamp,
    'autonomy_level': int(os.environ.get('REPAIRMAN_AUTONOMY_LEVEL', '3')),
    'apply_mode': os.environ.get('REPAIRMAN_APPLY_MODE', ''),
    'auditor_backend': os.environ.get('REPAIRMAN_AUDITOR_BACKEND', ''),
    'auditor_required': os.environ.get('REPAIRMAN_AUDITOR_REQUIRED', ''),
    'real_bedrock_enabled': os.environ.get('REPAIRMAN_AUDITOR_REAL_BEDROCK', '') == '1',
    'learning_registration': os.environ.get('REPAIRMAN_LEARNING_REGISTRATION', ''),
    'logi_cc_bridge_ok': logi_ok,
    'bedrock_auditor_smoke_ok': bedrock_ok,
    'repairman_audit_window_smoke_ok': smoke_ok,
    'ready_for_auto_safe_apply': logi_ok and bedrock_ok and smoke_ok,
    'bedrock_unavailable_blocks_apply': not bedrock_ok,
    'sentinels': {
        'bedrock': 'BEDROCK_AUDITOR_SMOKE_PASS' in bedrock_text or bedrock_payload.get('status') == 'PASS',
        'repairman_audit_window': 'REPAIRMAN_AUDIT_WINDOW_AUTONOMY_SMOKE_PASS' in smoke_text,
    },
    'evidence_paths': {
        'report_json': str(Path(report_dir) / f'launcher_{stamp}.json'),
        'report_md': str(Path(report_dir) / f'launcher_{stamp}.md'),
    },
}
Path(report_dir).mkdir(parents=True, exist_ok=True)
(Path(report_dir) / f'launcher_{stamp}.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
(Path(report_dir) / f'launcher_{stamp}.md').write_text(
    '# Repairman Audit Autonomy Launcher\n\n'
    f"- ok: {payload['ok']}\n"
    f"- autonomy_level: {payload['autonomy_level']}\n"
    f"- apply_mode: {payload['apply_mode']}\n"
    f"- auditor_backend: {payload['auditor_backend']}\n"
    f"- real_bedrock_enabled: {payload['real_bedrock_enabled']}\n"
    f"- logi_cc_bridge_ok: {payload['logi_cc_bridge_ok']}\n"
    f"- bedrock_auditor_smoke_ok: {payload['bedrock_auditor_smoke_ok']}\n"
    f"- repairman_audit_window_smoke_ok: {payload['repairman_audit_window_smoke_ok']}\n",
    encoding='utf-8',
)
print(json.dumps(payload, indent=2, ensure_ascii=False))
raise SystemExit(0 if payload['ok'] else 1)
PY

rc=$?
rm -f "$LOGI_OUT" "$LOGI_ERR" "$BEDROCK_OUT" "$BEDROCK_ERR" "$SMOKE_OUT" "$SMOKE_ERR"
exit "$rc"
