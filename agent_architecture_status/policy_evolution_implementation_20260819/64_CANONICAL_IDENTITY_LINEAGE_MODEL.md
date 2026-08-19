# 64 — Canonical Production Identity Lineage

The causal root is preserved from `failure_id` and `correlation_root_id` through `repair_case_id`, `repair_id`, `canonical_repair_identity`, proposal/hash, candidate hashes, attestation/hash, policy revision/hash, permit/hash, Owner approval/hash, revalidation/hash, restart/hash, queue event and completion evidence. A retry never creates a new semantic repair. A duplicate restart uses the same `repair_case_id:permit_id` idempotency key. Source, policy, proposal, attestation, approval or scope drift invalidates downstream records.
