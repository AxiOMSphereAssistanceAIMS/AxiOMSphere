# 67 — Observability and Operability

Permanent evidence fields are: lifecycle state/next action, repair/case/correlation identity, policy revision/hash, proposal/attestation/permit hashes, permit expiry, queue status/attempts, restart idempotency key, duplicate reconciliation result, verification result, rollback result, policy-gap classification, and runtime module hashes. Operators can distinguish evidence-required, authority-review, stale, retry-conflict, policy-gap, completed, and obsolete outcomes without inferring from free text.

The existing Logi and runtime status artifacts remain the operational surface. The new queue transaction records lock/CAS outcomes in returned statuses; no separate dashboard or parallel store was created.
