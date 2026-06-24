# Layer 5 — Live DOCSREG Runtime Integration Smoke

**Status:** PASS  
**Date:** 2026-06-24 08:11 +04  
**Tests:** 5/5 PASS | Regression: 920/920 PASS

## What was tested

Live end-to-end execution of `run_docsreg_cycle()` with:
- Real production auditor (`build_structure_auditor_fn(threshold=0.80)`)
- Real Redis (container `axiomsphere-aims-redis` at `172.18.0.26:6379`)
- Real `quality_report.json` written by `task_quality_validated`
- Real learning writes via `record_knowledge_source`
- Source document: `ISO 55000 Asset Managment Policy.pdf` (99 KB)
- **NO mock of `run_docsreg_cycle`**

## Test Results

| ID | Test | Result |
|----|------|--------|
| L5-1 | `test_live_runtime_smoke_creates_master_package` | PASS |
| L5-2 | `test_live_runtime_smoke_writes_quality_report` | PASS |
| L5-3 | `test_live_runtime_smoke_uses_real_auditor` | PASS |
| L5-4 | `test_live_runtime_smoke_writes_learning_entry` | PASS |
| L5-5 | `test_live_runtime_smoke_does_not_certify_failed_doc` | PASS |

## Production Fix Applied

**File:** `ops/docsreg/docsreg_document_type_cycle.py`  
**Function:** `_run_single_cycle()`

**Root cause:** `task_quality_validated` writes `quality_report.json` before `run_claude_code_audit()` executes. The audit status (`COMPONENT_FAIL_REPAIRABLE` or `COMPONENT_PASS`) was determined but never written back to `quality_report.json`. So `record_knowledge_source` always read `audit_status=UNKNOWN` → `real_auditor_used=False`.

**Fix:** After `audit_status = str(audit.get("status", ...))` resolves, update `quality_report.json` with `{"audit_status": audit_status}`.

**Effect:** `record_knowledge_source` now correctly sets `real_auditor_used=True` when the production auditor is used (status is in `RECOGNISED_AUDIT_STATUSES`).

## Redis Resolution

Redis is not published to `localhost:6379` — it lives only in the Docker network. The test module resolves it at import time:
1. Probe `localhost:6379` (fast path for native Redis)
2. Fall back to `docker inspect axiomsphere-aims-redis` → container IP `172.18.0.26`

## Design Note: evidence_root == draft_path.parent

`task_quality_validated` writes `quality_report.json` to `draft_path.parent`.  
`_record_cycle_learning` reads `quality_report.json` from `evidence_root`.  
These must be the same directory — the source PDF is copied into `evidence_root` so that `draft_path.parent IS evidence_root`.
