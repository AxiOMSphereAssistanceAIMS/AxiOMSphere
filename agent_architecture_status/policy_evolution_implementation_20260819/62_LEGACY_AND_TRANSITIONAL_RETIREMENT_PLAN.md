# 62 — Legacy and Transitional Retirement Plan

| Mechanism | Current authority | End state | Migration/cutoff | Removal or safety condition | Evidence |
|---|---|---|---|---|---|
| ALLOW/DENY policy projection | legacy callers only | compatibility read-only | every execution caller uses ExecutionPermit; no direct decision authority | projection returns `execution_authority: NONE`; remove after caller census is zero | `project_legacy`, integration tests |
| unbound auditor/approval records | historical stores | re-audit or evidence hold | no new execution from records without exact hashes | `LEGACY_UNBOUND` + `REAUDIT_REQUIRED` | contract tests |
| old repair statuses | historical queue/projections | map into canonical lifecycle | read projection during migration | no unknown state accepted by state model | 63 state model |
| legacy Repairman backend | old backend selector/fallback | retired | immediate fail-closed | `LEGACY_REPAIR_BACKEND_RETIRED` | retirement test |
| NAR-009 canary namespace | assurance fixture | reusable assurance capability | retained as disposable test namespace only | cleanup after every run; production roots forbidden | 65/cleanup evidence |
| queue rewrite implementation | previous direct truncate/write | atomic existing queue authority | immediate code cutover | lock + fsync + replace + CAS tests | queue tests |

No compatibility shim is an execution authority. Transitional reads are bounded by explicit reason codes and next actions; they are not an indefinite second pipeline.
