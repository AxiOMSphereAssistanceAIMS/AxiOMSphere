# 65 — Permanent Assurance Harness Architecture

`ops/policy_evolution/nar009_fault_injection_canary.py` is treated as a reusable assurance capability, not a one-off bypass. It creates a disposable target, injects a reversible defect, passes the normal contract/attestation/permit/revalidation path, mutates the existing queue authority in a certification namespace, exercises same-lineage CAS and duplicate reconciliation, applies a bounded patch, verifies, completes, and emits immutable evidence. The namespace is path-bound and never production.

The same harness is suitable for regression, release, and incident-recovery certification. Its permanent guarantees are target isolation, bounded execution, exact hashes, queue idempotency, cleanup-by-recreate, and explicit production-mutation=false evidence.
