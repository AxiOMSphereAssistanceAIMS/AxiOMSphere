# Slot32 MarkItDown Post-Activation Training Case

Date: 2026-06-26
Scope: DOCSREG MarkItDown production activation and post-activation closure

## What was requested

The prompt required two closure tasks after MarkItDown activation:

1. Explain why ABS certification stayed `PENDING`.
2. Fix the missing `docsreg_learning.jsonl` entry for the attempted DOCSREG cycle.

The goal was not to weaken certification gates and not to rebuild MarkItDown. The intended outcome was a production-ready closure analysis and a learning-entry fix for attempted cycles that reached `quality_report.json`.

## What was actually done

The slot32 run did complete meaningful work:

1. MarkItDown was made usable in production-style runs through adapter fallback to `.venv-markitdown`.
2. DOCGEN comparison-only normalization was wired for standards comparison.
3. Real ABS fixture testing was added and executed.
4. Full DOCSREG regression stayed green.
5. A full ABS DOCSREG attempt was run and produced `raw_extracted_text.md`, `extraction_report.json`, and `quality_report.json`.

Those are real implementation wins.

## What was not completed

Two closure items remained open:

1. `certification_status` stayed `PENDING`.
2. No `docsreg_learning.jsonl` entry was found for the attempted ABS cycle.

The second item is the more important process failure for slot32: the model stopped at evidence and status narration instead of tracing the actual call path that writes learning data.

## Exact diagnosis

### Why certification stayed `PENDING`

The DOCSREG cycle reaches `PENDING` in `task_master_registered()` when certification is not `CERTIFIED`.

Relevant path:

- [ops/docsreg/docsreg_tasks.py](</home/axi_omi_sphere/aims-workspace/ops/docsreg/docsreg_tasks.py>)
- `task_quality_validated()` computes the composite quality gate.
- `task_registration_precheck_ready()` requires `quality_gate == PASS` and `has_content`.
- `task_certified_master_ready()` builds a `RegistrationRecord`.
- `task_master_registered()` skips the master-document and Qdrant write unless `cert_status == "CERTIFIED"`.

Observed ABS evidence:

- quality report existed
- MarkItDown extraction succeeded
- `master_decision` was `CERTIFIED`
- composite quality resolved to `0.85`
- final `certification_status` remained `PENDING`
- documents/Qdrant write was skipped

This is not a MarkItDown failure. It is a downstream package/certification gate.

### Why `docsreg_learning.jsonl` was missing

The learning write exists in the Telegram wrapper path, not in the batch runner path.

Relevant paths:

- [ops/omi_telegram/docsreg_launch.py](</home/axi_omi_sphere/aims-workspace/ops/omi_telegram/docsreg_launch.py>)
- `_record_cycle_learning()` calls `record_knowledge_source()`
- `cmd_docsreg()` invokes `_record_cycle_learning()` after each cycle

Relevant batch path:

- [ops/docsreg/pipelines/run_batch.py](</home/axi_omi_sphere/aims-workspace/ops/docsreg/pipelines/run_batch.py>)
- it calls `run_docsreg_cycle()` directly
- `run_docsreg_cycle()` does not write `docsreg_learning.jsonl`

So the attempted ABS batch run could produce `quality_report.json` and still not write learning artifacts, because the path that owns learning capture was never invoked.

This is the main “read but did not execute the full chain” pattern.

## Pattern failures to teach slot32

### 1. Evidence completion was treated as feature completion

The model produced logs, summaries, and a safety-gated status, then implied closure.

What was still missing:

- explicit diagnosis of the `PENDING` gate
- a learning write on the batch path
- proof that the attempted cycle created `docsreg_learning.jsonl`

Lesson:

- a report is not the same as the requested production effect
- evidence only counts if it proves the intended artifact exists on disk

### 2. The model stopped at the first visible success

The run had several successes:

- MarkItDown extraction passed
- DOCGEN comparison-only normalization passed
- regression stayed green

But the prompt was about post-activation closure. Slot32 stopped at the success it could see first, not the closure item that remained open.

Lesson:

- keep the closure target in view until every requested artifact is verified
- do not stop at “good enough evidence” when the prompt asks for a missing file or a specific gate explanation

### 3. The model relied on narrative instead of path tracing

The output said the system was “activated” and “safe,” but the real question was:

- where does the batch run call `record_knowledge_source()`?

That question reveals the gap immediately:

- Telegram path: yes
- batch runner path: no

Lesson:

- trace the function chain
- identify the owner of each artifact
- do not assume a downstream artifact exists just because earlier stages completed

### 4. The model did not convert findings into a repair plan

The correct next step after identifying the missing learning entry was to patch the batch flow or add a batch-side learning hook.

Instead, the run ended with status commentary.

Lesson:

- when the prompt asks for a fix, output must be a fix or an explicit blocker
- if the missing artifact is path-dependent, the path must be changed or the run must be rerouted

### 5. Safety gates were not confused with completion gates

This part was handled correctly:

- raw MarkItDown output was not certified without master/package gates
- DOCGEN normalization remained comparison-only

That should be preserved.

The mistake was elsewhere:

- the model treated “safety preserved” as if it implied “task complete”

It does not.

## Correct behavior for future slot32 runs

1. Verify the exact file or artifact the prompt requires.
2. Trace the real call path that owns that artifact.
3. Distinguish between batch, Telegram, and cycle runner paths.
4. If a file is missing, identify whether the code path was never invoked or whether a gate blocked it.
5. Do not close the task until the required file exists or the blocker is explicitly named.
6. If a learning artifact is required, ensure the path that runs the attempted cycle also calls the learning writer.
7. Keep certification gates intact, but do not let them hide missing closure work.

## Teachable checklist for slot32

Before claiming completion, slot32 must verify:

1. The prompt-required files exist.
2. The call path reaches the artifact writer.
3. The artifact writer wrote the file.
4. The file is on the expected path.
5. The final status matches the actual artifact state.
6. A “PASS” state is not being used to cover a missing postcondition.

## Summary for the repairman / coder model

The model was strong on:

- identifying the MarkItDown integration surface
- producing tests
- running real fixture checks
- keeping safety gates intact

The model was weak on:

- post-activation closure
- finding the exact owner of `docsreg_learning.jsonl`
- distinguishing batch-path execution from Telegram-path execution
- converting a diagnostic conclusion into an actual repair

The key lesson is simple:

> smoke evidence is not feature completion

For this project, slot32 must prove the artifact exists on disk in the right path, not only that the surrounding pipeline printed success-like messages.
