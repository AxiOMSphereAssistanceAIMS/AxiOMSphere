# Auditor Session Watcher — Implementation Report

## Files Created
- `ops/scripts/auditor_session_preflight.sh` — runs all three route preflights, writes status JSON
- `ops/scripts/auditor_session_watcher.sh` — called by systemd timer, logs result
- `ops/scripts/auditor_session_status.sh` — human-readable status print with next-action hint
- `ops/systemd/user/aims-auditor-session-watcher.service` — oneshot service unit
- `ops/systemd/user/aims-auditor-session-watcher.timer` — 30s after login, every 10min
- `ops/agents/tests/test_auditor_session_watcher.py` — 12 tests

## Files Updated
- `ops/agents/codex_auditor_adapter.py` — reads fresh status file for fast-path selection
- `ops/agents/tests/test_codex_auditor_adapter.py` — chain-ordering test patched for status file

## Chain Results (this environment)
- Primary Codex: NOT_CONFIGURED (no LLM codex binary)
- Secondary Codex: NOT_CONFIGURED (same)
- Claude Bedrock: AVAILABLE (claude + CLAUDE_CODE_USE_BEDROCK=1)
- Active auditor: claude_bedrock
- Chain status: DEGRADED

## No Interactive Login
- auditor_session_preflight.sh: no `sso login`, `aws login`, `browser` commands
- auditor_session_watcher.sh: delegates only to preflight
- All launchers return AUTH_REQUIRED without hanging

## Systemd Timer
- `aims-auditor-session-watcher.timer` runs after 30s and every 10min
- User-level unit (no sudo)
- Persistent: runs on next login if missed
