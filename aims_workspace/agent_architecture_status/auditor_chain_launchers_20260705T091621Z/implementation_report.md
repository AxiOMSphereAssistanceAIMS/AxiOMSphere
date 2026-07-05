# Auditor Chain Launchers — Implementation Report

## Files Created
- `ops/scripts/load_auditor_env.sh` — env loader, sources .env.auditors.local
- `ops/scripts/codex_auditor_primary.sh` — primary Codex launcher with LLM-auditor validation
- `ops/scripts/codex_auditor_secondary.sh` — secondary Codex launcher (separate profile)
- `ops/scripts/claude_bedrock_auditor.sh` — Claude Code via AWS Bedrock fallback
- `.env.auditors.local.example` — template (committed)
- `.env.auditors.local` — real local env (gitignored, no secrets)

## Files Updated
- `ops/agents/codex_auditor_adapter.py` — three-tier chain priority
- `ops/agents/tests/test_codex_auditor_adapter.py` — 14 tests for chain behavior

## Auditor Chain Priority
1. AIMS_CODEX_AUDITOR_CMD → codex_auditor_primary.sh
2. AIMS_CODEX_AUDITOR_FALLBACK_CMD → codex_auditor_secondary.sh
3. AIMS_CLAUDE_BEDROCK_AUDITOR_CMD → claude_bedrock_auditor.sh
4. SKIPPED — all unavailable

## Preflight Results (this environment)
- Primary Codex: NOT_CONFIGURED (codex binary not found in PATH)
- Secondary Codex: NOT_CONFIGURED (codex binary not found in PATH)
- Claude Bedrock: AVAILABLE (claude binary present, CLAUDE_CODE_USE_BEDROCK=1)

## Wrong Binary Protection
npx codex v0.2.3 is a static site generator. The _validate_binary() function
in each launcher checks for static-site-generator patterns and rejects them.
Tests confirm WRONG_BINARY (exit 11) causes skip to next auditor.

## Auth Safety
No launcher calls aws sso login, opens a browser, or waits for operator input.
AUTH_REQUIRED (exit 10) is returned immediately and propagates to skip.
