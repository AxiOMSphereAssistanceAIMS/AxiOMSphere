# 65 — Permanent Repair Certification Harness

The NAR-009 harness is the permanent assurance capability. It provisions a disposable target, injects a reversible fault, uses the normal proposal/attestation/permit/revalidation/queue/Repairman path, verifies, rolls back to the fault baseline, emits immutable evidence, removes target/queue/governed store and is rerunnable. It has no production-only bypass and no certification marker that expands authority.

Two sequential runs completed after the cleanup/rollback correction; both returned `NAR009_GOVERNED_FAULT_INJECTION_RESTART_CERTIFIED_COMPLETED_VERIFIED` with duplicate restart reconciliation and cleanup receipt.
