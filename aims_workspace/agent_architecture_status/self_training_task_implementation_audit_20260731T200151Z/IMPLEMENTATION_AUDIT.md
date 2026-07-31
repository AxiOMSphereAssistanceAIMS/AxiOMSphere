# Self-training task implementation audit

Source: `/home/axi_omi_sphere/Downloads/AIMS_Full_Self_Training_Pipelines_Production_Readiness_Claude_Code_Task.md`

## Executive result

The project has a real, scheduler-owned and fail-closed raw-clearance infrastructure, but it does not yet satisfy the task's full real-data production criterion. The three-slot result previously reported as PASS was a fixture-only routing proof. It must not be interpreted as real training-data readiness.

## Already implemented

- Knomi and Traini are separate paths.
- `closed_loop.py` produces bounded knowledge cards and excludes raw transcript bodies from Knomi indexing.
- `raw_material_pair_preparation.py` and its admission gate produce/quarantine slot pools and keep agent-skill material out of model datasets.
- Terminal session checks, source hashes, cursor/closeout controls, Redis Scheduler ownership and worker runtime are present.
- Raw lifecycle baseline is closed: 143/143 items have dispositions, no unresolved item lacks a disposition, and holds have recheck conditions.
- Slot14/32/120 route isolation and no-training handoff logic are proven on explicitly excluded fixtures.
- Training remains fail-closed; no training, promotion, registry mutation or slot mutation was performed.

## Not complete or not proven on real data

1. The live pair-synthesis producer does not reliably emit the admission contract fields required by its own gate: `holdout_separation`, `independent_reviewer`, `raw_source_hash`, `prepared_answer_hash`, and a slot-specific `response_contract`.
2. Consequently real candidates are rejected before independent admission; real admitted output remains zero in the audited path (Slot14 historical verified count remains 4/750 in the prior evidence).
3. Three-slot decomposition/routing was demonstrated with `production_training_eligible=false` fixtures only. No real-data three-slot cycle has been proven.
4. `failure_closure_registry.py` is a report builder over one hardcoded historical feedback path. It is not an automatic repair queue, sandbox validator, activation gate, rollback mechanism or failed-stage rerunner.
5. `codex/summaries` is stale but still read by active modules. It should remain compatibility-read-only until reader migration is proven.

## Required implementation order

Repair the synthesis contract first, then rerun the real scheduled cycle. Do not bypass the missing metadata with defaults: hashes, reviewer identity, holdout separation and verification must be derived from actual evidence. After real candidates reach independent clearance, implement/verify the multi-route real-data path, then close the automatic skill-repair loop with bounded repair, sandbox validation, regression, activation, rollback and rerun. Only after those gates pass should downstream training readiness be reconsidered.

## Safe current status

`RAW CLEARANCE: PRODUCTION_READY`

`REAL LEARNING/PAIR PIPELINE: NOT_PRODUCTION_READY`

`TRAINING: NOT_READY / FAIL_CLOSED`

`NEXT SAFE ACTION: repair pair-synthesis metadata production and rerun the real five-hour cycle; never ingest raw Codex transcripts directly as training answers.`
