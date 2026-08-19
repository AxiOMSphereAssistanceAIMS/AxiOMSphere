# 64 — Identity and Lineage Model

`correlation_root_id` is the causal root. `failure_id` identifies the observed failure; `repair_case_id` is the governed case aggregate; `repair_id` is the queue execution lineage. A proposal binds the case to `source_hash`, candidate tree/diff hashes and evidence manifest hash. Attestation binds the exact proposal and current policy revision. Permit binds proposal, attestation, policy revision/hash, exact scope and a nonce. Revalidation binds the old proposal/policy to the current revision. Restart binds the same `repair_id` and lineage parent to a fresh permit via `repair_case_id:permit_id` idempotency. Completion evidence closes the same queue row.

Any changed proposal, candidate, source, attestation, policy, scope, permit expiry or approval freshness invalidates execution. No subsystem may generate a new repair identity during restart.
