# 68 — Production Retention and Cleanup Model

Failure, proposal, attestation, permit, approval, revalidation, restart, queue and completion records retain immutable hashes and causal references under their owning store. Completed/obsolete cases may be archived only after evidence and lineage are preserved. Canary targets, queues, governed stores, temporary worktrees and build artifacts are disposable; the harness removes them and emits a cleanup receipt. Cleanup cannot delete protected production source or certification evidence. Training/raw-material admission remains separate.
