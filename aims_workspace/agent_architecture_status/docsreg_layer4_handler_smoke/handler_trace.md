# Layer 4 — Handler-Level Smoke Test Trace

## Call Path Verified

```
ctx.args = ["/path/to/doc.md"]
  → cmd_docsreg(update, ctx)                         docsreg_launch.py:589
    → parse_docsreg_launch_spec(text)                 :600  [REAL]
    → _collect_input_files(request.draft_path)        :608  [REAL]
    → session_root = request.evidence_root / req_id   :623  [patched via DEFAULT_DOCSREG_EVIDENCE_ROOT]
    → review_dir.mkdir(parents=True, exist_ok=True)   :625  [succeeds — tmp_path used]
    → loop.run_in_executor(None, lambda: _run_one_cycle(...))  :678  [REAL]
      → build_structure_auditor_fn(threshold=0.80)    :557  [REAL — spy confirmed]
      → run_docsreg_cycle(..., auditor_fn=auditor_fn) :560  [MOCKED — writes quality_report.json]
    → _record_cycle_learning(result, source_file, ev_root)  [REAL]
    → update.message.reply_text("Processed 1 / Registered 1 / Failed 0")  [AsyncMock]
```

## Patches Applied Per Test

| Test | Patches |
|------|---------|
| H1 (directory batch) | run_docsreg_cycle, aims_paths.workspace_root, DEFAULT_DOCSREG_EVIDENCE_ROOT |
| H2 (auditor wiring) | build_structure_auditor_fn (spy), run_docsreg_cycle, aims_paths.workspace_root, DEFAULT_DOCSREG_EVIDENCE_ROOT |
| H3 (invalid path) | none — returns before mkdir |
| H4 (passing doc quality) | run_docsreg_cycle, aims_paths.workspace_root, DEFAULT_DOCSREG_EVIDENCE_ROOT |
| H5 (failed doc not certified) | run_docsreg_cycle, aims_paths.workspace_root, DEFAULT_DOCSREG_EVIDENCE_ROOT |
| H6 (group/private parity) | run_docsreg_cycle, aims_paths.workspace_root, DEFAULT_DOCSREG_EVIDENCE_ROOT |
| H7 (no args → usage) | none — returns before mkdir |

## Root Cause of Initial Failures

`cmd_docsreg()` at line 623 constructs `session_root = request.evidence_root / request_id`.
`request.evidence_root` defaults to `DEFAULT_DOCSREG_EVIDENCE_ROOT` (module-level), which resolves to
`/data/docsreg_evidence` (from env or workspace_root). This path is not writable in unit test context.

Fix: `patch("ops.omi_telegram.docsreg_launch.DEFAULT_DOCSREG_EVIDENCE_ROOT", tmp_path / "evidence")`
added to all 5 affected tests.

## Test Results

19/19 PASS  |  915/915 DOCSREG regression PASS
