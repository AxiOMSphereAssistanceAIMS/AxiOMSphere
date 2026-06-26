# Slot32 Training Assessment: DOCSREG MarkItDown Backend

Created: 2026-06-26T09:40:48+04:00

Verdict: `TASK_NOT_IMPLEMENTED_AS_REQUESTED`

## Requested Scope

The actual task was narrow:

- Add Microsoft MarkItDown as an additional extraction backend for DOCSREG.
- Keep MarkItDown output as raw extraction only.
- Preserve the existing DOCSREG flow: master generation, validation, retention, learning, and optional Qdrant/RAG.
- Do not rebuild DOCSREG.

The expected architecture was:

```text
source file
-> DOCSREG inventory
-> extractor backend: current extractor OR markitdown
-> raw_extracted_text.md
-> existing DOCSREG master generation
-> quality_report.json
-> registration package
-> learning loop
-> optional Qdrant/RAG
```

## State Before My Evidence Edits

Target backend implementation was not present.

Missing files:

- `ops/docsreg/extraction/extraction_models.py`
- `ops/docsreg/extraction/markitdown_adapter.py`
- `ops/tests/test_docsreg_markitdown_adapter.py`
- `ops/tests/test_docsreg_markitdown_pipeline_integration.py`
- `ops/tests/fixtures/docsreg_markitdown/sample.md`
- `ops/tests/fixtures/docsreg_markitdown/sample.txt`

Missing wiring:

- `DOCSREG_EXTRACTOR_BACKEND=auto|legacy|markitdown`
- MarkItDown adapter call from the DOCSREG extraction boundary
- `extraction_report.json` artifact writing
- optional `docsreg-extract = ["markitdown"]` dependency extra

Dependency state:

- Default `python`: `markitdown` not importable.
- `.venv-markitdown`: `markitdown` importable.
- `pyproject.toml`: already dirty before this assessment, but only with an unrelated `pypdf` dependency diff; no MarkItDown extra was present.

Existing partial infrastructure:

- `raw_extracted_text.md` already exists in `RegistrationPackageBuilder`, but this does not prove MarkItDown populates it.
- `ops/docsreg/docsreg_composite_quality_gate.py` already protects against word-count-only auto-pass.
- DOCSREG archive extraction exists.
- Older MarkItDown usage exists in `ops/docagent`, `ops/docs_pipeline`, and the MCP server, but not as the requested DOCSREG extraction backend.

## What My Checks Changed

I did not change production source code.

I created evidence-only reports:

- `aims_workspace/agent_architecture_status/markitdown_integration_p0_preflight/`
- `aims_workspace/agent_architecture_status/markitdown_integration_inventory/`
- `aims_workspace/agent_architecture_status/docsreg_markitdown_backend_verification_20260626/`
- `aims_workspace/agent_architecture_status/docsreg_markitdown_slot32_training_assessment_20260626/`

## What Slot32 Missed

The implementation appears to have stopped at smoke/inventory-level evidence, not feature completion.

Observed gaps:

- Treated MarkItDown availability or smoke evidence as if it satisfied backend integration.
- Did not create the requested DOCSREG extraction adapter package.
- Did not create `ExtractionResult` for the requested adapter API.
- Did not implement `extract_with_markitdown(source_path: Path)`.
- Did not add `DOCSREG_EXTRACTOR_BACKEND` selection.
- Did not connect MarkItDown at the existing `_extract_text` or equivalent extraction boundary.
- Did not write `extraction_report.json`.
- Did not add the optional dependency extra.
- Did not add requested tests or fixtures.
- Did not verify default Python and `.venv-markitdown` separately before declaring readiness.
- Did not prove that MarkItDown raw output cannot be certified without the master package.
- Did not prove archive members can use MarkItDown after extraction.
- Did not run the requested focused tests because the files did not exist.
- Did not run the limited production-style smoke because the backend was absent.

## Key Training Lessons

Smoke evidence is not implementation evidence.

If the task asks for an "additional backend", the minimum implementation is:

- dependency boundary
- adapter API
- backend selection
- artifact writing
- integration at the existing boundary
- focused tests
- regression or explicit non-run rationale

Existing library usage elsewhere in the repo does not satisfy a specific integration request. In this case, MarkItDown in `ops/docagent` or `ops/docs_pipeline` is not the same as a DOCSREG extraction backend.

Existing `raw_extracted_text.md` is not enough. The question is whether the requested backend writes it, reports extraction metadata, and then hands off to the existing master-generation flow.

Do not expand scope. The user's task was DOCSREG-only extraction. The broader DOCGEN source-normalization plan was a different architecture and should not be substituted for this task.

## Repairman Skill Candidate

Skill name: `docsreg-markitdown-backend-audit`

Purpose: verify whether a DOCSREG MarkItDown backend is actually installed.

Checks:

```bash
test -f ops/docsreg/extraction/extraction_models.py
test -f ops/docsreg/extraction/markitdown_adapter.py
test -f ops/tests/test_docsreg_markitdown_adapter.py
test -f ops/tests/test_docsreg_markitdown_pipeline_integration.py
rg -n "DOCSREG_EXTRACTOR_BACKEND|extract_with_markitdown|extraction_report" ops/docsreg ops/tests
python - <<'PY'
try:
    import markitdown
    print("MARKITDOWN_AVAILABLE")
except Exception as exc:
    print("MARKITDOWN_NOT_AVAILABLE", repr(exc))
PY
```

Pass criteria:

- Adapter files exist.
- Default test interpreter can import MarkItDown, or tests skip cleanly.
- `DOCSREG_EXTRACTOR_BACKEND` exists.
- MarkItDown path writes `raw_extracted_text.md` and `extraction_report.json`.
- Raw output is not certified without `master_document.md` and quality gates.
- Requested focused tests pass.

Stop condition:

- If requested tests are missing, do not report completion.

## Logi Skill Candidate

Skill name: `implementation-evidence-classifier`

Purpose: prevent agents from confusing smoke, inventory, implementation, tests, and rollout.

Evidence levels:

- Level 0: dependency/import smoke
- Level 1: code files present
- Level 2: unit tests present and pass
- Level 3: integration path exercised
- Level 4: regression run
- Level 5: limited production-style run
- Level 6: commit with evidence package

For this task, the state was Level 0 to partial Level 1 only. It should not be reported as implemented.

## Correct Next Implementation Slice

The next coding slice should be small:

1. Add `ops/docsreg/extraction/extraction_models.py`.
2. Add `ops/docsreg/extraction/markitdown_adapter.py`.
3. Add optional dependency extra in `pyproject.toml` without touching core runtime.
4. Add fixtures and adapter tests.
5. Compile and run only adapter tests.

Only after that should the DOCSREG extraction boundary be patched.
