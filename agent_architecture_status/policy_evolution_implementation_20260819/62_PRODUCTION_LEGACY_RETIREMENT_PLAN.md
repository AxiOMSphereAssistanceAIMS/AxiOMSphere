# 62 — Production Legacy Retirement Plan

| Legacy/transitional path | Target | Enforced retirement condition | Evidence |
|---|---|---|---|
| ALLOW/DENY projection | read-only compatibility | `execution_authority=NONE` and caller census reaches zero | `project_legacy` tests |
| unbound auditor/approval records | re-audit or evidence hold | no execution without exact hashes | contract rejection |
| old statuses | canonical state model | unknown/illegal transitions rejected | state tests |
| legacy Repairman backend | retired fail-closed | `LEGACY_REPAIR_BACKEND_RETIRED` | retirement test |
| direct queue truncate/write | atomic existing queue transaction | runtime loaded queue hash certified | runtime hash proof |
| disposable canary artifacts | cleanup after each run | cleanup receipt all true | cleanup receipt |

No duplicate store, queue or synchronizer was introduced. Compatibility reads have no execution authority.
